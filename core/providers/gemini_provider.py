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
        service = get_ai_service()
        started = time.time()
        model_name = (candidate.model if candidate else "") or self.default_model
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
            return TranslationResult(
                status="error",
                provider=self.name,
                model=runtime_model,
                error_type=classify_error(message),
                error_message=message,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            return TranslationResult(
                status="error",
                provider=self.name,
                model=model_name or self.default_model,
                error_type=classify_error(exc),
                error_message=str(exc),
                latency_ms=round((time.time() - started) * 1000),
            )
