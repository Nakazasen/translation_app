"""Provider adapters for the translation router."""

from translation_app.core.providers.base import BaseTranslationProvider
from translation_app.core.providers.profiles import ProviderProfile, build_provider_profiles, get_default_provider_profiles

__all__ = [
    "BaseTranslationProvider",
    "GeminiProvider",
    "GoogleTranslateProvider",
    "OpenAICompatibleProvider",
    "ProviderProfile",
    "build_provider_profiles",
    "get_default_provider_profiles",
]


def __getattr__(name):
    if name == "GeminiProvider":
        from translation_app.core.providers.gemini_provider import GeminiProvider

        return GeminiProvider
    if name == "GoogleTranslateProvider":
        from translation_app.core.providers.google_provider import GoogleTranslateProvider

        return GoogleTranslateProvider
    if name == "OpenAICompatibleProvider":
        from translation_app.core.providers.openai_compatible_provider import OpenAICompatibleProvider

        return OpenAICompatibleProvider
    raise AttributeError(name)
