"""
Minimal provider router for translation requests.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, Optional


AUTH_HINTS = (
    "401",
    "403",
    "unauthorized",
    "authentication",
    "auth failure",
    "invalid api key",
    "incorrect api key",
    "permission denied",
    "forbidden",
    "api key",
    "invalid key",
)
QUOTA_HINTS = ("429", "quota", "rate limit", "rate_limit", "resource exhausted", "too many requests")
TIMEOUT_HINTS = ("timeout", "timed out")
TRANSPORT_HINTS = (
    "connection failed",
    "connection aborted",
    "connection refused",
    "connection reset",
    "connection error",
    "actively refused",
    "winerror 10061",
    "winerror 10054",
    "winerror 11001",
    "remote end closed connection",
    "temporary failure in name resolution",
    "name or service not known",
    "no address associated with hostname",
    "network is unreachable",
    "failed to establish a new connection",
    "max retries exceeded",
)
MODEL_UNAVAILABLE_HINTS = ("404", "410", "not found", "model unavailable")
MODEL_ERROR_HINTS = ("invalid model", "model not found", "unknown model", "unsupported model")
TOKEN_LIMIT_HINTS = ("token limit", "token_limit", "prompt token", "context length")
PROVIDER_5XX_HINTS = ("500", "502", "503", "504", "server error", "bad gateway", "service unavailable", "gateway timeout")


@dataclass
class TranslationRequest:
    text: str
    source_lang: str
    target_lang: str
    context: str = ""
    glossary_terms: list[dict[str, Any]] = field(default_factory=list)
    strategy: str = "waterfall"
    job_id: Optional[str] = None


@dataclass
class TranslationResult:
    status: str
    text: str = ""
    provider: str = ""
    model: str = ""
    key_id: str = ""
    key_index: int = -1
    error_type: str = ""
    error_message: str = ""
    latency_ms: int = 0
    from_cache: bool = False
    attempts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProviderState:
    provider_name: str
    display_name: str = ""
    model: str = ""
    key_id: Optional[str] = None
    key_index: Optional[int] = None
    is_available: bool = True
    cooldown_until: float = 0.0
    consecutive_failures: int = 0
    last_error_type: str = ""
    last_latency_ms: int = 0
    success_count: int = 0
    failure_count: int = 0

    # New fields for Phase 5I
    free_quota: dict[str, Any] = field(default_factory=dict)
    rpm_limit: int = 0
    tpm_limit: int = 0
    daily_limit: int = 0
    health_status: str = "healthy"
    last_error_class: str = ""
    quality_score: float = 5.0
    latency_score: float = 0.0
    capabilities: dict[str, Any] = field(default_factory=dict)


class ProviderRouter:
    """Runtime-only provider router with cooldown and health tracking."""

    def __init__(self, cooldown_seconds: int = 300, max_retries: int = 2):
        self.cooldown_seconds = max(1, int(cooldown_seconds))
        self.max_retries = max(0, int(max_retries))
        self._providers: dict[str, Any] = {}
        self._provider_states: dict[str, ProviderState] = {}

    def register_provider(self, provider: Any) -> None:
        self._providers[provider.name] = provider
        self._ensure_state(
            provider.name,
            getattr(provider, "default_model", ""),
            display_name=getattr(provider, "display_name", provider.name),
        )

    def route(self, request: TranslationRequest, policy: Optional[dict[str, Any]] = None) -> TranslationResult:
        policy = policy or {}
        allowed = policy.get("allowed_providers")
        ordered_names = self._resolve_order(policy.get("provider_order"), allowed, policy)
        max_attempts = self.max_retries + 1 if ordered_names else 0
        attempts: list[dict[str, Any]] = []
        total_attempts = 0

        if max_attempts <= 0:
            return TranslationResult(
                status="error",
                error_type="no_provider_available",
                error_message="No eligible translation providers are available.",
                attempts=attempts,
            )

        for provider_name in ordered_names:
            provider = self._providers.get(provider_name)
            if provider is None:
                continue

            if not provider.is_available():
                model_name = getattr(provider, "default_model", "")
                state = self._ensure_state(
                    provider.name,
                    model_name,
                    display_name=getattr(provider, "display_name", provider.name),
                )
                state.is_available = False
                state.last_error_type = "unavailable"
                attempts.append(
                    {
                        "provider": provider.name,
                        "display_name": getattr(provider, "display_name", provider.name),
                        "model": model_name,
                        "status": "skipped",
                        "reason": "unavailable",
                    }
                )
                continue

            candidates = self._filter_candidates(provider, list(provider.iter_candidates()) or [], policy)
            if not candidates:
                pinned_model = self._get_strict_provider_model(policy, provider.name) or getattr(provider, "default_model", "")
                message = ""
                reason = "unavailable"
                if self._get_strict_provider_model(policy, provider.name):
                    reason = "model_unavailable"
                    message = (
                        f"Configured default model '{pinned_model}' is not available for "
                        f"{getattr(provider, 'display_name', provider.name)}."
                    )
                attempts.append(
                    {
                        "provider": provider.name,
                        "display_name": getattr(provider, "display_name", provider.name),
                        "model": pinned_model,
                        "status": "skipped",
                        "reason": reason,
                        "message": message,
                    }
                )
                continue

            for candidate in candidates:
                if total_attempts >= max_attempts:
                    break

                state = self._ensure_state(
                    provider.name,
                    candidate.model or getattr(provider, "default_model", ""),
                    key_index=candidate.key_index,
                    key_id=candidate.key_id,
                    display_name=getattr(provider, "display_name", provider.name),
                )
                if self._is_on_cooldown(state):
                    attempts.append(
                        {
                            "provider": provider.name,
                            "display_name": getattr(provider, "display_name", provider.name),
                            "model": candidate.model,
                            "key_index": candidate.key_index,
                            "key_id": candidate.key_id,
                            "status": "skipped",
                            "reason": "cooldown",
                        }
                    )
                    continue

                total_attempts += 1
                result = provider.translate(request, candidate)
                result.provider = result.provider or provider.name
                result.model = result.model or candidate.model or getattr(provider, "default_model", "")
                result.key_index = candidate.key_index
                result.key_id = candidate.key_id

                if result.status == "success":
                    self.mark_success(
                        result.provider,
                        result.model,
                        result.latency_ms,
                        key_index=candidate.key_index,
                        key_id=candidate.key_id,
                        display_name=getattr(provider, "display_name", provider.name),
                    )
                    provider.mark_success(candidate)
                    attempts.append(
                        {
                            "provider": result.provider,
                            "display_name": getattr(provider, "display_name", provider.name),
                            "model": result.model,
                            "key_index": candidate.key_index,
                            "key_id": candidate.key_id,
                            "status": "success",
                            "latency_ms": result.latency_ms,
                        }
                    )
                    result.attempts = attempts
                    return result

                error_detail = result.error_type or result.error_message or "provider_error"
                self.mark_failure(
                    result.provider or provider.name,
                    result.model or candidate.model or getattr(provider, "default_model", ""),
                    error_detail,
                    result.latency_ms,
                    key_index=candidate.key_index,
                    key_id=candidate.key_id,
                    display_name=getattr(provider, "display_name", provider.name),
                )
                provider.mark_failure(candidate, result.error_type or "error")
                attempts.append(
                    {
                        "provider": result.provider or provider.name,
                        "display_name": getattr(provider, "display_name", provider.name),
                        "model": result.model or candidate.model or getattr(provider, "default_model", ""),
                        "key_index": candidate.key_index,
                        "key_id": candidate.key_id,
                        "status": "failed",
                        "reason": result.error_type or "error",
                        "message": result.error_message,
                        "latency_ms": result.latency_ms,
                    }
                )

            if total_attempts >= max_attempts:
                break

        final_attempt = attempts[-1] if attempts else {}
        error_message = str(final_attempt.get("message", "No translation provider succeeded."))
        strict_model = self._get_strict_provider_model(policy, str(final_attempt.get("provider", "")))
        if strict_model and str(final_attempt.get("model", "")) == strict_model and final_attempt.get("status") == "failed":
            display_name = str(final_attempt.get("display_name", final_attempt.get("provider", "provider")))
            base_message = error_message or str(final_attempt.get("reason", "provider_error"))
            error_message = f"{display_name} default model '{strict_model}' failed: {base_message}"
        return TranslationResult(
            status="error",
            provider=str(final_attempt.get("provider", "")),
            model=str(final_attempt.get("model", "")),
            error_type=str(final_attempt.get("reason", "no_provider_available")),
            error_message=error_message,
            latency_ms=int(final_attempt.get("latency_ms", 0) or 0),
            attempts=attempts,
        )

    def mark_success(
        self,
        provider: str,
        model: str,
        latency_ms: int = 0,
        *,
        key_index: int | None = None,
        key_id: str | None = None,
        display_name: str = "",
    ) -> None:
        state = self._ensure_state(provider, model, key_index=key_index, key_id=key_id, display_name=display_name)
        state.model = model or state.model
        state.is_available = True
        state.cooldown_until = 0.0
        state.consecutive_failures = 0
        state.last_error_type = ""
        state.last_latency_ms = max(0, int(latency_ms or 0))
        state.success_count += 1

        # New dynamic metadata tracking for Phase 5I
        state.health_status = "healthy"
        if latency_ms > 0:
            if state.latency_score <= 0:
                state.latency_score = float(latency_ms)
            else:
                state.latency_score = 0.8 * state.latency_score + 0.2 * float(latency_ms)

    def mark_failure(
        self,
        provider: str,
        model: str,
        error: Any,
        latency_ms: int = 0,
        *,
        key_index: int | None = None,
        key_id: str | None = None,
        display_name: str = "",
    ) -> None:
        state = self._ensure_state(provider, model, key_index=key_index, key_id=key_id, display_name=display_name)
        error_type = classify_error(error)
        state.model = model or state.model
        state.is_available = error_type != "auth_failure"
        state.consecutive_failures += 1
        state.last_error_type = error_type
        state.last_latency_ms = max(0, int(latency_ms or 0))
        state.failure_count += 1

        # New dynamic metadata tracking for Phase 5I
        state.last_error_class = error_type
        if error_type == "auth_failure":
            state.health_status = "dead"
            # Call AIConfigManager to persistently disable the provider
            try:
                from translation_app.core.ai_service import get_ai_service
                service = get_ai_service()
                if service and service.config_manager:
                    service.config_manager.update_provider_enabled(provider, False)
                    service.config_manager.save_config()
            except Exception:
                pass
        elif error_type in ("quota_rate_limit", "token_limit"):
            state.health_status = "cooldown"
        elif error_type in ("timeout", "provider_5xx"):
            state.health_status = "degraded"

        if latency_ms > 0:
            if state.latency_score <= 0:
                state.latency_score = float(latency_ms)
            else:
                state.latency_score = 0.8 * state.latency_score + 0.2 * float(latency_ms)

        if error_type in {
            "auth_failure",
            "quota_rate_limit",
            "token_limit",
            "timeout",
            "transport_error",
            "model_unavailable",
            "model_error",
            "provider_5xx",
            "unknown_transport_error",
        }:
            state.cooldown_until = time.time() + self.cooldown_seconds

    def get_health_snapshot(self) -> list[dict[str, Any]]:
        snapshots = []
        now = time.time()
        for state in self._provider_states.values():
            payload = asdict(state)
            payload["is_available"] = state.is_available and not self._is_on_cooldown(state, now)
            payload["cooldown_until"] = round(state.cooldown_until, 3) if state.cooldown_until else 0.0
            snapshots.append(payload)
        snapshots.sort(key=lambda item: (item["provider_name"], item["model"]))
        return snapshots

    def reset_cooldowns(self) -> None:
        for state in self._provider_states.values():
            state.cooldown_until = 0.0
            state.is_available = True
            state.consecutive_failures = 0
            state.last_error_type = ""
            state.health_status = "healthy"

    def _resolve_order(self, preferred: Optional[Iterable[str]], allowed: Optional[Iterable[str]], policy: Optional[dict[str, Any]] = None) -> list[str]:
        policy = policy or {}
        policy_mode = policy.get("mode", "")
        allowed_set = {item for item in (allowed or self._providers.keys()) if item in self._providers}

        # If we have one of the free AI pool policies, we dynamically rank them!
        if policy_mode in ("ai_pool_auto", "ai_pool_no_google", "ai_pool_with_google_last_resort"):
            def get_provider_rank(name):
                # Aggregate states for this provider name
                provider_states = [s for s in self._provider_states.values() if s.provider_name == name]
                if not provider_states:
                    provider_states = [self._ensure_state(name)]

                is_available = any(s.is_available for s in provider_states)
                is_cooldown = all(self._is_on_cooldown(s) for s in provider_states)

                # Check aggregated health_status
                health_set = {s.health_status for s in provider_states}
                if "healthy" in health_set:
                    health_status = "healthy"
                elif "degraded" in health_set:
                    health_status = "degraded"
                elif "cooldown" in health_set:
                    health_status = "cooldown"
                else:
                    health_status = "dead"

                is_google = (name == "google")

                if not is_available:
                    status_rank = 4
                elif is_cooldown:
                    status_rank = 3
                elif is_google and policy_mode == "ai_pool_with_google_last_resort":
                    status_rank = 2
                elif health_status == "degraded":
                    status_rank = 1
                else:
                    status_rank = 0

                quality = max((getattr(s, "quality_score", 5.0) for s in provider_states), default=5.0)
                latencies = [getattr(s, "latency_score", 0.0) for s in provider_states if getattr(s, "latency_score", 0.0) > 0]
                latency = sum(latencies) / len(latencies) if latencies else 500.0

                return (status_rank, -quality, latency)

            sorted_names = sorted(allowed_set, key=get_provider_rank)
            return sorted_names

        order = [name for name in (preferred or self._providers.keys()) if name in allowed_set]
        for name in allowed_set:
            if name not in order:
                order.append(name)
        return order

    def _ensure_state(
        self,
        provider: str,
        model: str = "",
        *,
        key_index: int | None = None,
        key_id: str | None = None,
        display_name: str = "",
    ) -> ProviderState:
        key = f"{provider}::{model}::{key_index if key_index is not None else -1}"
        if key not in self._provider_states:
            quality_scores = {
                "gemini": 9.0,
                "groq": 7.5,
                "cerebras": 7.5,
                "openrouter": 8.0,
                "mistral": 7.0,
                "sambanova": 7.5,
                "github": 7.5,
                "ai21": 7.5,
                "cloudflare": 6.5,
                "huggingface": 6.5,
                "google": 5.0,
            }
            self._provider_states[key] = ProviderState(
                provider_name=provider,
                display_name=display_name or provider,
                model=model,
                key_id=key_id or None,
                key_index=key_index,
                quality_score=quality_scores.get(provider, 5.0),
            )
        return self._provider_states[key]

    def _is_on_cooldown(self, state: ProviderState, now: Optional[float] = None) -> bool:
        if state.cooldown_until <= 0:
            return False
        current = now if now is not None else time.time()
        return state.cooldown_until > current

    def _filter_candidates(self, provider: Any, candidates: list[Any], policy: dict[str, Any]) -> list[Any]:
        strict_model = self._get_strict_provider_model(policy, provider.name)
        if not strict_model:
            return candidates
        return [
            candidate
            for candidate in candidates
            if (getattr(candidate, "model", "") or getattr(provider, "default_model", "")) == strict_model
        ]

    def _get_strict_provider_model(self, policy: dict[str, Any], provider_name: str) -> str:
        strict_provider_models = policy.get("strict_provider_models", {})
        if not isinstance(strict_provider_models, dict):
            return ""
        return str(strict_provider_models.get(provider_name, "") or "").strip()


def classify_error(error: Any, status_code: int | None = None, response_body: Any = None) -> str:
    if status_code in (401, 403):
        return "auth_failure"
    if status_code == 429:
        return "quota_rate_limit"
    if status_code == 400:
        detail_400 = _build_error_detail(error, response_body)
        if any(token in detail_400 for token in MODEL_ERROR_HINTS):
            return "model_error"
    if status_code in (404, 410):
        detail_404 = _build_error_detail(error, response_body)
        if any(token in detail_404 for token in MODEL_ERROR_HINTS + MODEL_UNAVAILABLE_HINTS):
            return "model_unavailable"
    if status_code is not None and 500 <= status_code <= 599:
        return "provider_5xx"

    detail = _build_error_detail(error, response_body)

    if any(token in detail for token in AUTH_HINTS):
        return "auth_failure"
    if any(token in detail for token in QUOTA_HINTS):
        return "quota_rate_limit"
    if "400" in detail and any(token in detail for token in MODEL_ERROR_HINTS):
        return "model_error"
    if any(token in detail for token in TOKEN_LIMIT_HINTS):
        return "token_limit"
    if any(token in detail for token in TIMEOUT_HINTS):
        return "timeout"
    if any(token in detail for token in TRANSPORT_HINTS):
        return "transport_error"
    if any(token in detail for token in MODEL_ERROR_HINTS):
        return "model_error"
    if any(token in detail for token in MODEL_UNAVAILABLE_HINTS):
        return "model_unavailable"
    if any(token in detail for token in PROVIDER_5XX_HINTS):
        return "provider_5xx"
    return "unknown_transport_error"


def _build_error_detail(error: Any, response_body: Any = None) -> str:
    parts: list[str] = []

    if response_body:
        if isinstance(response_body, dict):
            parts.append(" ".join(str(value) for value in response_body.values()))
        else:
            parts.append(str(response_body))

    if isinstance(error, str):
        parts.append(error)
    elif isinstance(error, dict):
        parts.append(" ".join(str(value) for value in error.values()))
    elif error is not None:
        parts.append(type(error).__name__)
        parts.append(str(error))

    return " ".join(part for part in parts if part).lower()
