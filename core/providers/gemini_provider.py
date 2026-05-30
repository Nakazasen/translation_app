"""Gemini provider wrapper using the existing AI service."""

from __future__ import annotations

import time

from translation_app.core.ai_service import get_ai_service
from translation_app.core.provider_router import TranslationRequest, TranslationResult, classify_error
from translation_app.core.providers.base import BaseTranslationProvider, ProviderCandidate
from translation_app.core.providers.profiles import ProviderProfile


class GeminiProvider(BaseTranslationProvider):
    name = "gemini"
    display_name = "Gemini"
    supports_glossary = True
    supports_ai_prompt = True
    default_model = ""

    def __init__(
        self,
        *,
        profile: ProviderProfile | None = None,
        enabled: bool = True,
        default_model: str = "",
        models: list[str] | None = None,
        display_name: str = "",
    ):
        if profile is None:
            profile = ProviderProfile(
                name=self.name,
                display_name=display_name or self.display_name,
                provider_type="gemini",
                enabled=enabled,
                model_pool=list(models or ([default_model] if default_model else [])),
                default_model=default_model,
            ).normalized()

        self.profile = profile.normalized()
        self.name = self.profile.name or self.name
        self.display_name = self.profile.display_name or self.display_name
        self.enabled = self.profile.enabled
        self.model_pool = list(self.profile.model_pool)
        self.default_model = self.profile.default_model or (self.model_pool[0] if self.model_pool else "")

    def is_available(self) -> bool:
        return bool(self.enabled and self.model_pool and get_ai_service().is_available())

    def iter_candidates(self) -> list[ProviderCandidate]:
        if not self.is_available():
            return []
        return [ProviderCandidate(provider_name=self.name, model=model) for model in self.model_pool]

    def translate(self, request: TranslationRequest, candidate: ProviderCandidate | None = None) -> TranslationResult:
        import re
        started = time.time()
        model_name = (candidate.model if candidate else "") or self.default_model

        # Determine candidate API key to use
        api_key = None
        if self.profile.api_key_pool:
            key_index = candidate.key_index if (candidate and hasattr(candidate, 'key_index') and candidate.key_index is not None) else 0
            if 0 <= key_index < len(self.profile.api_key_pool):
                api_key = self.profile.api_key_pool[key_index]
            else:
                api_key = self.profile.api_key_pool[0]

        # Use temporary service to keep it completely isolated and thread-safe if a key is provided
        from translation_app.core.ai_service import get_ai_service, WaterfallGeminiService
        if api_key:
            service = WaterfallGeminiService(api_key=api_key)
        else:
            service = get_ai_service()

        def sanitize_api_keys(text: str) -> str:
            if not text:
                return ""
            # Redact Gemini keys
            text = re.sub(r"AIzaSy[A-Za-z0-9_-]+", "[REDACTED_API_KEY]", text)
            # Redact OpenAI/generic keys
            text = re.sub(r"sk-[A-Za-z0-9]+", "[REDACTED_API_KEY]", text)
            return text

        try:
            result = service.translate_with_glossary_terms(
                request.text,
                request.source_lang,
                request.target_lang,
                glossary_terms=request.glossary_terms,
                allow_google_fallback=False,
                preferred_models=[model_name] if model_name else None,
            )
            latency_ms = round((time.time() - started) * 1000)
            status = result.get("status", "error")
            runtime_model = result.get("model_used", model_name or self.default_model)
            if status == "success":
                return TranslationResult(
                    status="success",
                    text=result.get("text", ""),
                    provider=self.name,
                    model=runtime_model,
                    latency_ms=latency_ms,
                )

            message = result.get("error_message") or result.get("text") or "Gemini translation failed."

            # Unwrap the real underlying error from the waterfall wrapper text
            if "AI translation failed and Google fallback is disabled" in message:
                text_val = result.get("text", "")
                if "Last error:" in text_val:
                    message = text_val.split("Last error:", 1)[1].strip()

            message = sanitize_api_keys(message)

            return TranslationResult(
                status="error",
                provider=self.name,
                model=runtime_model,
                error_type=classify_error(message),
                error_message=message,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            message = sanitize_api_keys(str(exc))
            return TranslationResult(
                status="error",
                provider=self.name,
                model=model_name or self.default_model,
                error_type=classify_error(message),
                error_message=message,
                latency_ms=round((time.time() - started) * 1000),
            )
