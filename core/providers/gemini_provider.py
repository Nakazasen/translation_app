"""Gemini provider wrapper using the existing AI service."""

from __future__ import annotations

import time

from translation_app.core.ai_service import get_ai_service
from translation_app.core.provider_router import TranslationRequest, TranslationResult, classify_error
from translation_app.core.providers.base import BaseTranslationProvider, ProviderCandidate


class GeminiProvider(BaseTranslationProvider):
    name = "gemini"
    display_name = "Gemini"
    supports_glossary = True
    supports_ai_prompt = True
    default_model = "gemini"

    def is_available(self) -> bool:
        return get_ai_service().is_available()

    def translate(self, request: TranslationRequest, candidate: ProviderCandidate | None = None) -> TranslationResult:
        service = get_ai_service()
        started = time.time()
        try:
            result = service.translate_with_glossary_terms(
                request.text,
                request.source_lang,
                request.target_lang,
                glossary_terms=request.glossary_terms,
                allow_google_fallback=False,
            )
            latency_ms = round((time.time() - started) * 1000)
            status = result.get("status", "error")
            if status == "success":
                return TranslationResult(
                    status="success",
                    text=result.get("text", ""),
                    provider=self.name,
                    model=result.get("model_used", self.default_model),
                    latency_ms=latency_ms,
                )
            message = result.get("error_message") or result.get("text") or "Gemini translation failed."
            return TranslationResult(
                status="error",
                provider=self.name,
                model=result.get("model_used", self.default_model),
                error_type=classify_error(message),
                error_message=message,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            return TranslationResult(
                status="error",
                provider=self.name,
                model=self.default_model,
                error_type=classify_error(exc),
                error_message=str(exc),
                latency_ms=round((time.time() - started) * 1000),
            )
