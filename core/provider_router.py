"""
Minimal provider router for translation requests.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, Optional


QUOTA_HINTS = ("429", "quota", "rate limit", "rate_limit", "resource exhausted", "too many requests")
TIMEOUT_HINTS = ("timeout", "timed out")
MODEL_UNAVAILABLE_HINTS = ("404", "410", "not found", "model unavailable")
TOKEN_LIMIT_HINTS = ("token limit", "token_limit", "prompt token", "context length")


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
    error_type: str = ""
    error_message: str = ""
    latency_ms: int = 0
    from_cache: bool = False
    attempts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProviderState:
    provider_name: str
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


class ProviderRouter:
    """Runtime-only provider router with cooldown and health tracking."""

    def __init__(self, cooldown_seconds: int = 300, max_retries: int = 2):
        self.cooldown_seconds = max(1, int(cooldown_seconds))
        self.max_retries = max(0, int(max_retries))
        self._providers: dict[str, Any] = {}
        self._provider_states: dict[str, ProviderState] = {}

    def register_provider(self, provider: Any) -> None:
        self._providers[provider.name] = provider
        self._ensure_state(provider.name, getattr(provider, "default_model", ""))

    def route(self, request: TranslationRequest, policy: Optional[dict[str, Any]] = None) -> TranslationResult:
        policy = policy or {}
        allowed = policy.get("allowed_providers")
        ordered_names = self._resolve_order(policy.get("provider_order"), allowed)
        max_attempts = min(len(ordered_names), self.max_retries + 1) if ordered_names else 0
        attempts: list[dict[str, Any]] = []

        if max_attempts <= 0:
            return TranslationResult(
                status="error",
                error_type="no_provider_available",
                error_message="No eligible translation providers are available.",
                attempts=attempts,
            )

        for provider_name in ordered_names[:max_attempts]:
            provider = self._providers.get(provider_name)
            if provider is None:
                continue

            model_name = getattr(provider, "default_model", "")
            state = self._ensure_state(provider.name, model_name)
            if not provider.is_available():
                state.is_available = False
                state.last_error_type = "unavailable"
                attempts.append(
                    {
                        "provider": provider.name,
                        "model": model_name,
                        "status": "skipped",
                        "reason": "unavailable",
                    }
                )
                continue

            if self._is_on_cooldown(state):
                attempts.append(
                    {
                        "provider": provider.name,
                        "model": model_name,
                        "status": "skipped",
                        "reason": "cooldown",
                    }
                )
                continue

            result = provider.translate(request)
            result.provider = result.provider or provider.name
            result.model = result.model or model_name

            if result.status == "success":
                self.mark_success(result.provider, result.model, result.latency_ms)
                attempts.append(
                    {
                        "provider": result.provider,
                        "model": result.model,
                        "status": "success",
                        "latency_ms": result.latency_ms,
                    }
                )
                result.attempts = attempts
                return result

            error_detail = result.error_type or result.error_message or "provider_error"
            self.mark_failure(result.provider or provider.name, result.model or model_name, error_detail, result.latency_ms)
            attempts.append(
                {
                    "provider": result.provider or provider.name,
                    "model": result.model or model_name,
                    "status": "failed",
                    "reason": result.error_type or "error",
                    "message": result.error_message,
                    "latency_ms": result.latency_ms,
                }
            )

        final_attempt = attempts[-1] if attempts else {}
        return TranslationResult(
            status="error",
            provider=str(final_attempt.get("provider", "")),
            model=str(final_attempt.get("model", "")),
            error_type=str(final_attempt.get("reason", "no_provider_available")),
            error_message=str(final_attempt.get("message", "No translation provider succeeded.")),
            latency_ms=int(final_attempt.get("latency_ms", 0) or 0),
            attempts=attempts,
        )

    def mark_success(self, provider: str, model: str, latency_ms: int = 0) -> None:
        state = self._ensure_state(provider, model)
        state.model = model or state.model
        state.is_available = True
        state.cooldown_until = 0.0
        state.consecutive_failures = 0
        state.last_error_type = ""
        state.last_latency_ms = max(0, int(latency_ms or 0))
        state.success_count += 1

    def mark_failure(self, provider: str, model: str, error: Any, latency_ms: int = 0) -> None:
        state = self._ensure_state(provider, model)
        error_type = classify_error(error)
        state.model = model or state.model
        state.is_available = error_type != "auth_failure"
        state.consecutive_failures += 1
        state.last_error_type = error_type
        state.last_latency_ms = max(0, int(latency_ms or 0))
        state.failure_count += 1
        if error_type in {
            "auth_failure",
            "quota_rate_limit",
            "token_limit",
            "timeout",
            "model_unavailable",
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

    def _resolve_order(self, preferred: Optional[Iterable[str]], allowed: Optional[Iterable[str]]) -> list[str]:
        allowed_set = {item for item in (allowed or self._providers.keys()) if item in self._providers}
        order = [name for name in (preferred or self._providers.keys()) if name in allowed_set]
        for name in allowed_set:
            if name not in order:
                order.append(name)
        return order

    def _ensure_state(self, provider: str, model: str = "") -> ProviderState:
        key = f"{provider}::{model}"
        if key not in self._provider_states:
            self._provider_states[key] = ProviderState(provider_name=provider, model=model)
        return self._provider_states[key]

    def _is_on_cooldown(self, state: ProviderState, now: Optional[float] = None) -> bool:
        if state.cooldown_until <= 0:
            return False
        current = now if now is not None else time.time()
        return state.cooldown_until > current


def classify_error(error: Any) -> str:
    if isinstance(error, str):
        detail = error.lower()
    else:
        detail = str(error or "").lower()

    if any(token in detail for token in QUOTA_HINTS):
        return "quota_rate_limit"
    if any(token in detail for token in TOKEN_LIMIT_HINTS):
        return "token_limit"
    if any(token in detail for token in TIMEOUT_HINTS):
        return "timeout"
    if any(token in detail for token in MODEL_UNAVAILABLE_HINTS):
        return "model_unavailable"
    if "401" in detail or "auth" in detail or "api key" in detail or "invalid key" in detail:
        return "auth_failure"
    if "503" in detail or "502" in detail or "500" in detail or "server error" in detail:
        return "provider_5xx"
    return "unknown_transport_error"
