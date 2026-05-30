"""Cloudflare Workers AI translation provider adapter."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from translation_app.core.provider_router import TranslationRequest, TranslationResult, classify_error
from translation_app.core.providers.base import BaseTranslationProvider, ProviderCandidate
from translation_app.core.providers.profiles import ProviderProfile, mask_key_suffix


class CloudflareProvider(BaseTranslationProvider):
    name = "cloudflare"
    display_name = "Cloudflare Workers AI"
    supports_glossary = False
    supports_ai_prompt = True
    default_model = "@cf/meta/llama-3-8b-instruct"

    def __init__(
        self,
        *,
        profile: ProviderProfile | None = None,
        enabled: bool = False,
        base_url: str = "",
        api_keys: list[str] | None = None,
        models: list[str] | None = None,
        timeout: int = 15,
        display_name: str = "",
    ):
        if profile is None:
            profile = ProviderProfile(
                name=self.name,
                display_name=display_name or self.display_name,
                provider_type="cloudflare",
                enabled=enabled,
                base_url=base_url or "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run",
                api_key_pool=list(api_keys or []),
                model_pool=list(models or [self.default_model]),
                timeout=timeout,
                supports_glossary=False,
            ).normalized()

        self.profile = profile.normalized()
        self.name = self.profile.name or self.name
        self.display_name = self.profile.display_name or self.display_name
        self.enabled = self.profile.enabled
        self.base_url = self.profile.base_url.rstrip("/")
        self.api_key_pool = list(self.profile.api_key_pool)
        self.model_pool = list(self.profile.model_pool)
        self.timeout = self.profile.timeout
        self._next_key_index = 0
        self._next_model_index = 0

    def is_available(self) -> bool:
        return bool(self.enabled and self.model_pool and self.api_key_pool)

    def iter_candidates(self) -> list[ProviderCandidate]:
        if not self.is_available():
            return []

        models = list(self.model_pool)
        # Shift models based on rotation index
        if self._next_model_index > 0 and len(models) > 0:
            offset = self._next_model_index % len(models)
            models = models[offset:] + models[:offset]

        key_entries = list(enumerate(self.api_key_pool))
        if self._next_key_index > 0 and len(key_entries) > 0:
            offset = self._next_key_index % len(key_entries)
            key_entries = key_entries[offset:] + key_entries[:offset]

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

        model_name = candidate.model or self.default_model
        api_token = ""
        account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")

        # If we have multiple keys in pool, check if index 0 is account_id and 1 is api_token
        keys = self.api_key_pool
        if len(keys) >= 2:
            account_id = keys[0]
            api_token = keys[1]
        elif len(keys) == 1:
            api_token = keys[0]

        # Build endpoint URL
        endpoint_base = self.base_url
        if "{account_id}" in endpoint_base:
            if account_id:
                endpoint_base = endpoint_base.replace("{account_id}", account_id)
            else:
                # Try to search environment or default
                endpoint_base = endpoint_base.replace("{account_id}", "placeholder")

        endpoint = f"{endpoint_base.rstrip('/')}/{model_name}"

        # Build prompt
        glossary_lines = []
        for term in request.glossary_terms:
            source = str(term.get("source_term", "")).replace("\r", " ").replace("\n", " ").strip()
            target = str(term.get("target_term", "")).replace("\r", " ").replace("\n", " ").strip()
            if source and target:
                glossary_lines.append(f"{source} => {target}")
        glossary_part = f"\nUse this glossary strictly:\n" + "\n".join(glossary_lines) + "\n" if glossary_lines else "\n"
        prompt = (
            f"Translate the following text from {request.source_lang} to {request.target_lang}.\n"
            f"Provide ONLY the translation, without any explanations or notes."
            f"{glossary_part}"
            f"TEXT: {request.text}\n\nTRANSLATION:"
        )

        payload = {
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        headers = {
            "Content-Type": "application/json",
        }
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        try:
            raw_body = json.dumps(payload).encode("utf-8")
            http_request = urllib.request.Request(endpoint, data=raw_body, headers=headers, method="POST")
            with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                raw_response = response.read().decode("utf-8")

            data = json.loads(raw_response)
            if not data.get("success", False):
                errors = data.get("errors", [])
                err_msg = errors[0].get("message", "Cloudflare API Error") if errors else "Cloudflare API Error"
                raise RuntimeError(err_msg)

            text = data.get("result", {}).get("response", "").strip()
            return TranslationResult(
                status="success",
                text=text,
                provider=self.name,
                model=model_name,
                key_id=candidate.key_id,
                key_index=candidate.key_index,
                latency_ms=round((time.time() - started) * 1000),
            )
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass

            # Clean error
            sanitized = _sanitize_error_detail(body or str(exc), api_token)
            return TranslationResult(
                status="error",
                provider=self.name,
                model=model_name,
                key_id=candidate.key_id,
                key_index=candidate.key_index,
                error_type=classify_error(exc, status_code=status_code, response_body=body),
                error_message=f"HTTP {status_code}: {sanitized}",
                latency_ms=round((time.time() - started) * 1000),
            )
        except Exception as exc:
            sanitized = _sanitize_error_detail(str(exc), api_token)
            return TranslationResult(
                status="error",
                provider=self.name,
                model=model_name,
                key_id=candidate.key_id,
                key_index=candidate.key_index,
                error_type=classify_error(exc),
                error_message=sanitized,
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


def _sanitize_error_detail(detail: str, api_key: str = "") -> str:
    sanitized = str(detail or "")
    if api_key:
        sanitized = sanitized.replace(api_key, "[REDACTED_API_KEY]")
    sanitized = re.sub(
        r"Authorization\s*:\s*Bearer\s+[^\s,;]+",
        "Authorization: [REDACTED_API_KEY]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"Bearer\s+[^\s,;]+", "Bearer [REDACTED_API_KEY]", sanitized, flags=re.IGNORECASE)
    return sanitized[:300]
