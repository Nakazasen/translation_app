"""Base provider contract for translation providers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from translation_app.core.provider_router import TranslationRequest, TranslationResult


class BaseTranslationProvider(ABC):
    name = "base"
    supports_glossary = False
    supports_ai_prompt = False
    default_model = ""

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def translate(self, request: TranslationRequest) -> TranslationResult:
        raise NotImplementedError
