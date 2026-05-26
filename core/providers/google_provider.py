"""Google Translate provider wrapper."""

from __future__ import annotations

import time

from deep_translator import GoogleTranslator

from translation_app.config import config
from translation_app.core.provider_router import TranslationRequest, TranslationResult, classify_error
from translation_app.core.providers.base import BaseTranslationProvider, ProviderCandidate


class GoogleTranslateProvider(BaseTranslationProvider):
    name = "google"
    display_name = "Google Translate"
    supports_glossary = False
    supports_ai_prompt = False
    default_model = "google-translate"

    def is_available(self) -> bool:
        return True

    def translate(self, request: TranslationRequest, candidate: ProviderCandidate | None = None) -> TranslationResult:
        started = time.time()
        try:
            source_lang = "auto" if request.source_lang.lower() == "auto" else config.normalize_language_code(request.source_lang)
            target_lang = config.normalize_language_code(request.target_lang)
            translator = GoogleTranslator(source=source_lang, target=target_lang)
            translated_text = _translate_in_chunks(translator, request.text)
            return TranslationResult(
                status="success",
                text=translated_text,
                provider=self.name,
                model=self.default_model,
                latency_ms=round((time.time() - started) * 1000),
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


def _translate_in_chunks(translator: GoogleTranslator, text: str) -> str:
    max_length = config.max_text_length
    chunks = [text[index:index + max_length] for index in range(0, len(text), max_length)]
    translated_chunks: list[str] = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        if len(chunk) <= 5000:
            translated_chunks.append(translator.translate(chunk))
            continue
        for sub_chunk in [chunk[index:index + 4000] for index in range(0, len(chunk), 4000)]:
            if sub_chunk.strip():
                translated_chunks.append(translator.translate(sub_chunk))
    return "".join(translated_chunks)
