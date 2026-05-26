"""Base provider contract for translation providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from translation_app.core.provider_router import TranslationRequest, TranslationResult


@dataclass(frozen=True)
class ProviderCandidate:
    provider_name: str
    model: str = ""
    key_index: int = -1
    key_id: str = ""


class BaseTranslationProvider(ABC):
    name = "base"
    display_name = "Base"
    supports_glossary = False
    supports_ai_prompt = False
    default_model = ""

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def translate(self, request: TranslationRequest, candidate: ProviderCandidate | None = None) -> TranslationResult:
        raise NotImplementedError

    def iter_candidates(self) -> list[ProviderCandidate]:
        return [ProviderCandidate(provider_name=self.name, model=self.default_model)]

    def mark_success(self, candidate: ProviderCandidate) -> None:
        return None

    def mark_failure(self, candidate: ProviderCandidate, error_type: str) -> None:
        return None
