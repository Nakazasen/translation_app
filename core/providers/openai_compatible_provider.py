"""OpenAI-compatible translation provider wrapper."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from translation_app.core.provider_router import TranslationRequest, TranslationResult, classify_error
from translation_app.core.providers.base import BaseTranslationProvider


class OpenAICompatibleProvider(BaseTranslationProvider):
    supports_glossary = True
    supports_ai_prompt = True

    def __init__(
        self,
        *,
        enabled: bool = False,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        provider_name: str = "openai_compatible",
        timeout: int = 15,
        allow_no_key_local: bool = False,
    ):
        self.name = provider_name or "openai_compatible"
        self.default_model = model or ""
        self.enabled = bool(enabled)
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.timeout = max(1, int(timeout or 15))
        self.allow_no_key_local = bool(allow_no_key_local)

    def is_available(self) -> bool:
        if not self.enabled or not self.base_url or not self.default_model:
            return False
        if self.api_key:
            return True
        return self.allow_no_key_local and _is_local_base_url(self.base_url)

    def translate(self, request: TranslationRequest) -> TranslationResult:
        started = time.time()
        prompt = _build_prompt(request)
        payload = {
            "model": self.default_model,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
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
                model=self.default_model,
                latency_ms=round((time.time() - started) * 1000),
            )
        except urllib.error.HTTPError as exc:
            detail = _sanitize_error_detail(exc.read().decode("utf-8", errors="replace"), self.api_key)
            return TranslationResult(
                status="error",
                provider=self.name,
                model=self.default_model,
                error_type=classify_error(f"{exc.code} {detail}"),
                error_message=f"HTTP {exc.code}: {detail}",
                latency_ms=round((time.time() - started) * 1000),
            )
        except Exception as exc:
            detail = _sanitize_error_detail(str(exc), self.api_key)
            return TranslationResult(
                status="error",
                provider=self.name,
                model=self.default_model,
                error_type=classify_error(detail),
                error_message=detail,
                latency_ms=round((time.time() - started) * 1000),
            )


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
