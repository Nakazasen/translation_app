"""OpenAI-compatible translation provider wrapper with runtime key/model rotation."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from translation_app.core.provider_router import TranslationRequest, TranslationResult, classify_error
from translation_app.core.providers.base import BaseTranslationProvider, ProviderCandidate
from translation_app.core.providers.profiles import ProviderProfile, mask_key_suffix


class OpenAICompatibleProvider(BaseTranslationProvider):
    supports_glossary = True
    supports_ai_prompt = True

    def __init__(
        self,
        *,
        profile: ProviderProfile | None = None,
        enabled: bool = False,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        provider_name: str = "openai_compatible",
        timeout: int = 15,
        allow_no_key_local: bool = False,
        display_name: str = "",
        api_keys: list[str] | None = None,
        models: list[str] | None = None,
    ):
        if profile is None:
            profile = ProviderProfile(
                name=provider_name or "openai_compatible",
                display_name=display_name or provider_name or "OpenAI-Compatible",
                provider_type="openai_compatible",
                enabled=enabled,
                base_url=base_url,
                api_key_pool=list(api_keys or ([api_key] if api_key else [])),
                model_pool=list(models or ([model] if model else [])),
                timeout=timeout,
                supports_glossary=True,
                allow_no_key_local=allow_no_key_local,
            ).normalized()

        self.profile = profile.normalized()
        self.name = self.profile.name
        self.display_name = self.profile.display_name
        self.default_model = self.profile.model_pool[0] if self.profile.model_pool else ""
        self.enabled = self.profile.enabled
        self.base_url = self.profile.base_url.rstrip("/")
        self.api_key_pool = list(self.profile.api_key_pool)
        self.model_pool = list(self.profile.model_pool)
        self.timeout = self.profile.timeout
        self.allow_no_key_local = self.profile.allow_no_key_local
        self._next_key_index = 0
        self._next_model_index = 0

    @property
    def api_key(self) -> str:
        return self.api_key_pool[0] if self.api_key_pool else ""

    def is_available(self) -> bool:
        if not self.enabled or not self.base_url or not self.model_pool:
            return False
        if self.api_key_pool:
            return True
        return self.allow_no_key_local and _is_local_base_url(self.base_url)

    def iter_candidates(self) -> list[ProviderCandidate]:
        if not self.is_available():
            return []

        models = _rotate_list(self.model_pool, self._next_model_index)
        if self.api_key_pool:
            key_entries = list(enumerate(self.api_key_pool))
            key_entries = _rotate_list(key_entries, self._next_key_index)
        else:
            key_entries = [(-1, "")]

        candidates: list[ProviderCandidate] = []
        for model in models:
            for key_index, key_value in key_entries:
                candidates.append(
                    ProviderCandidate(
                        provider_name=self.name,
                        model=model,
                        key_index=key_index,
                        key_id=mask_key_suffix(key_value) if key_index >= 0 else "",
                    )
                )
        return candidates

    def translate(self, request: TranslationRequest, candidate: ProviderCandidate | None = None) -> TranslationResult:
        started = time.time()
        candidate = candidate or ProviderCandidate(
            provider_name=self.name,
            model=self.default_model,
            key_index=0 if self.api_key_pool else -1,
            key_id=mask_key_suffix(self.api_key_pool[0]) if self.api_key_pool else "",
        )
        prompt = _build_prompt(request)
        payload = {
            "model": candidate.model or self.default_model,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {"Content-Type": "application/json"}
        api_key = self._resolve_api_key(candidate.key_index)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        endpoint = f"{self.base_url}/chat/completions" if self.base_url.endswith("/v1") else f"{self.base_url}/v1/chat/completions"

        try:
            raw_body = json.dumps(payload).encode("utf-8")
            http_request = urllib.request.Request(endpoint, data=raw_body, headers=headers, method="POST")
            with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                raw_response = response.read().decode("utf-8")
            data = json.loads(raw_response)
            text = _extract_message_text(data)
            return TranslationResult(
                status="success",
                text=text,
                provider=self.name,
                model=candidate.model or self.default_model,
                key_id=candidate.key_id,
                key_index=candidate.key_index,
                latency_ms=round((time.time() - started) * 1000),
            )
        except urllib.error.HTTPError as exc:
            raw_detail = exc.read().decode("utf-8", errors="replace")
            detail = _sanitize_error_detail(_normalize_error_payload(raw_detail), api_key)
            return TranslationResult(
                status="error",
                provider=self.name,
                model=candidate.model or self.default_model,
                key_id=candidate.key_id,
                key_index=candidate.key_index,
                error_type=classify_error(f"{exc.code} {detail}"),
                error_message=f"HTTP {exc.code}: {detail}",
                latency_ms=round((time.time() - started) * 1000),
            )
        except Exception as exc:
            detail = _sanitize_error_detail(str(exc), api_key)
            return TranslationResult(
                status="error",
                provider=self.name,
                model=candidate.model or self.default_model,
                key_id=candidate.key_id,
                key_index=candidate.key_index,
                error_type=classify_error(detail),
                error_message=detail,
                latency_ms=round((time.time() - started) * 1000),
            )

    def mark_success(self, candidate: ProviderCandidate) -> None:
        if self.api_key_pool:
            self._next_key_index = (max(0, candidate.key_index) + 1) % len(self.api_key_pool)
        if self.model_pool and candidate.model in self.model_pool:
            self._next_model_index = self.model_pool.index(candidate.model)

    def mark_failure(self, candidate: ProviderCandidate, error_type: str) -> None:
        if self.api_key_pool and error_type in {"auth_failure", "quota_rate_limit", "transport_error", "timeout", "provider_5xx"}:
            self._next_key_index = (max(0, candidate.key_index) + 1) % len(self.api_key_pool)
        if self.model_pool and candidate.model in self.model_pool and error_type in {"model_error", "model_unavailable", "token_limit"}:
            self._next_model_index = (self.model_pool.index(candidate.model) + 1) % len(self.model_pool)

    def _resolve_api_key(self, key_index: int) -> str:
        if key_index is None or key_index < 0 or key_index >= len(self.api_key_pool):
            return ""
        return self.api_key_pool[key_index]


def _build_prompt(request: TranslationRequest) -> str:
    glossary_lines = []
    for term in request.glossary_terms:
        source = str(term.get("source_term", "")).replace("\r", " ").replace("\n", " ").strip()
        target = str(term.get("target_term", "")).replace("\r", " ").replace("\n", " ").strip()
        if source and target:
            glossary_lines.append(f"{source} => {target}")
    glossary_part = f"\nUse this glossary strictly:\n" + "\n".join(glossary_lines) + "\n" if glossary_lines else "\n"
    return (
        f"Translate the following text from {request.source_lang} to {request.target_lang}.\n"
        f"Provide ONLY the translation, without any explanations or notes."
        f"{glossary_part}"
        f"TEXT: {request.text}\n\nTRANSLATION:"
    )


def _extract_message_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, list):
        parts = [str(item.get("text", "")) for item in content if isinstance(item, dict)]
        return "".join(parts).strip()
    return str(content).strip()


def _normalize_error_payload(raw_detail: str) -> str:
    detail = str(raw_detail or "")
    try:
        payload = json.loads(detail)
    except Exception:
        return detail

    error = payload.get("error")
    if isinstance(error, dict):
        values = [error.get("message"), error.get("type"), error.get("code")]
        return " ".join(str(value) for value in values if value)
    if isinstance(error, str):
        return error
    if payload.get("message"):
        return str(payload.get("message"))
    return detail


def _is_local_base_url(base_url: str) -> bool:
    parsed = urllib.parse.urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _sanitize_error_detail(detail: str, api_key: str = "") -> str:
    sanitized = str(detail or "")
    if api_key:
        sanitized = sanitized.replace(api_key, "[REDACTED_API_KEY]")
    sanitized = re.sub(r"Bearer\s+[^\s,;]+", "Bearer [REDACTED_API_KEY]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"AIza[0-9A-Za-z\-_]{8,}", "[REDACTED_API_KEY]", sanitized)
    return sanitized[:500]


def _rotate_list(values, offset: int):
    if not values:
        return []
    index = max(0, int(offset or 0)) % len(values)
    return list(values[index:]) + list(values[:index])
