"""
AI Service - Dynamic Configuration with Waterfall Fallback + API Key Rotation
===============================================================================
Port from leetcode_mastery for Translation App.
Reads model configuration from external JSON file.
Supports runtime changes without recompiling.

Features:
- Waterfall fallback strategy: try multiple models in order
- API Key rotation: cycle through multiple keys on quota errors
- Dynamic config: read models from JSON file

Config file: Stored in user's AppData folder for persistence across updates.
"""

import os
import sys
import json
import re
import time
import logging
import concurrent.futures
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

from translation_app.core.providers.profiles import get_default_provider_profiles

logger = logging.getLogger(__name__)

def get_config_path() -> Path:
    """Get the correct config path, works for both dev and frozen .exe."""
    # For frozen executable, use AppData folder for persistence
    if getattr(sys, 'frozen', False):
        # Running as compiled .exe
        app_data = os.getenv('APPDATA', os.path.expanduser('~'))
        config_dir = Path(app_data) / 'DichTuDong' / 'config'
    else:
        # Running in development mode
        config_dir = Path(__file__).parent.parent / "data"
    
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "ai_settings.json"

# Default config path for Translation App
DEFAULT_CONFIG_PATH = get_config_path()

# =============================================================================
# MODEL ALLOWLIST & CATEGORIZATION
# =============================================================================
LIVE_TEXT_TRANSLATION_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
    "gemma-4-31b-it",
    "gemma-4-26b-a4b-it"
]

VISION_MODELS = [
    "gemini-2.5-flash",
    "gemini-3-flash-preview"
]

DEFAULT_MODELS = [
    {"model_id": "gemini-3.5-flash", "is_active": True, "timeout": 10},
    {"model_id": "gemini-3.1-flash-lite", "is_active": True, "timeout": 10},
    {"model_id": "gemini-2.5-flash", "is_active": True, "timeout": 12},
    {"model_id": "gemini-2.5-flash-lite", "is_active": True, "timeout": 7},
    {"model_id": "gemini-3-flash-preview", "is_active": True, "timeout": 10},
    {"model_id": "gemma-4-31b-it", "is_active": True, "timeout": 15},
    {"model_id": "gemma-4-26b-a4b-it", "is_active": True, "timeout": 15},
]

DEFAULT_PROVIDER_MODEL_CATALOG_VERSION = 1
PROVIDER_MODEL_REFRESH_STATUSES = {"never", "success", "error"}


def _blank_provider_model_refresh_entry() -> dict[str, Any]:
    return {
        "last_refreshed_at": None,
        "last_status": "never",
        "last_error": "",
        "last_count": 0,
    }


def get_default_provider_model_refresh_state() -> dict[str, dict[str, Any]]:
    return {
        provider_name: _blank_provider_model_refresh_entry()
        for provider_name in get_default_provider_profiles().keys()
    }


def _gemini_catalog_seed() -> list[dict[str, Any]]:
    vision_set = set(VISION_MODELS)
    return [
        {
            "id": entry["model_id"],
            "label": entry["model_id"],
            "enabled": bool(entry.get("is_active", True)),
            "source": "default",
            "capabilities": {
                "text": True,
                "vision": entry["model_id"] in vision_set,
            },
        }
        for entry in DEFAULT_MODELS
    ]


def get_default_provider_model_catalog() -> dict[str, Any]:
    return {
        "version": DEFAULT_PROVIDER_MODEL_CATALOG_VERSION,
        "providers": {
            "gemini": {
                "default_model": "gemini-3.5-flash",
                "models": _gemini_catalog_seed(),
            },
            "groq": {
                "default_model": "llama3-8b-8192",
                "models": [
                    {"id": "llama3-8b-8192", "label": "Llama 3 8B (Groq)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                    {"id": "mixtral-8x7b-32768", "label": "Mixtral 8x7B (Groq)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                    {"id": "gemma2-9b-it", "label": "Gemma 2 9B (Groq)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                ],
            },
            "cerebras": {
                "default_model": "llama3.1-8b",
                "models": [
                    {"id": "llama3.1-8b", "label": "Llama 3.1 8B (Cerebras)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                    {"id": "llama3.1-70b", "label": "Llama 3.1 70B (Cerebras)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                ],
            },
            "openrouter": {
                "default_model": "meta-llama/llama-3.3-70b-instruct:free",
                "models": [
                    {"id": "meta-llama/llama-3.3-70b-instruct:free", "label": "Llama 3.3 70B Free (OpenRouter)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                    {"id": "meta-llama/llama-3.2-3b-instruct:free", "label": "Llama 3.2 3B Free (OpenRouter)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                ],
            },
            "mistral": {
                "default_model": "mistral-tiny",
                "models": [
                    {"id": "mistral-tiny", "label": "Mistral Tiny (Mistral)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                    {"id": "mistral-small-latest", "label": "Mistral Small (Mistral)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                ],
            },
            "sambanova": {
                "default_model": "meta-llama/Llama-3-8B-Instruct",
                "models": [
                    {"id": "meta-llama/Llama-3-8B-Instruct", "label": "Llama 3 8B (SambaNova)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                    {"id": "meta-llama/Llama-3-70B-Instruct", "label": "Llama 3 70B (SambaNova)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                ],
            },
            "cloudflare": {
                "default_model": "@cf/meta/llama-3-8b-instruct",
                "models": [
                    {"id": "@cf/meta/llama-3-8b-instruct", "label": "Llama 3 8B (Cloudflare)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                ],
            },
            "huggingface": {
                "default_model": "meta-llama/Meta-Llama-3-8B-Instruct",
                "models": [
                    {"id": "meta-llama/Meta-Llama-3-8B-Instruct", "label": "Llama 3 8B (HuggingFace)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                ],
            },
            "github": {
                "default_model": "meta-llama-3-8b-instruct",
                "models": [
                    {"id": "meta-llama-3-8b-instruct", "label": "Llama 3 8B (GitHub)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                    {"id": "gpt-4o-mini", "label": "GPT-4o Mini (GitHub)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                ],
            },
            "ai21": {
                "default_model": "jamba-1.5-mini",
                "models": [
                    {"id": "jamba-1.5-mini", "label": "Jamba 1.5 Mini (AI21)", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                ],
            },
            "chatanywhere": {
                "default_model": "gpt-4o-mini",
                "models": [
                    {"id": "gpt-4o-mini", "label": "gpt-4o-mini", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                    {"id": "gpt-4o", "label": "gpt-4o", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                    {"id": "gpt-3.5-turbo", "label": "gpt-3.5-turbo", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                ],
            },
            "deepseek": {
                "default_model": "deepseek-v4-flash",
                "models": [
                    {"id": "deepseek-v4-flash", "label": "deepseek-v4-flash", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                    {"id": "deepseek-v4-pro", "label": "deepseek-v4-pro", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                ],
            },
            "nvidia_nim": {
                "default_model": "meta/llama-3.1-405b-instruct",
                "models": [
                    {"id": "meta/llama-3.1-405b-instruct", "label": "meta/llama-3.1-405b-instruct", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                    {"id": "meta/llama-3.1-70b-instruct", "label": "meta/llama-3.1-70b-instruct", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                    {"id": "meta/llama-3.1-8b-instruct", "label": "meta/llama-3.1-8b-instruct", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                    {"id": "nvidia/llama-3.1-nemotron-70b-instruct", "label": "nvidia/llama-3.1-nemotron-70b-instruct", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                ],
            },
            "openai_compatible": {
                "default_model": "",
                "models": [],
            },
            "google": {
                "default_model": "google-translate",
                "models": [
                    {"id": "google-translate", "label": "Google Translate", "enabled": True, "source": "default", "capabilities": {"text": True, "vision": False}},
                ],
            },
        },
    }


def _normalize_catalog_capabilities(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {"text": True, "vision": False, "embedding": False, "rerank": False, "unknown": False}
    return {
        "text": bool(value.get("text", True)),
        "vision": bool(value.get("vision", False)),
        "embedding": bool(value.get("embedding", False)),
        "rerank": bool(value.get("rerank", False)),
        "unknown": bool(value.get("unknown", False)),
    }


def _normalize_model_catalog_entry(value: Any, default_source: str = "user") -> dict[str, Any] | None:
    if isinstance(value, str):
        model_id = value.strip()
        if not model_id:
            return None
        return {
            "id": model_id,
            "label": model_id,
            "enabled": True,
            "source": "seed" if default_source in ("default", "seed") else default_source,
            "visibility": "unverified",
            "capabilities": {"text": True, "vision": False, "embedding": False, "rerank": False, "unknown": False},
            "discovered_at": None,
            "last_validated_at": None,
            "provider": None,
            "display_name": model_id,
            "raw_metadata": None,
        }

    if not isinstance(value, dict):
        return None

    model_id = str(value.get("id") or value.get("model_id") or "").strip()
    if not model_id:
        return None

    label = str(value.get("label") or value.get("display_name") or model_id).strip() or model_id
    source = str(value.get("source") or default_source).strip() or default_source
    if source in ("default", "seed"):
        source = "seed"

    visibility = str(value.get("visibility") or "unverified").strip()

    return {
        "id": model_id,
        "label": label,
        "enabled": bool(value.get("enabled", True)),
        "source": source,
        "visibility": visibility,
        "capabilities": _normalize_catalog_capabilities(value.get("capabilities")),
        "discovered_at": value.get("discovered_at"),
        "last_validated_at": value.get("last_validated_at"),
        "provider": value.get("provider"),
        "display_name": str(value.get("display_name") or label).strip() or label,
        "raw_metadata": value.get("raw_metadata"),
    }


def _merge_model_catalog_lists(base: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for entry in base + incoming:
        normalized = _normalize_model_catalog_entry(entry)
        if normalized is None:
            continue
        model_id = normalized["id"]
        if model_id not in order:
            order.append(model_id)
            merged[model_id] = normalized
            continue

        current = merged[model_id]
        incoming_label = normalized.get("label") or ""
        if (not current.get("label")) or current.get("label") == current["id"]:
            current["label"] = incoming_label or current["label"]
        elif incoming_label and incoming_label != model_id:
            current["label"] = incoming_label

        current["enabled"] = bool(normalized.get("enabled", current["enabled"]))

        # Merge source based on priority: user > api_discovered > docs_known > seed / legacy
        src_priority = {"user": 4, "api_discovered": 3, "docs_known": 2, "seed": 1, "legacy": 1}
        curr_src = current.get("source", "seed")
        in_src = normalized.get("source", "seed")
        if src_priority.get(in_src, 0) >= src_priority.get(curr_src, 0):
            current["source"] = in_src

        # Merge visibility: live_validated > current_key_visible > unverified > unavailable
        vis_priority = {"live_validated": 4, "current_key_visible": 3, "unverified": 2, "unavailable": 1}
        curr_vis = current.get("visibility", "unverified")
        in_vis = normalized.get("visibility", "unverified")
        if vis_priority.get(in_vis, 0) >= vis_priority.get(curr_vis, 0):
            current["visibility"] = in_vis

        # Merge capabilities
        curr_caps = current.get("capabilities") or {}
        in_caps = normalized.get("capabilities") or {}
        current["capabilities"] = {
            "text": bool(curr_caps.get("text", True) or in_caps.get("text", True)),
            "vision": bool(curr_caps.get("vision", False) or in_caps.get("vision", False)),
            "embedding": bool(curr_caps.get("embedding", False) or in_caps.get("embedding", False)),
            "rerank": bool(curr_caps.get("rerank", False) or in_caps.get("rerank", False)),
            "unknown": bool(curr_caps.get("unknown", False) or in_caps.get("unknown", False)),
        }

        # Keep timestamps if available
        if normalized.get("discovered_at"):
            current["discovered_at"] = normalized["discovered_at"]
        if normalized.get("last_validated_at"):
            current["last_validated_at"] = normalized["last_validated_at"]

        # Keep other fields
        if normalized.get("provider"):
            current["provider"] = normalized["provider"]
        if normalized.get("display_name"):
            current["display_name"] = normalized["display_name"]
        if normalized.get("raw_metadata"):
            current["raw_metadata"] = normalized["raw_metadata"]

    return [merged[model_id] for model_id in order]


def _sanitize_catalog_error_detail(detail: str, api_key: str = "") -> str:
    sanitized = str(detail or "")
    if api_key:
        sanitized = sanitized.replace(api_key, "[REDACTED_API_KEY]")
    sanitized = re.sub(
        r"Authorization\s*:\s*Bearer\s+[^\s,;]+",
        "Authorization: [REDACTED_API_KEY]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"AIza[0-9A-Za-z\-_]{8,}", "[REDACTED_API_KEY]", sanitized)
    sanitized = sanitized.replace("\r", " ").replace("\n", " ")
    return sanitized[:400]

def validate_model_for_profile(model_id: str, profile: str) -> bool:
    """
    Validate if a model is suitable for a given profile.
    Profiles: 'text' (general text translation), 'vision' (multimodal OCR/translation)
    """
    model_lower = model_id.lower()
    
    # Exclude multimedia, generation, audio, robotics and computer use models
    invalid_keywords = ["imagen", "veo", "tts", "native-audio", "audio", "robotics", "computer-use"]
    if any(kw in model_lower for kw in invalid_keywords):
        return False
        
    if profile == "text":
        return model_id in LIVE_TEXT_TRANSLATION_MODELS
    elif profile == "vision":
        # Dynamic check for other providers (Nvidia Nim, ChatAnywhere, DeepSeek, etc.)
        vision_keywords = ["vision", "vl", "multimodal", "gui"]
        if any(kw in model_lower for kw in vision_keywords):
            # Exclude gemini pro models from dynamic vision since they fail/timeout
            if "gemini" in model_lower and "pro" in model_lower:
                return False
            return True
            
        # Fallback to hardcoded list of verified default vision models
        return model_id in VISION_MODELS
        
    return True


class AIConfigManager:
    """
    Manages AI configuration from external JSON file.
    Allows runtime updates without code changes.
    Supports API Key rotation for high-availability.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config = None
        self._current_key_index = 0
        self.load_config()
    
    def _merge_with_defaults(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Merge loaded config with defaults so that missing fields are filled instead of resetting everything."""
        defaults = self._get_default_config()
        if not isinstance(config_data, dict):
            return defaults
            
        merged = deepcopy(defaults)
        
        # Merge top-level fields
        for key, default_val in defaults.items():
            if key in config_data:
                if key == "waterfall_strategy" and isinstance(config_data[key], list):
                    merged_strategy = []
                    
                    # Merge loaded models if they are valid live text models
                    for model in config_data[key]:
                        if isinstance(model, dict) and "model_id" in model:
                            model_id = model["model_id"]
                            if model_id in LIVE_TEXT_TRANSLATION_MODELS:
                                default_model = next((m for m in DEFAULT_MODELS if m["model_id"] == model_id), None)
                                default_timeout = default_model["timeout"] if default_model else 10
                                
                                m_copy = {
                                    "model_id": model_id,
                                    "is_active": model.get("is_active", True),
                                    "timeout": model.get("timeout", default_timeout)
                                }
                                merged_strategy.append(m_copy)
                            else:
                                logger.info(f"🚫 Migrated out invalid text translation model: {model_id}")
                                
                    # If some default live models are completely missing, append them
                    merged_model_ids = [m["model_id"] for m in merged_strategy]
                    for def_model in DEFAULT_MODELS:
                        if def_model["model_id"] not in merged_model_ids:
                            merged_strategy.append(def_model.copy())
                            
                    merged[key] = merged_strategy
                elif key == "providers" and isinstance(config_data[key], dict):
                    providers_merged = deepcopy(defaults["providers"])
                    for p_name, p_default in defaults["providers"].items():
                        p_configured = config_data[key].get(p_name)
                        if isinstance(p_configured, dict):
                            p_merged = deepcopy(p_default)
                            p_merged.update(p_configured)
                            providers_merged[p_name] = p_merged
                    merged[key] = providers_merged
                elif key == "provider_router" and isinstance(config_data[key], dict):
                    router_merged = deepcopy(defaults["provider_router"])
                    router_merged.update(config_data[key])
                    merged[key] = router_merged
                else:
                    merged[key] = config_data[key]

        merged["provider_model_catalog"] = self._normalize_provider_model_catalog(
            config_data.get("provider_model_catalog"),
            providers_value=config_data.get("providers"),
            legacy_openai=config_data.get("openai_compatible"),
            waterfall_strategy=config_data.get("waterfall_strategy"),
        )
                    
        return merged

    def load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file with backup support and corruption protection."""
        config_loaded = False
        loaded_data = None
        
        # Try loading main config
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                config_loaded = True
                logger.info(f"✅ Loaded AI config from: {self.config_path}")
        except Exception as e:
            logger.error(f"❌ Failed to load main config: {e}. Trying backup...")
            
        # Try loading backup config if main failed
        if not config_loaded:
            bak_path = self.config_path.with_suffix(self.config_path.suffix + '.bak')
            try:
                if bak_path.exists():
                    with open(bak_path, 'r', encoding='utf-8') as f:
                        loaded_data = json.load(f)
                    config_loaded = True
                    logger.info(f"✅ Loaded AI config from backup: {bak_path}")
            except Exception as e_bak:
                logger.error(f"❌ Failed to load backup config: {e_bak}")
                
        if config_loaded and loaded_data is not None:
            # Detect changes to the api_keys pool
            old_keys = self._config.get("api_keys", []) if self._config else []
            new_keys = loaded_data.get("api_keys", [])
            
            self._config = self._merge_with_defaults(loaded_data)
            
            # If api_keys changed, reset index. Otherwise, retain in-memory index.
            if old_keys != new_keys:
                self._current_key_index = self._config.get("current_key_index", 0)
        else:
            if self.config_path.exists() or self.config_path.with_suffix(self.config_path.suffix + '.bak').exists():
                # Both files are corrupted. Do NOT overwrite. Load default in RAM.
                logger.error("❌ Both main and backup configs are corrupted. Using defaults in-memory. DO NOT OVERWRITE.")
                if self._config is None:
                    self._config = self._get_default_config()
                    self._current_key_index = 0
            else:
                # First startup
                logger.warning(f"⚠️ Config not found, using defaults: {self.config_path}")
                self._config = self._get_default_config()
                self._current_key_index = 0
                self.save_config()  # Create default config file
                
        return self._config
    
    def save_config(self) -> bool:
        """Save current configuration to JSON file using atomic write."""
        temp_path = self.config_path.with_suffix(self.config_path.suffix + '.tmp')
        bak_path = self.config_path.with_suffix(self.config_path.suffix + '.bak')
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 1. Atomic write to temp file
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
                
            # 2. Backup existing config
            if self.config_path.exists():
                try:
                    os.replace(self.config_path, bak_path)
                except Exception as bak_err:
                    logger.warning(f"⚠️ Failed to backup config: {bak_err}")
            
            # 3. Rename temp to config
            os.replace(temp_path, self.config_path)
            logger.info(f"✅ Saved AI config to: {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to save config: {e}")
            if temp_path.exists():
                try:
                    os.remove(temp_path)
                except:
                    pass
            return False
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Return default configuration."""
        provider_router_defaults = {
            "enabled": False,
            "policy": "ai_waterfall",
            "max_retries": 2,
            "cooldown_seconds": 300,
            "provider_order": [
                "gemini",
                "groq",
                "cerebras",
                "openrouter",
                "mistral",
                "sambanova",
                "cloudflare",
                "huggingface",
                "github",
                "ai21",
                "chatanywhere",
                "deepseek",
                "nvidia_nim",
                "openai_compatible",
                "google",
            ],
        }
        provider_defaults = get_default_provider_profiles()
        return {
            "api_key": os.getenv("GEMINI_API_KEY", ""),
            "api_keys": [],
            "current_key_index": 0,
            "waterfall_strategy": DEFAULT_MODELS.copy(),
            "use_translation_memory": True,
            "translation_memory_policy": "tm_prefer_cache",
            "min_segment_length_to_cache": 2,
            "use_glossary": True,
            "max_glossary_terms_per_segment": 20,
            "glossary_enforcement_level": "prompt",
            "use_provider_router": False,
            "provider_router_policy": "ai_first",
            "provider_router_max_retries": 2,
            "provider_cooldown_seconds": 300,
            "provider_order": provider_router_defaults["provider_order"].copy(),
            "openai_compatible": {
                "enabled": False,
                "base_url": "",
                "api_key": "",
                "model": "",
                "provider_name": "openai_compatible",
                "timeout": 15,
                "allow_no_key_local": False,
            },
            "provider_router": deepcopy(provider_router_defaults),
            "providers": deepcopy(provider_defaults),
            "provider_model_catalog": get_default_provider_model_catalog(),
            "auto_refresh_provider_models": True,
            "provider_model_refresh_ttl_hours": 24,
            "provider_model_refresh_state": get_default_provider_model_refresh_state(),
        }

    @property
    def provider_router_config(self) -> Dict[str, Any]:
        defaults = self._get_default_config()["provider_router"]
        value = self._config.get("provider_router", {})
        merged = deepcopy(defaults)
        if isinstance(value, dict):
            merged.update(value)
        return merged

    @provider_router_config.setter
    def provider_router_config(self, value: Dict[str, Any]):
        defaults = self._get_default_config()["provider_router"]
        merged = deepcopy(defaults)
        if isinstance(value, dict):
            merged.update(value)
        self._config["provider_router"] = merged

    @property
    def providers_config(self) -> Dict[str, Any]:
        defaults = self._get_default_config()["providers"]
        value = self._config.get("providers", {})
        merged = deepcopy(defaults)
        if isinstance(value, dict):
            for provider_name, provider_defaults in defaults.items():
                provider_merged = deepcopy(provider_defaults)
                configured = value.get(provider_name, {})
                if isinstance(configured, dict):
                    provider_merged.update(configured)
                merged[provider_name] = provider_merged

        # Backward compatibility bridge for the single openai-compatible config block.
        legacy_openai = self._config.get("openai_compatible", {})
        if isinstance(legacy_openai, dict):
            if "enabled" in legacy_openai:
                merged["openai_compatible"]["enabled"] = bool(legacy_openai.get("enabled", merged["openai_compatible"]["enabled"]))
            legacy_base_url = str(legacy_openai.get("base_url", "") or "").strip()
            if legacy_base_url:
                merged["openai_compatible"]["base_url"] = legacy_base_url
            legacy_api_key = str(legacy_openai.get("api_key", "") or "").strip()
            if legacy_api_key:
                merged["openai_compatible"]["api_keys"] = [legacy_api_key]
            legacy_model = str(legacy_openai.get("model", "") or "").strip()
            if legacy_model:
                merged["openai_compatible"]["models"] = [legacy_model]
            if legacy_openai.get("timeout"):
                merged["openai_compatible"]["timeout"] = int(legacy_openai.get("timeout", merged["openai_compatible"]["timeout"]) or merged["openai_compatible"]["timeout"])
            if "allow_no_key_local" in legacy_openai:
                merged["openai_compatible"]["allow_no_key_local"] = bool(legacy_openai.get("allow_no_key_local", merged["openai_compatible"]["allow_no_key_local"]))

        return merged

    @providers_config.setter
    def providers_config(self, value: Dict[str, Any]):
        defaults = self._get_default_config()["providers"]
        merged = deepcopy(defaults)
        if isinstance(value, dict):
            for provider_name, provider_defaults in defaults.items():
                provider_merged = deepcopy(provider_defaults)
                configured = value.get(provider_name, {})
                if isinstance(configured, dict):
                    provider_merged.update(configured)
                merged[provider_name] = provider_merged
        self._config["providers"] = merged
        self._config["provider_model_catalog"] = self._normalize_provider_model_catalog(
            self._config.get("provider_model_catalog"),
            providers_value=merged,
            legacy_openai=self._config.get("openai_compatible"),
            waterfall_strategy=self._config.get("waterfall_strategy"),
        )

    def _normalize_provider_model_catalog(
        self,
        raw_catalog: Any,
        *,
        providers_value: Any | None = None,
        legacy_openai: Any | None = None,
        waterfall_strategy: Any | None = None,
    ) -> Dict[str, Any]:
        defaults = get_default_provider_model_catalog()
        providers = deepcopy(defaults["providers"])

        raw_providers = raw_catalog.get("providers", {}) if isinstance(raw_catalog, dict) else {}
        for provider_name, default_entry in defaults["providers"].items():
            configured = raw_providers.get(provider_name, {}) if isinstance(raw_providers, dict) else {}
            has_configured_provider = isinstance(configured, dict) and provider_name in raw_providers
            base_models = configured.get("models", []) if has_configured_provider else default_entry.get("models", [])

            # Auto-migrate deprecated OpenRouter free models to active free models
            if provider_name == "openrouter":
                deprecated_ids = {"google/gemini-2.5-flash:free", "meta-llama/llama-3-8b-instruct:free"}
                has_deprecated = any(isinstance(item, dict) and item.get("id") in deprecated_ids for item in base_models)
                if has_deprecated or not base_models:
                    base_models = [item for item in base_models if isinstance(item, dict) and item.get("id") not in deprecated_ids]
                    for default_m in default_entry.get("models", []):
                        if not any(isinstance(item, dict) and item.get("id") == default_m["id"] for item in base_models):
                            base_models.append(default_m)

            models = _merge_model_catalog_lists([], base_models)
            default_model = str(
                (configured.get("default_model", "") if has_configured_provider else default_entry.get("default_model", ""))
                or ""
            ).strip()

            if provider_name == "openrouter" and default_model in {"google/gemini-2.5-flash:free", "meta-llama/llama-3-8b-instruct:free"}:
                default_model = "meta-llama/llama-3.3-70b-instruct:free"
            if default_model and not any(item["id"] == default_model for item in models):
                models.append(
                    {
                        "id": default_model,
                        "label": default_model,
                        "enabled": True,
                        "source": "user",
                        "capabilities": {"text": True, "vision": False},
                    }
                )
            providers[provider_name] = {
                "default_model": default_model,
                "models": models,
            }

        provider_configs = providers_value if isinstance(providers_value, dict) else (self._config.get("providers", {}) if isinstance(self._config, dict) else {})
        if isinstance(provider_configs, dict):
            for provider_name, provider_cfg in provider_configs.items():
                if not isinstance(provider_cfg, dict) or provider_name not in providers:
                    continue
                if isinstance(raw_catalog, dict) and provider_name in raw_providers:
                    continue
                legacy_models = [
                    _normalize_model_catalog_entry(model_id, default_source="legacy")
                    for model_id in provider_cfg.get("models", [])
                ]
                legacy_models = [item for item in legacy_models if item is not None]
                providers[provider_name]["models"] = _merge_model_catalog_lists(
                    providers[provider_name]["models"],
                    legacy_models,
                )
                if not providers[provider_name]["default_model"] and legacy_models:
                    providers[provider_name]["default_model"] = legacy_models[0]["id"]

        if isinstance(legacy_openai, dict):
            legacy_model = str(legacy_openai.get("model", "") or "").strip()
            if legacy_model:
                providers["openai_compatible"]["models"] = _merge_model_catalog_lists(
                    providers["openai_compatible"]["models"],
                    [{"id": legacy_model, "label": legacy_model, "enabled": True, "source": "legacy", "capabilities": {"text": True, "vision": False}}],
                )
                if not providers["openai_compatible"]["default_model"]:
                    providers["openai_compatible"]["default_model"] = legacy_model

        strategy = waterfall_strategy if isinstance(waterfall_strategy, list) else (self._config.get("waterfall_strategy", []) if isinstance(self._config, dict) else [])
        gemini_models = []
        default_gemini = ""
        for entry in strategy:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("model_id", "")).strip()
            if not model_id:
                continue
            normalized = {
                "id": model_id,
                "label": model_id,
                "enabled": bool(entry.get("is_active", True)),
                "source": "default" if model_id in {item["model_id"] for item in DEFAULT_MODELS} else "user",
                "capabilities": {"text": True, "vision": model_id in VISION_MODELS},
            }
            gemini_models.append(normalized)
            if not default_gemini and normalized["enabled"]:
                default_gemini = model_id
        providers["gemini"]["models"] = _merge_model_catalog_lists(providers["gemini"]["models"], gemini_models)
        if default_gemini:
            providers["gemini"]["default_model"] = default_gemini

        for provider_name, entry in providers.items():
            if not entry["default_model"]:
                first_enabled = next((item["id"] for item in entry["models"] if item.get("enabled", True)), "")
                entry["default_model"] = first_enabled

        return {
            "version": DEFAULT_PROVIDER_MODEL_CATALOG_VERSION,
            "providers": providers,
        }

    @property
    def provider_model_catalog(self) -> Dict[str, Any]:
        return self._normalize_provider_model_catalog(self._config.get("provider_model_catalog"))

    @provider_model_catalog.setter
    def provider_model_catalog(self, value: Dict[str, Any]):
        self._config["provider_model_catalog"] = self._normalize_provider_model_catalog(
            value,
            providers_value=self._config.get("providers"),
            legacy_openai=self._config.get("openai_compatible"),
            waterfall_strategy=self._config.get("waterfall_strategy"),
        )

    @property
    def use_provider_router(self) -> bool:
        return bool(self.provider_router_config.get("enabled", self._config.get("use_provider_router", False)))

    @use_provider_router.setter
    def use_provider_router(self, value: bool):
        self._config["use_provider_router"] = bool(value)
        router_config = self.provider_router_config
        router_config["enabled"] = bool(value)
        self._config["provider_router"] = router_config

    @property
    def provider_router_policy(self) -> str:
        value = str(self.provider_router_config.get("policy", self._config.get("provider_router_policy", "ai_waterfall"))).strip().lower()
        return value or "ai_waterfall"

    @provider_router_policy.setter
    def provider_router_policy(self, value: str):
        normalized = str(value or "ai_waterfall").strip().lower()
        self._config["provider_router_policy"] = normalized or "ai_waterfall"
        router_config = self.provider_router_config
        router_config["policy"] = normalized or "ai_waterfall"
        self._config["provider_router"] = router_config

    @property
    def provider_router_max_retries(self) -> int:
        return max(0, int(self.provider_router_config.get("max_retries", self._config.get("provider_router_max_retries", 2))))

    @provider_router_max_retries.setter
    def provider_router_max_retries(self, value: int):
        self._config["provider_router_max_retries"] = max(0, int(value))
        router_config = self.provider_router_config
        router_config["max_retries"] = max(0, int(value))
        self._config["provider_router"] = router_config

    @property
    def provider_cooldown_seconds(self) -> int:
        return max(1, int(self.provider_router_config.get("cooldown_seconds", self._config.get("provider_cooldown_seconds", 300))))

    @provider_cooldown_seconds.setter
    def provider_cooldown_seconds(self, value: int):
        self._config["provider_cooldown_seconds"] = max(1, int(value))
        router_config = self.provider_router_config
        router_config["cooldown_seconds"] = max(1, int(value))
        self._config["provider_router"] = router_config

    @property
    def provider_order(self) -> List[str]:
        value = self.provider_router_config.get("provider_order", self._config.get("provider_order", []))
        if not isinstance(value, list):
            value = self._get_default_config()["provider_router"]["provider_order"].copy()

        current_list = [str(item).strip().lower() for item in value if str(item).strip()]

        # All 15 known providers in translation_app
        all_known = [
            "gemini", "groq", "cerebras", "openrouter", "mistral", "sambanova",
            "cloudflare", "huggingface", "github", "ai21", "chatanywhere",
            "deepseek", "nvidia_nim", "openai_compatible", "google"
        ]

        # Safely append any missing known providers to the end of the priority order list
        for p in all_known:
            if p not in current_list:
                current_list.append(p)

        return current_list

    @provider_order.setter
    def provider_order(self, value: List[str]):
        normalized = [str(item).strip().lower() for item in (value or []) if str(item).strip()]

        all_known = [
            "gemini", "groq", "cerebras", "openrouter", "mistral", "sambanova",
            "cloudflare", "huggingface", "github", "ai21", "chatanywhere",
            "deepseek", "nvidia_nim", "openai_compatible", "google"
        ]
        for p in all_known:
            if p not in normalized:
                normalized.append(p)

        self._config["provider_order"] = normalized
        router_config = self.provider_router_config
        router_config["provider_order"] = normalized
        self._config["provider_router"] = router_config

    @property
    def openai_compatible_config(self) -> Dict[str, Any]:
        defaults = self._get_default_config()["openai_compatible"]
        merged = deepcopy(defaults)
        merged.update(self._config.get("openai_compatible", {}))
        provider_cfg = self.providers_config.get("openai_compatible", {})
        merged["enabled"] = bool(provider_cfg.get("enabled", merged["enabled"]))
        merged["base_url"] = str(provider_cfg.get("base_url", merged["base_url"]) or "").strip()
        api_keys = provider_cfg.get("api_keys", [])
        merged["api_key"] = str(api_keys[0] if isinstance(api_keys, list) and api_keys else merged["api_key"] or "").strip()
        models = provider_cfg.get("models", [])
        merged["model"] = str(models[0] if isinstance(models, list) and models else merged["model"] or "").strip()
        merged["timeout"] = int(provider_cfg.get("timeout", merged["timeout"]) or merged["timeout"])
        merged["provider_name"] = "openai_compatible"
        merged["allow_no_key_local"] = bool(provider_cfg.get("allow_no_key_local", merged["allow_no_key_local"]))
        return merged

    @openai_compatible_config.setter
    def openai_compatible_config(self, value: Dict[str, Any]):
        defaults = self._get_default_config()["openai_compatible"]
        merged = deepcopy(defaults)
        if isinstance(value, dict):
            merged.update(value)
        self._config["openai_compatible"] = merged
        providers_config = self.providers_config
        provider_entry = deepcopy(providers_config.get("openai_compatible", {}))
        provider_entry["enabled"] = bool(merged.get("enabled", provider_entry.get("enabled", False)))
        provider_entry["base_url"] = str(merged.get("base_url", provider_entry.get("base_url", "")) or "").strip()
        provider_entry["api_keys"] = [str(merged.get("api_key", "") or "").strip()] if str(merged.get("api_key", "") or "").strip() else provider_entry.get("api_keys", [])
        provider_entry["models"] = [str(merged.get("model", "") or "").strip()] if str(merged.get("model", "") or "").strip() else provider_entry.get("models", [])
        provider_entry["timeout"] = int(merged.get("timeout", provider_entry.get("timeout", 15)) or 15)
        provider_entry["allow_no_key_local"] = bool(merged.get("allow_no_key_local", provider_entry.get("allow_no_key_local", False)))
        providers_config["openai_compatible"] = provider_entry
        self._config["providers"] = providers_config
    
    # =========================================================================
    # API KEY MANAGEMENT - with In-Memory Rotation
    # =========================================================================
    
    @property
    def api_key(self) -> str:
        """Get the current API key from config or environment.
        Priority: api_keys list > api_key > env variable
        """
        keys = self._config.get("api_keys", [])
        if keys and isinstance(keys, list) and len(keys) > 0:
            idx = self._current_key_index
            if idx >= len(keys) or idx < 0:
                idx = 0
                self._current_key_index = 0
            return keys[idx]
        
        key = self._config.get("api_key", "")
        return key if key else os.getenv("GEMINI_API_KEY", "")
    
    @api_key.setter
    def api_key(self, value: str):
        """Set API key in config."""
        self._config["api_key"] = value
    
    @property
    def api_keys(self) -> List[str]:
        """Get the full pool of API keys."""
        return self._config.get("api_keys", [])
    
    @api_keys.setter
    def api_keys(self, value: List[str]):
        """Set the pool of API keys."""
        self._config["api_keys"] = value
        self._current_key_index = 0
        self._config["current_key_index"] = 0
        if value:
            self._config["api_key"] = value[0]
            
    @property
    def use_translation_memory(self) -> bool:
        """Check if Translation Memory is enabled."""
        return self._config.get("use_translation_memory", True)
        
    @use_translation_memory.setter
    def use_translation_memory(self, value: bool):
        """Set Translation Memory enabled state."""
        self._config["use_translation_memory"] = value

    @property
    def translation_memory_policy(self) -> str:
        """Get the Translation Memory Quality Policy.
        Supported values:
        - tm_prefer_cache: Use TM hit, skip AI call
        - tm_suggest_only: Show suggestions, still call AI
        - tm_retranslate_and_update: Call AI, overwrite/update TM cache
        - tm_disabled: Disable TM entirely (fallback/equivalent to use_translation_memory = False)
        """
        value = str(self._config.get("translation_memory_policy", "tm_prefer_cache")).strip().lower()
        if value in {"tm_prefer_cache", "tm_suggest_only", "tm_retranslate_and_update", "tm_disabled"}:
            return value
        return "tm_prefer_cache"
        
    @translation_memory_policy.setter
    def translation_memory_policy(self, value: str):
        """Set the Translation Memory Quality Policy."""
        normalized = str(value).strip().lower()
        if normalized in {"tm_prefer_cache", "tm_suggest_only", "tm_retranslate_and_update", "tm_disabled"}:
            self._config["translation_memory_policy"] = normalized
        
    @property
    def min_segment_length_to_cache(self) -> int:
        """Get the minimum segment length to cache in TM."""
        return self._config.get("min_segment_length_to_cache", 2)
        
    @min_segment_length_to_cache.setter
    def min_segment_length_to_cache(self, value: int):
        """Set the minimum segment length to cache in TM."""
        self._config["min_segment_length_to_cache"] = value
        
    @property
    def use_glossary(self) -> bool:
        """Check if Glossary enforcement is enabled."""
        return self._config.get("use_glossary", True)
        
    @use_glossary.setter
    def use_glossary(self, value: bool):
        """Set Glossary enforcement enabled state."""
        self._config["use_glossary"] = value
        
    @property
    def max_glossary_terms_per_segment(self) -> int:
        """Get the maximum glossary terms per segment."""
        return self._config.get("max_glossary_terms_per_segment", 20)
        
    @max_glossary_terms_per_segment.setter
    def max_glossary_terms_per_segment(self, value: int):
        """Set the maximum glossary terms per segment."""
        self._config["max_glossary_terms_per_segment"] = value
        
    @property
    def glossary_enforcement_level(self) -> str:
        """
        Get the glossary enforcement level.

        Supported values:
        - off: glossary is ignored during translation prompt construction
        - prompt: sanitized glossary terms are injected into the prompt
        - validate: reserved for future QA validation, currently does not enforce anything at translation time
        """
        value = str(self._config.get("glossary_enforcement_level", "prompt")).strip().lower()
        if value in {"off", "prompt", "validate"}:
            return value
        return "prompt"
        
    @glossary_enforcement_level.setter
    def glossary_enforcement_level(self, value: str):
        """
        Set the glossary enforcement level.

        "validate" is accepted as reserved configuration for future QA validation,
        but it does not inject or enforce glossary terms during translation yet.
        """
        normalized = str(value).strip().lower()
        self._config["glossary_enforcement_level"] = (
            normalized if normalized in {"off", "prompt", "validate"} else "prompt"
        )


    
    def rotate_api_key(self) -> bool:
        """
        Cycle to the next API key in the pool.
        This updates our in-memory pointer without mutating the config or reordering keys on disk.
        """
        keys = self._config.get("api_keys", [])
        if not keys or not isinstance(keys, list) or len(keys) < 2:
            logger.warning("⚠️ Cannot rotate: Need at least 2 API keys")
            return False
            
        self._current_key_index = (self._current_key_index + 1) % len(keys)
        self._config["current_key_index"] = self._current_key_index
        logger.info(f"🔄 Rotated to next API key at index {self._current_key_index}")
        return True
    
    # =========================================================================
    # MODEL MANAGEMENT
    # =========================================================================
    
    @property
    def active_models(self) -> List[str]:
        """Get list of active model IDs in priority order."""
        strategy = self._config.get("waterfall_strategy", DEFAULT_MODELS)
        return [m["model_id"] for m in strategy if m.get("is_active", True)]
    
    @property
    def waterfall_strategy(self) -> List[Dict]:
        """Get full waterfall strategy configuration."""
        return self._config.get("waterfall_strategy", DEFAULT_MODELS)
    
    @waterfall_strategy.setter
    def waterfall_strategy(self, value: List[Dict]):
        """Set waterfall strategy configuration."""
        self._config["waterfall_strategy"] = value
    
    def add_model(self, model_id: str, is_active: bool = True, timeout: int = 10) -> bool:
        """Add a new model to the strategy."""
        # Check for duplicates
        for m in self._config["waterfall_strategy"]:
            if m["model_id"] == model_id:
                logger.warning(f"⚠️ Model already exists: {model_id}")
                return False
        
        self._config["waterfall_strategy"].append({
            "model_id": model_id,
            "is_active": is_active,
            "timeout": timeout
        })
        return True
    
    def remove_model(self, model_id: str) -> bool:
        """Remove a model from the strategy."""
        original_len = len(self._config["waterfall_strategy"])
        self._config["waterfall_strategy"] = [
            m for m in self._config["waterfall_strategy"] 
            if m["model_id"] != model_id
        ]
        return len(self._config["waterfall_strategy"]) < original_len
    
    def move_model(self, model_id: str, direction: int) -> bool:
        """Move model up (-1) or down (+1) in priority."""
        strategy = self._config["waterfall_strategy"]
        for i, m in enumerate(strategy):
            if m["model_id"] == model_id:
                new_idx = i + direction
                if 0 <= new_idx < len(strategy):
                    strategy[i], strategy[new_idx] = strategy[new_idx], strategy[i]
                    return True
                return False
        return False
    
    def toggle_model(self, model_id: str) -> bool:
        """Toggle active state of a model."""
        for m in self._config["waterfall_strategy"]:
            if m["model_id"] == model_id:
                m["is_active"] = not m.get("is_active", True)
                return True
        return False

    def get_provider_profiles_public(self) -> Dict[str, Dict[str, Any]]:
        """Get public view of provider profiles for UI display without exposing raw keys."""
        from translation_app.core.providers.profiles import build_provider_profiles
        profiles = build_provider_profiles(self)
        return {name: profile.to_public_dict() for name, profile in profiles.items()}

    def get_provider_model_catalog_snapshot(self) -> Dict[str, Any]:
        """Return normalized provider model catalog for internal callers."""
        return deepcopy(self.provider_model_catalog)

    def get_provider_model_catalog_public(self) -> Dict[str, Any]:
        """Return a public provider model catalog without secrets."""
        catalog = self.get_provider_model_catalog_snapshot()
        provider_profiles = self.providers_config
        for provider_name, provider_entry in catalog.get("providers", {}).items():
            provider_cfg = provider_profiles.get(provider_name, {})
            provider_type = str(provider_cfg.get("type", provider_name) or provider_name).strip().lower()
            provider_entry["provider_type"] = provider_type
            provider_entry["supports_refresh"] = provider_type == "openai_compatible" and bool(
                str(provider_cfg.get("base_url", "") or "").strip()
            )
        return catalog

    def _sync_provider_catalog_to_legacy_fields(self, provider_name: str) -> None:
        catalog = self.provider_model_catalog
        provider_entry = catalog.get("providers", {}).get(provider_name, {})
        providers = self.providers_config
        if provider_name in providers:
            model_ids = [item["id"] for item in provider_entry.get("models", [])]
            providers[provider_name]["models"] = model_ids
            self._config["providers"] = providers
        if provider_name == "openai_compatible":
            legacy = deepcopy(self._config.get("openai_compatible", {}))
            legacy["model"] = str(provider_entry.get("default_model", "") or "").strip()
            self._config["openai_compatible"] = legacy

    def add_provider_model(
        self,
        provider_name: str,
        model_id: str,
        label: Optional[str] = None,
        capabilities: Optional[Dict[str, Any]] = None,
        *,
        source: str = "user",
    ) -> bool:
        provider_name = str(provider_name or "").strip().lower()
        model_id = str(model_id or "").strip()
        if not provider_name or not model_id:
            return False

        catalog = self.provider_model_catalog
        providers = catalog.get("providers", {})
        if provider_name not in providers:
            return False

        entry = providers[provider_name]
        models = entry.get("models", [])
        if any(item.get("id") == model_id for item in models):
            return False

        models.append(
            {
                "id": model_id,
                "label": str(label or model_id).strip() or model_id,
                "enabled": True,
                "source": str(source or "user").strip() or "user",
                "capabilities": _normalize_catalog_capabilities(capabilities),
            }
        )
        if not entry.get("default_model"):
            entry["default_model"] = model_id
        self.provider_model_catalog = catalog

        if provider_name == "gemini":
            timeout = next((item.get("timeout", 10) for item in DEFAULT_MODELS if item["model_id"] == model_id), 10)
            self.add_model(model_id, is_active=True, timeout=int(timeout or 10))
            self._config["provider_model_catalog"] = self._normalize_provider_model_catalog(self._config.get("provider_model_catalog"))

        self._sync_provider_catalog_to_legacy_fields(provider_name)
        return True

    def remove_provider_model(self, provider_name: str, model_id: str) -> bool:
        provider_name = str(provider_name or "").strip().lower()
        model_id = str(model_id or "").strip()
        if not provider_name or not model_id:
            return False

        catalog = self.provider_model_catalog
        providers = catalog.get("providers", {})
        entry = providers.get(provider_name)
        if not entry:
            return False

        models = entry.get("models", [])
        next_models = [item for item in models if item.get("id") != model_id]
        if len(next_models) == len(models):
            return False

        entry["models"] = next_models
        if entry.get("default_model") == model_id:
            entry["default_model"] = next((item["id"] for item in next_models if item.get("enabled", True)), next_models[0]["id"] if next_models else "")
        self.provider_model_catalog = catalog

        if provider_name == "gemini":
            self.remove_model(model_id)
            self._config["provider_model_catalog"] = self._normalize_provider_model_catalog(self._config.get("provider_model_catalog"))

        self._sync_provider_catalog_to_legacy_fields(provider_name)
        return True

    def set_provider_model_enabled(self, provider_name: str, model_id: str, enabled: bool) -> bool:
        provider_name = str(provider_name or "").strip().lower()
        model_id = str(model_id or "").strip()
        catalog = self.provider_model_catalog
        entry = catalog.get("providers", {}).get(provider_name)
        if not entry:
            return False

        for model_entry in entry.get("models", []):
            if model_entry.get("id") == model_id:
                model_entry["enabled"] = bool(enabled)
                if not enabled and entry.get("default_model") == model_id:
                    entry["default_model"] = next(
                        (item["id"] for item in entry.get("models", []) if item.get("id") != model_id and item.get("enabled", True)),
                        "",
                    )
                elif enabled and not entry.get("default_model"):
                    entry["default_model"] = model_id
                self.provider_model_catalog = catalog
                if provider_name == "gemini":
                    for strategy_entry in self._config.get("waterfall_strategy", []):
                        if strategy_entry.get("model_id") == model_id:
                            strategy_entry["is_active"] = bool(enabled)
                            break
                    self._config["provider_model_catalog"] = self._normalize_provider_model_catalog(self._config.get("provider_model_catalog"))
                self._sync_provider_catalog_to_legacy_fields(provider_name)
                return True
        return False

    def set_provider_default_model(self, provider_name: str, model_id: str) -> bool:
        provider_name = str(provider_name or "").strip().lower()
        model_id = str(model_id or "").strip()
        catalog = self.provider_model_catalog
        entry = catalog.get("providers", {}).get(provider_name)
        if not entry:
            return False
        if not any(item.get("id") == model_id for item in entry.get("models", [])):
            return False
        entry["default_model"] = model_id
        self.provider_model_catalog = catalog
        self._sync_provider_catalog_to_legacy_fields(provider_name)
        return True

    def export_provider_model_catalog(self, path: str) -> bool:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(self.get_provider_model_catalog_public(), handle, indent=2, ensure_ascii=False)
        return True

    def import_provider_model_catalog(self, path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as handle:
            imported = json.load(handle)
        self.provider_model_catalog = imported
        for provider_name in self.provider_model_catalog.get("providers", {}):
            self._sync_provider_catalog_to_legacy_fields(provider_name)
        return self.get_provider_model_catalog_public()

    def refresh_provider_models(self, provider_name: str) -> list[str]:
        from datetime import datetime
        provider_name = str(provider_name or "").strip().lower()
        providers = self.providers_config
        provider_cfg = providers.get(provider_name, {})
        provider_type = str(provider_cfg.get("type", provider_name) or provider_name).strip().lower()
        if provider_type != "openai_compatible":
            raise ValueError(f"Provider '{provider_name}' does not support dynamic model refresh.")

        base_url = str(provider_cfg.get("base_url", "") or "").strip()
        if not base_url:
            raise ValueError(f"Provider '{provider_name}' does not have a configured base URL.")

        api_keys = provider_cfg.get("api_keys", [])
        api_key = str(api_keys[0] if isinstance(api_keys, list) and api_keys else "").strip()
        endpoint = f"{base_url.rstrip('/')}/models" if base_url.rstrip("/").endswith("/v1") else f"{base_url.rstrip('/')}/v1/models"
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        request = urllib.request.Request(endpoint, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=int(provider_cfg.get("timeout", 15) or 15)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = str(exc)
            clean = _sanitize_catalog_error_detail(detail or str(exc), api_key)
            raise RuntimeError(f"Model refresh failed for {provider_name}: {clean}") from exc
        except Exception as exc:
            clean = _sanitize_catalog_error_detail(str(exc), api_key)
            raise RuntimeError(f"Model refresh failed for {provider_name}: {clean}") from exc

        data = payload.get("data", payload if isinstance(payload, list) else [])
        if not isinstance(data, list):
            raise RuntimeError(f"Model refresh failed for {provider_name}: unsupported /models response.")

        discovered_records = []
        now_iso = datetime.now().isoformat()

        for item in data:
            if isinstance(item, dict):
                model_id = str(item.get("id") or item.get("model") or "").strip()
                raw_meta = {k: v for k, v in item.items() if k not in ("api_key", "secret", "token")}
            else:
                model_id = str(item or "").strip()
                raw_meta = {}

            if not model_id:
                continue

            if provider_name == "nvidia_nim":
                model_lower = model_id.lower()
                # Block contaminated prefixes/namespaces
                if model_lower.startswith(("models/gemini", "gemini-", "gpt-", "claude-")):
                    continue
                if model_id in ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"):
                    continue

            is_vision = any(kw in model_id.lower() for kw in ("vision", "vl", "multimodal", "gui"))
            is_embedding = "embed" in model_id.lower()
            is_rerank = "rerank" in model_id.lower()

            record = {
                "id": model_id,
                "label": model_id,
                "enabled": True,
                "source": "api_discovered",
                "visibility": "current_key_visible",
                "capabilities": {
                    "text": not (is_embedding or is_rerank),
                    "vision": is_vision,
                    "embedding": is_embedding,
                    "rerank": is_rerank,
                    "unknown": False
                },
                "discovered_at": now_iso,
                "last_validated_at": now_iso,
                "provider": provider_name,
                "display_name": model_id,
                "raw_metadata": raw_meta
            }
            discovered_records.append(record)

        if not discovered_records:
            raise RuntimeError(f"Model refresh failed for {provider_name}: no models returned.")

        current_catalog = self.provider_model_catalog
        providers_sec = current_catalog.setdefault("providers", {})
        entry = providers_sec.setdefault(provider_name, {"default_model": "", "models": []})

        existing_models = entry.get("models", [])
        merged_models = _merge_model_catalog_lists(existing_models, discovered_records)

        # Mark previous api_discovered models that are not returned as unavailable
        discovered_ids = {r["id"] for r in discovered_records}
        for m in merged_models:
            if m["id"] not in discovered_ids:
                if m.get("source") == "api_discovered":
                    m["visibility"] = "unavailable"
                else:
                    m["visibility"] = "unverified"

        entry["models"] = merged_models

        # Set or preserve default model
        default_model = entry.get("default_model", "")
        if default_model and not any(m["id"] == default_model and m.get("enabled", True) for m in merged_models):
            enabled_models = [m["id"] for m in merged_models if m.get("enabled", True)]
            entry["default_model"] = enabled_models[0] if enabled_models else ""
        elif not default_model:
            enabled_models = [m["id"] for m in merged_models if m.get("enabled", True)]
            entry["default_model"] = enabled_models[0] if enabled_models else ""

        self.provider_model_catalog = current_catalog
        self._sync_provider_catalog_to_legacy_fields(provider_name)

        return [r["id"] for r in discovered_records]

    def update_provider_enabled(self, provider_name: str, enabled: bool):
        """Update enabled state of a provider."""
        providers = self.providers_config
        if provider_name in providers:
            providers[provider_name]["enabled"] = bool(enabled)
            self.providers_config = providers

    def add_provider_api_key(self, provider_name: str, api_key: str) -> bool:
        """Add API Key to a specific provider's pool."""
        api_key = str(api_key or "").strip()
        if not api_key:
            return False
            
        # Legacy Gemini compatibility
        if provider_name == "gemini":
            keys = list(self.api_keys)
            if api_key not in keys:
                keys.append(api_key)
                self.api_keys = keys
                
        providers = self.providers_config
        if provider_name in providers:
            keys = providers[provider_name].get("api_keys", [])
            if not isinstance(keys, list):
                keys = []
            if api_key not in keys:
                keys.append(api_key)
                providers[provider_name]["api_keys"] = keys
                self.providers_config = providers
                return True
        return False

    def remove_provider_api_key(self, provider_name: str, key_index: int) -> bool:
        """Remove API key at index from a specific provider's pool."""
        # Legacy Gemini compatibility
        if provider_name == "gemini":
            keys = list(self.api_keys)
            if 0 <= key_index < len(keys):
                keys.pop(key_index)
                self.api_keys = keys

        providers = self.providers_config
        if provider_name in providers:
            keys = providers[provider_name].get("api_keys", [])
            if isinstance(keys, list) and 0 <= key_index < len(keys):
                keys.pop(key_index)
                providers[provider_name]["api_keys"] = keys
                self.providers_config = providers
                return True
        return False

    def update_provider_default_model(self, provider_name: str, model: str):
        """Update default model pool of a provider."""
        self.set_provider_default_model(provider_name, model)

    def update_provider_base_url(self, provider_name: str, base_url: str):
        """Update base URL of custom/OpenAI compatible providers."""
        base_url = str(base_url or "").strip()
        providers = self.providers_config
        if provider_name in providers:
            providers[provider_name]["base_url"] = base_url
            self.providers_config = providers

    @property
    def auto_refresh_provider_models(self) -> bool:
        return bool(self._config.get("auto_refresh_provider_models", True))

    @auto_refresh_provider_models.setter
    def auto_refresh_provider_models(self, value: bool):
        self._config["auto_refresh_provider_models"] = bool(value)

    @property
    def provider_model_refresh_ttl_hours(self) -> int:
        return int(self._config.get("provider_model_refresh_ttl_hours", 24))

    @provider_model_refresh_ttl_hours.setter
    def provider_model_refresh_ttl_hours(self, value: int):
        self._config["provider_model_refresh_ttl_hours"] = int(value)

    @property
    def provider_model_refresh_state(self) -> Dict[str, Dict[str, Any]]:
        value = self._config.get("provider_model_refresh_state", {})
        if not isinstance(value, dict):
            value = {}
        defaults = get_default_provider_model_refresh_state()
        merged = deepcopy(defaults)
        for provider_name, entry in value.items():
            if provider_name in merged and isinstance(entry, dict):
                merged[provider_name].update(entry)
        return merged

    @provider_model_refresh_state.setter
    def provider_model_refresh_state(self, value: Dict[str, Dict[str, Any]]):
        defaults = get_default_provider_model_refresh_state()
        merged = deepcopy(defaults)
        if isinstance(value, dict):
            for provider_name, entry in value.items():
                if provider_name in merged and isinstance(entry, dict):
                    merged[provider_name].update(entry)
        self._config["provider_model_refresh_state"] = merged

    def should_auto_refresh_provider_models(self, provider_id: str, now: Optional[datetime] = None) -> bool:
        """
        Check if a provider should undergo automatic model catalog refresh.
        """
        if not self.auto_refresh_provider_models:
            return False

        provider_id = str(provider_id or "").strip().lower()
        if provider_id == "google":
            return False

        catalog = self.get_provider_model_catalog_public()
        provider_entry = catalog.get("providers", {}).get(provider_id, {})
        if not provider_entry.get("supports_refresh", False):
            return False

        provider_cfg = self.providers_config.get(provider_id, {})
        base_url = str(provider_cfg.get("base_url", "") or "").strip()
        if not base_url:
            return False

        api_keys = provider_cfg.get("api_keys", [])
        has_key = any(str(k or "").strip() for k in api_keys)
        allow_no_key = bool(provider_cfg.get("allow_no_key_local", False))
        if not (has_key or allow_no_key):
            return False

        state = self.provider_model_refresh_state.get(provider_id, {})
        last_refreshed_str = state.get("last_refreshed_at")
        if not last_refreshed_str:
            return True

        try:
            last_refreshed = datetime.fromisoformat(last_refreshed_str)
        except ValueError:
            return True

        if now is None:
            now = datetime.now()

        ttl = timedelta(hours=self.provider_model_refresh_ttl_hours)
        return now - last_refreshed >= ttl

    def record_provider_model_refresh_result(
        self,
        provider_id: str,
        status: str,
        count: int,
        error: Optional[str] = None,
    ) -> None:
        """
        Record the outcome of a provider model refresh and persist it.
        """
        provider_id = str(provider_id or "").strip().lower()
        if status not in PROVIDER_MODEL_REFRESH_STATUSES:
            status = "error"

        state = self.provider_model_refresh_state
        entry = state.setdefault(provider_id, _blank_provider_model_refresh_entry())

        provider_cfg = self.providers_config.get(provider_id, {})
        api_keys = provider_cfg.get("api_keys", [])
        api_key = str(api_keys[0] if isinstance(api_keys, list) and api_keys else "").strip()

        sanitized_error = ""
        if error:
            sanitized_error = _sanitize_catalog_error_detail(error, api_key)

        entry["last_refreshed_at"] = datetime.now().isoformat()
        entry["last_status"] = status
        entry["last_count"] = count
        entry["last_error"] = sanitized_error

        self.provider_model_refresh_state = state
        self.save_config()

    def get_provider_model_refresh_state_public(self) -> Dict[str, Dict[str, Any]]:
        """
        Get public, safe copy of refresh states.
        """
        return deepcopy(self.provider_model_refresh_state)


class WaterfallGeminiService:
    """
    AI Service with Waterfall fallback strategy + API Key Rotation.
    Now reads configuration from external JSON file.
    
    Features:
    - Tries multiple models in order (waterfall)
    - Auto-rotates API keys on quota errors
    - Falls back to web browser if all fails
    """
    
    def __init__(self, api_key: Optional[str] = None, config_path: Optional[str] = None):
        """
        Initialize the AI service.
        
        Args:
            api_key: Override API key (uses config/env if None)
            config_path: Path to config JSON file
        """
        self.config_manager = AIConfigManager(config_path)
        self.api_key = api_key or self.config_manager.api_key
        self._client = None
        self._configured = False
        self._is_new_sdk = False
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
        
        if not self.api_key:
            logger.warning("⚠️ GEMINI_API_KEY not found! Will use web fallback.")
        else:
            self._configure_genai()
    
    @property
    def models_priority(self) -> List[str]:
        """Get active models from config."""
        return self.config_manager.active_models
    
    def reload_config(self):
        """Reload configuration from file."""
        self.config_manager.load_config()
        new_api_key = self.config_manager.api_key
        
        # If API key changed, reconfigure
        if new_api_key and new_api_key != self.api_key:
            self.api_key = new_api_key
            self._configured = False  # Reset to allow reconfigure
            self._configure_genai()
        elif new_api_key and not self._configured:
            self.api_key = new_api_key
            self._configure_genai()
    
    def _configure_genai(self, force: bool = False) -> bool:
        """Lazily configure the genai library. Supports both new and legacy SDKs."""
        if self._configured and not force:
            return True
        
        if not self.api_key:
            return False

        # Attempt 1: New SDK (google-genai)
        try:
            from google import genai
            logger.info("🔧 Configuring Gemini with new SDK...")
            self._client = genai.Client(api_key=self.api_key)
            self._is_new_sdk = True
            self._configured = True
            logger.info("✅ Gemini API (New SDK) configured successfully")
            return True
        except (ImportError, Exception):
            # Attempt 2: Legacy SDK (google.generativeai)
            try:
                import google.generativeai as genai_legacy
                logger.info("🔧 Configuring Gemini with legacy SDK...")
                genai_legacy.configure(api_key=self.api_key)
                self._client = genai_legacy
                self._is_new_sdk = False
                self._configured = True
                logger.info("✅ Gemini API (Legacy SDK) configured successfully")
                return True
            except Exception as e:
                logger.error(f"❌ Failed to configure Gemini with either SDK: {e}")
                return False
    
    def is_available(self) -> bool:
        """Check if AI service is available. Auto-reload config first."""
        # Always reload config to pick up any changes
        self.reload_config()
        return self._configured and bool(self.api_key)
    
    def _generate_with_timeout(self, model_name: str, prompt: str, timeout: float) -> str:
        """Call Gemini model with strict execution timeout using a ThreadPoolExecutor."""
        def call_gemini():
            if self._is_new_sdk:
                response = self._client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                return response.text
            else:
                model = self._client.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                return response.text

        future = self._executor.submit(call_gemini)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as te:
            future.cancel()
            chunk_preview = prompt[:50].replace('\n', ' ') + "..."
            logger.error(f"⏱️ Model {model_name} timed out after {timeout}s | Key: [configured] | Chunk preview: {chunk_preview}")
            raise TimeoutError(f"Model {model_name} timed out after {timeout} seconds") from te

    def generate_response(self, prompt: str, preferred_models: Optional[List[str]] = None) -> dict:
        """
        Execute Waterfall strategy to generate AI response.
        Automatically rotates API keys on quota errors.
        
        Returns:
            dict with keys: 'text', 'model_used', 'status'
        """
        if not self.api_key:
            return {
                "text": "",
                "model_used": "WEB_FALLBACK",
                "status": "fallback"
            }
        
        if not self._configured:
            if not self._configure_genai():
                return {
                    "text": "",
                    "model_used": "WEB_FALLBACK", 
                    "status": "fallback"
                }
        
        last_error = None
        
        if preferred_models is not None:
            active_models = []
            seen_models = set()
            for model_name in preferred_models:
                normalized_model = str(model_name or "").strip()
                if normalized_model and normalized_model not in seen_models:
                    active_models.append(normalized_model)
                    seen_models.add(normalized_model)
        else:
            # Filter priority models for text profile validation
            active_models = [
                m for m in self.models_priority
                if validate_model_for_profile(m, "text")
            ]
        
        for model_name in active_models:
            # Find timeout in config
            model_config = next((m for m in self.config_manager.waterfall_strategy if m["model_id"] == model_name), None)
            timeout = model_config.get("timeout", 10) if model_config else 10
            
            try:
                logger.info(f"🔄 Attempting model: {model_name} (timeout={timeout}s)...")
                text_result = self._generate_with_timeout(model_name, prompt, timeout)
                logger.info(f"✅ Success with: {model_name}")
                return {
                    "text": text_result,
                    "model_used": model_name,
                    "status": "success"
                }
                
            except Exception as e:
                error_str = str(e).lower()
                logger.error(f"❌ Failed {model_name}: {e}")
                last_error = e
                
                # Check for quota/rate limit errors - try rotating key
                if ("429" in str(e) or "quota" in error_str or "rate" in error_str or "limit" in error_str):
                    logger.warning(f"⚠️ Quota/Rate limit detected for {model_name}")
                    
                    # Try rotating API key if we have multiple
                    if len(self.config_manager.api_keys) > 1:
                        logger.info("🚀 Attempting API key rotation...")
                        if self.config_manager.rotate_api_key():
                            self.api_key = self.config_manager.api_key
                            self._configure_genai(force=True)
                            # Retry same model with new key
                            try:
                                text_result = self._generate_with_timeout(model_name, prompt, timeout)
                                logger.info(f"✅ Retry success with new key: {model_name}")
                                return {
                                    "text": text_result,
                                    "model_used": model_name,
                                    "status": "success"
                                }
                            except Exception as retry_e:
                                logger.warning(f"⚠️ Retry with new key also failed: {retry_e}")
                
                continue
        
        # ALL MODELS FAILED
        logger.warning("⚠️ All API models failed. Returning fallback status.")
        
        return {
            "text": f"All models failed. Last error: {str(last_error)}",
            "model_used": "AI_EXHAUSTED",
            "status": "fallback"
        }
    
    def _google_translate_fallback(self, text: str, source_lang: str, target_lang: str) -> dict:
        """Fallback to Google Translate using deep_translator."""
        try:
            from deep_translator import GoogleTranslator
            logger.info(f"🌐 Falling back to Google Translate: {source_lang} -> {target_lang}")
            
            # Simple normalization for deep_translator
            src = source_lang.lower() if source_lang.lower() != 'auto' else 'auto'
            dest = target_lang.lower()
            
            translator = GoogleTranslator(source=src, target=dest)
            translated_text = translator.translate(text)
            
            return {
                "text": translated_text,
                "model_used": "GOOGLE_TRANSLATE_FALLBACK",
                "status": "success"
            }
        except Exception as e:
            logger.error(f"❌ Google Translate fallback failed: {e}")
            return {
                "text": f"All AI models failed, and Google Translate fallback also failed: {e}",
                "model_used": "NONE",
                "status": "error"
            }

    @staticmethod
    def _sanitize_glossary_value(value: Any) -> str:
        """Flatten glossary values to a single prompt-safe line."""
        if value is None:
            return ""
        normalized = str(value).replace("\r", "\n")
        sanitized = " ".join(part.strip() for part in normalized.splitlines() if part.strip())
        return sanitized.strip()

    def _build_glossary_prompt_lines(self, relevant_terms: List[Dict[str, Any]]) -> List[str]:
        glossary_lines = []
        for term in relevant_terms:
            source_term = self._sanitize_glossary_value(term.get("source_term"))
            target_term = self._sanitize_glossary_value(term.get("target_term"))
            if source_term and target_term:
                glossary_lines.append(f"{source_term} => {target_term}")
        return glossary_lines

    def _build_glossary_prompt_part(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        glossary_terms: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Build the glossary prompt section for prompt-level enforcement only.

        "validate" is reserved for future QA validation and intentionally does
        not inject glossary terms yet.
        """
        if not self.config_manager.use_glossary:
            return ""

        enforce_level = self.config_manager.glossary_enforcement_level
        if enforce_level != "prompt":
            return ""

        if glossary_terms is None:
            try:
                from translation_app.core.translation_memory import get_tm_manager

                tm = get_tm_manager()
                glossary_terms = tm.find_relevant_terms(
                    text,
                    source_lang,
                    target_lang,
                    max_terms=self.config_manager.max_glossary_terms_per_segment,
                )
            except Exception as ge:
                logger.error(f"Failed to fetch glossary terms for prompt injection: {ge}")
                return ""

        glossary_lines = self._build_glossary_prompt_lines(glossary_terms or [])

        if not glossary_lines:
            return ""

        return "\nUse this glossary strictly:\n" + "\n".join(glossary_lines) + "\n"

    def build_translation_prompt(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        glossary_terms: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        glossary_part = self._build_glossary_prompt_part(
            text,
            source_lang,
            target_lang,
            glossary_terms=glossary_terms,
        )
        return f"""Translate the following text from {source_lang} to {target_lang}.
Provide ONLY the translation, without any explanations or notes.
{glossary_part}
TEXT: {text}

TRANSLATION:"""
    
    # =========================================================================
    # TRANSLATION SPECIFIC METHODS
    # =========================================================================
    
    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        allow_google_fallback: bool = True,
        preferred_models: Optional[List[str]] = None,
    ) -> dict:
        """Translate text using Waterfall strategy with optional Google fallback."""
        return self.translate_with_glossary_terms(
            text,
            source_lang,
            target_lang,
            glossary_terms=None,
            allow_google_fallback=allow_google_fallback,
            preferred_models=preferred_models,
        )

    def translate_with_glossary_terms(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        glossary_terms: Optional[List[Dict[str, Any]]] = None,
        allow_google_fallback: bool = True,
        preferred_models: Optional[List[str]] = None,
    ) -> dict:
        """Translate text using explicit glossary terms when provided."""
        prompt = self.build_translation_prompt(
            text,
            source_lang,
            target_lang,
            glossary_terms=glossary_terms,
        )
        if preferred_models is None:
            result = self.generate_response(prompt)
        else:
            result = self.generate_response(prompt, preferred_models=preferred_models)
        
        # If AI failed, use Google Translate fallback if allowed
        if result.get("status") == "fallback":
            if allow_google_fallback:
                return self._google_translate_fallback(text, source_lang, target_lang)
            else:
                return {
                    "text": result.get("text", "AI Translation failed"),
                    "model_used": result.get("model_used", "AI_EXHAUSTED"),
                    "status": "error",
                    "error_message": "AI translation failed and Google fallback is disabled."
                }
            
        return result
    
    def analyze_sentence(self, text: str, source_lang: str, target_lang: str, context: Optional[str] = None) -> dict:
        """Deeply analyze sentence meaning with AI, fallback to Google Translate."""
        prompt = f"""Phân tích ý nghĩa sâu của đoạn văn sau từ ngôn ngữ {source_lang} sang {target_lang}.
Đặc biệt nếu là tiếng Nhật hoặc các ngôn ngữ có nhiều tầng nghĩa, hãy mổ xẻ cấu trúc và ngữ cảnh.

ĐOẠN VĂN CẦN PHÂN TÍCH: 
{text}

BỐI CẢNH (NẾU CÓ): 
{context if context else "Không có bối cảnh cụ thể"}

YÊU CẦU:
1. Dịch nghĩa bóng và nghĩa đen (nếu có).
2. Phân tích các thành phần quan trọng hoặc các cụm từ/thành ngữ đặc biệt.
3. Giải thích ý đồ của người nói trong ngữ cảnh này.
4. Đề xuất cách dịch thoát ý, dễ hiểu nhất cho người Việt.

TRẢ LỜI BẰNG TIẾNG VIỆT:"""
        result = self.generate_response(prompt)
        
        # If AI failed, use Google Translate fallback (just for the text)
        if result.get("status") == "fallback":
            logger.warning("⚠️ AI Analysis failed, falling back to simple Google Translation")
            return self._google_translate_fallback(text, source_lang, target_lang)
            
        return result
    
    def _generate_vision_with_timeout(self, model_name: str, prompt: str, image_bytes: bytes, timeout: float) -> str:
        """Call Gemini vision model with strict execution timeout using a ThreadPoolExecutor."""
        def call_vision():
            if self._is_new_sdk:
                from google.genai import types
                response = self._client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Content(
                            parts=[
                                types.Part(text=prompt),
                                types.Part(
                                    inline_data=types.Blob(
                                        mime_type="image/png",
                                        data=image_bytes
                                    )
                                )
                            ]
                        )
                    ]
                )
                return response.text
            else:
                import base64
                image_b64 = base64.b64encode(image_bytes).decode('utf-8')
                model = self._client.GenerativeModel(model_name)
                image_part = {
                    "mime_type": "image/png",
                    "data": image_b64
                }
                response = model.generate_content([prompt, image_part])
                return response.text

        future = self._executor.submit(call_vision)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as te:
            future.cancel()
            logger.error(f"⏱️ Vision model {model_name} timed out after {timeout}s | Key: [configured]")
            raise TimeoutError(f"Vision model {model_name} timed out after {timeout} seconds") from te

    def translate_image_with_vision(self, image_bytes: bytes, source_lang: str, target_lang: str, 
                                     preserve_format: bool = True, custom_hint: str = "") -> dict:
        """
        Use Gemini Vision to OCR and translate image in ONE step.
        This bypasses Tesseract OCR entirely and leverages Gemini's multimodal capabilities.
        
        Especially useful for:
        - Scanned PDFs with complex layouts
        - Japanese/Chinese technical documents
        - Images with mixed text and graphics
        
        Args:
            image_bytes: Image data as bytes (PNG, JPEG, etc.)
            source_lang: Source language code
            target_lang: Target language code
            preserve_format: If True, try to preserve layout/table structure
            custom_hint: Optional hint about image layout (e.g., "This is a 2x2 grid of pages")
            
        Returns:
            dict with 'text', 'model_used', 'status'
        """
        if not self.api_key:
            return {
                "text": "",
                "model_used": "NO_API_KEY",
                "status": "error"
            }
        
        if not self._configured:
            if not self._configure_genai():
                return {
                    "text": "",
                    "model_used": "CONFIG_FAILED", 
                    "status": "error"
                }
        
        # Add custom hint to prompt if provided
        layout_info = f"\n\n📌 GỢI Ý LAYOUT: {custom_hint}" if custom_hint else ""
        
        # Create prompt for vision model
        if preserve_format:
            prompt = f"""Bạn là chuyên gia dịch thuật kỹ thuật. Hãy thực hiện các bước sau với hình ảnh này:{layout_info}

1. NHẬN DIỆN tất cả văn bản trong ảnh (bao gồm cả text trong bảng, header, footer, chú thích).
2. DỊCH tất cả văn bản từ {source_lang} sang {target_lang}.
3. GIỮ NGUYÊN cấu trúc layout gốc (nếu có bảng, giữ format bảng; nếu có đánh số, giữ đánh số).

QUY TẮC:
- Thuật ngữ kỹ thuật giữ nguyên tiếng Anh trong ngoặc nếu cần (ví dụ: "Bảng mạch in (PCB)")
- Số liệu, đơn vị đo lường giữ nguyên
- Mã sản phẩm, part number giữ nguyên

CHỈ TRẢ VỀ VĂN BẢN ĐÃ DỊCH, KHÔNG GIẢI THÍCH."""
        else:
            prompt = f"""Đọc và dịch tất cả văn bản trong hình ảnh từ {source_lang} sang {target_lang}.{layout_info}
Chỉ trả về bản dịch, không giải thích."""

        last_error = None
        
        # Filter active priority models for vision profile validation
        vision_models = [
            m for m in self.models_priority 
            if validate_model_for_profile(m, "vision")
        ]
        # Fallback to default vision models if priority list yields none
        if not vision_models:
            vision_models = VISION_MODELS.copy()
        
        for model_name in vision_models:
            model_config = next((m for m in self.config_manager.waterfall_strategy if m["model_id"] == model_name), None)
            timeout = model_config.get("timeout", 15) if model_config else 15
            
            try:
                logger.info(f"🖼️ Vision OCR+Translate with: {model_name} (timeout={timeout}s)...")
                text_result = self._generate_vision_with_timeout(model_name, prompt, image_bytes, timeout)
                logger.info(f"✅ Vision translation success with: {model_name}")
                return {
                    "text": text_result,
                    "model_used": model_name,
                    "status": "success"
                }
                
            except Exception as e:
                error_str = str(e).lower()
                logger.warning(f"❌ Vision model {model_name} failed: {e}")
                last_error = e
                
                # Try API key rotation on quota errors
                if ("429" in str(e) or "quota" in error_str or "rate" in error_str):
                    if len(self.config_manager.api_keys) > 1:
                        if self.config_manager.rotate_api_key():
                            self.api_key = self.config_manager.api_key
                            self._configure_genai(force=True)
                
                continue
        
        logger.error(f"❌ All vision models failed. Last error: {last_error}")
        return {
            "text": f"Vision translation failed: {last_error}",
            "model_used": "VISION_FAILED",
            "status": "error"
        }


def test_single_model_connection(api_key: str, model_name: str, test_prompt: str = "Ping") -> Dict[str, Any]:
    """
    Test connection to a single model.
    Used by UI to validate models before adding to strategy.
    
    Args:
        api_key: Gemini API key to test
        model_name: Model ID to test
        test_prompt: Simple prompt for testing
        
    Returns:
        dict with 'success', 'latency', 'reply' or 'error'
    """
    try:
        from google import genai
        
        start_time = time.time()
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=test_prompt
        )
        latency = round((time.time() - start_time) * 1000)
        
        return {
            "success": True,
            "latency": f"{latency}ms",
            "reply": "[REDACTED]"
        }
    except ImportError:
        # Try legacy SDK
        try:
            import google.generativeai as genai_legacy
            
            start_time = time.time()
            genai_legacy.configure(api_key=api_key)
            model = genai_legacy.GenerativeModel(model_name)
            response = model.generate_content(test_prompt)
            latency = round((time.time() - start_time) * 1000)
            
            return {
                "success": True,
                "latency": f"{latency}ms",
                "reply": "[REDACTED]"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================
_service_instance: Optional[WaterfallGeminiService] = None

def get_ai_service(api_key: Optional[str] = None) -> WaterfallGeminiService:
    """Get singleton AI service instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = WaterfallGeminiService(api_key)
    return _service_instance

def get_config_manager() -> AIConfigManager:
    """Get config manager from singleton service."""
    return get_ai_service().config_manager
