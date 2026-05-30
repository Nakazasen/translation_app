"""Provider profile defaults and config normalization for the translation router."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item for item in (_normalize_text(value) for value in values) if item]


def mask_key_suffix(raw: str) -> str:
    token = _normalize_text(raw)
    if not token:
        return ""
    if len(token) <= 4:
        return "***"
    return f"****{token[-4:]}"


@dataclass
class ProviderProfile:
    name: str
    display_name: str
    provider_type: str
    enabled: bool
    base_url: str = ""
    api_key_pool: list[str] = field(default_factory=list)
    model_pool: list[str] = field(default_factory=list)
    timeout: int = 15
    supports_glossary: bool = True
    allow_no_key_local: bool = False
    default_model: str = ""

    def normalized(self) -> "ProviderProfile":
        return ProviderProfile(
            name=_normalize_text(self.name).lower(),
            display_name=_normalize_text(self.display_name) or _normalize_text(self.name),
            provider_type=_normalize_text(self.provider_type).lower(),
            enabled=bool(self.enabled),
            base_url=_normalize_text(self.base_url),
            api_key_pool=_normalize_string_list(self.api_key_pool),
            model_pool=_normalize_string_list(self.model_pool),
            timeout=max(1, int(self.timeout or 15)),
            supports_glossary=bool(self.supports_glossary),
            allow_no_key_local=bool(self.allow_no_key_local),
            default_model=_normalize_text(self.default_model),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "type": self.provider_type,
            "enabled": self.enabled,
            "base_url": self.base_url,
            "api_keys": ["[REDACTED_API_KEY]" for _ in self.api_key_pool],
            "models": list(self.model_pool),
            "default_model": self.default_model or (self.model_pool[0] if self.model_pool else ""),
            "timeout": self.timeout,
            "supports_glossary": self.supports_glossary,
            "allow_no_key_local": self.allow_no_key_local,
        }


def get_default_provider_profiles() -> dict[str, dict[str, Any]]:
    return {
        "gemini": {
            "enabled": True,
            "type": "gemini",
            "display_name": "Gemini",
            "base_url": "",
            "api_keys": [],
            "models": [],
            "timeout": 15,
            "supports_glossary": True,
        },
        "chatanywhere": {
            "enabled": False,
            "type": "openai_compatible",
            "display_name": "ChatAnyWhere",
            "base_url": "https://api.chatanywhere.tech/v1",
            "api_keys": [],
            "models": [],
            "timeout": 15,
            "supports_glossary": True,
        },
        "deepseek": {
            "enabled": False,
            "type": "openai_compatible",
            "display_name": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "api_keys": [],
            "models": [],
            "timeout": 15,
            "supports_glossary": True,
        },
        "nvidia_nim": {
            "enabled": False,
            "type": "openai_compatible",
            "display_name": "NVIDIA NIM",
            "base_url": "https://integrate.api.nvidia.com/v1",
            "api_keys": [],
            "models": [],
            "timeout": 15,
            "supports_glossary": True,
        },
        "openai_compatible": {
            "enabled": False,
            "type": "openai_compatible",
            "display_name": "OpenAI-Compatible",
            "base_url": "",
            "api_keys": [],
            "models": [],
            "timeout": 15,
            "supports_glossary": True,
            "allow_no_key_local": False,
        },
        "groq": {
            "enabled": False,
            "type": "openai_compatible",
            "display_name": "Groq",
            "base_url": "https://api.groq.com/openai/v1",
            "api_keys": [],
            "models": ["llama3-8b-8192", "mixtral-8x7b-32768", "gemma2-9b-it"],
            "timeout": 15,
            "supports_glossary": True,
        },
        "cerebras": {
            "enabled": False,
            "type": "openai_compatible",
            "display_name": "Cerebras",
            "base_url": "https://api.cerebras.ai/v1",
            "api_keys": [],
            "models": ["llama3.1-8b", "llama3.1-70b"],
            "timeout": 15,
            "supports_glossary": True,
        },
        "openrouter": {
            "enabled": False,
            "type": "openai_compatible",
            "display_name": "OpenRouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_keys": [],
            "models": ["meta-llama/llama-3.3-70b-instruct:free", "meta-llama/llama-3.2-3b-instruct:free"],
            "timeout": 15,
            "supports_glossary": True,
        },
        "mistral": {
            "enabled": False,
            "type": "openai_compatible",
            "display_name": "Mistral AI",
            "base_url": "https://api.mistral.ai/v1",
            "api_keys": [],
            "models": ["mistral-tiny", "mistral-small-latest"],
            "timeout": 15,
            "supports_glossary": True,
        },
        "sambanova": {
            "enabled": False,
            "type": "openai_compatible",
            "display_name": "SambaNova",
            "base_url": "https://api.sambanova.ai/v1",
            "api_keys": [],
            "models": ["meta-llama/Llama-3-8B-Instruct", "meta-llama/Llama-3-70B-Instruct"],
            "timeout": 15,
            "supports_glossary": True,
        },
        "cloudflare": {
            "enabled": False,
            "type": "cloudflare",
            "display_name": "Cloudflare Workers AI",
            "base_url": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run",
            "api_keys": [],
            "models": ["@cf/meta/llama-3-8b-instruct"],
            "timeout": 15,
            "supports_glossary": False,
        },
        "huggingface": {
            "enabled": False,
            "type": "huggingface",
            "display_name": "HuggingFace",
            "base_url": "https://api-inference.huggingface.co/models",
            "api_keys": [],
            "models": ["meta-llama/Meta-Llama-3-8B-Instruct"],
            "timeout": 15,
            "supports_glossary": False,
        },
        "github": {
            "enabled": False,
            "type": "openai_compatible",
            "display_name": "GitHub Models",
            "base_url": "https://models.inference.ai.azure.com",
            "api_keys": [],
            "models": ["meta-llama-3-8b-instruct", "gpt-4o-mini"],
            "timeout": 15,
            "supports_glossary": True,
        },
        "ai21": {
            "enabled": False,
            "type": "openai_compatible",
            "display_name": "AI21 Studio",
            "base_url": "https://api.ai21.com/studio/v1",
            "api_keys": [],
            "models": ["jamba-1.5-mini"],
            "timeout": 15,
            "supports_glossary": True,
        },
        "google": {
            "enabled": True,
            "type": "google_translate",
            "display_name": "Google Translate",
            "base_url": "",
            "api_keys": [],
            "models": ["google-translate"],
            "timeout": 15,
            "supports_glossary": False,
        },
    }


def build_provider_profiles(config_manager) -> dict[str, ProviderProfile]:
    configured = config_manager.providers_config
    profiles: dict[str, ProviderProfile] = {}
    catalog = {}
    if hasattr(config_manager, "get_provider_model_catalog_snapshot"):
        catalog = config_manager.get_provider_model_catalog_snapshot().get("providers", {})

    active_gemini_models = [
        str(model.get("model_id", "")).strip()
        for model in config_manager.waterfall_strategy
        if isinstance(model, dict) and model.get("is_active") and str(model.get("model_id", "")).strip()
    ]
    gemini_keys = list(config_manager.api_keys)
    if not gemini_keys and config_manager.api_key:
        gemini_keys = [config_manager.api_key]

    for provider_name, provider_data in configured.items():
        provider_type = _normalize_text(provider_data.get("type", provider_name)).lower()
        api_keys = _normalize_string_list(provider_data.get("api_keys"))
        models = _normalize_string_list(provider_data.get("models"))
        catalog_entry = catalog.get(provider_name, {}) if isinstance(catalog, dict) else {}
        catalog_models = []
        if isinstance(catalog_entry, dict):
            for item in catalog_entry.get("models", []):
                if isinstance(item, dict) and item.get("enabled", True):
                    model_id = _normalize_text(item.get("id"))
                    if model_id:
                        catalog_models.append(model_id)
            default_model = _normalize_text(catalog_entry.get("default_model"))
            if default_model and default_model in catalog_models:
                catalog_models = [default_model] + [item for item in catalog_models if item != default_model]
        else:
            default_model = ""
        base_url = _normalize_text(provider_data.get("base_url"))
        timeout = max(1, int(provider_data.get("timeout", 15) or 15))
        supports_glossary = provider_data.get("supports_glossary", provider_type != "google_translate")
        allow_no_key_local = bool(provider_data.get("allow_no_key_local", False))

        if provider_name == "gemini":
            if not api_keys:
                api_keys = gemini_keys
            if not models:
                models = list(active_gemini_models)
            if not default_model and models:
                default_model = models[0]
        elif catalog_models:
            models = list(catalog_models)
        elif models and not default_model:
            default_model = models[0]

        # Ensure default model is ALWAYS at the front of model pool for active execution
        if default_model:
            if default_model in models:
                models = [default_model] + [m for m in models if m != default_model]
            else:
                models = [default_model] + models

        profiles[provider_name] = ProviderProfile(
            name=provider_name,
            display_name=_normalize_text(provider_data.get("display_name", provider_name)) or provider_name,
            provider_type=provider_type,
            enabled=bool(provider_data.get("enabled", False)),
            base_url=base_url,
            api_key_pool=api_keys,
            model_pool=models,
            timeout=timeout,
            supports_glossary=bool(supports_glossary),
            allow_no_key_local=allow_no_key_local,
            default_model=default_model or (models[0] if models else ""),
        ).normalized()

    return profiles
