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
import time
import logging
import concurrent.futures
from typing import Optional, List, Dict, Any
from pathlib import Path

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
    "gemini-2.5-pro",
    "gemini-3-flash-preview",
    "gemini-3-pro-preview"
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
        # Vision models must be in VISION_MODELS
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
            
        merged = defaults.copy()
        
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
                else:
                    merged[key] = config_data[key]
                    
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
        return {
            "api_key": os.getenv("GEMINI_API_KEY", ""),
            "api_keys": [],
            "current_key_index": 0,
            "waterfall_strategy": DEFAULT_MODELS.copy(),
            "use_translation_memory": True,
            "min_segment_length_to_cache": 2,
            "use_glossary": True,
            "max_glossary_terms_per_segment": 20,
            "glossary_enforcement_level": "prompt"
        }
    
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

    def generate_response(self, prompt: str) -> dict:
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

    def _build_glossary_prompt_part(self, text: str, source_lang: str, target_lang: str) -> str:
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

        try:
            from translation_app.core.translation_memory import get_tm_manager

            tm = get_tm_manager()
            relevant_terms = tm.find_relevant_terms(
                text,
                source_lang,
                target_lang,
                max_terms=self.config_manager.max_glossary_terms_per_segment,
            )
        except Exception as ge:
            logger.error(f"Failed to fetch glossary terms for prompt injection: {ge}")
            return ""

        glossary_lines = []
        for term in relevant_terms:
            source_term = self._sanitize_glossary_value(term.get("source_term"))
            target_term = self._sanitize_glossary_value(term.get("target_term"))
            if source_term and target_term:
                glossary_lines.append(f"{source_term} => {target_term}")

        if not glossary_lines:
            return ""

        return "\nUse this glossary strictly:\n" + "\n".join(glossary_lines) + "\n"
    
    # =========================================================================
    # TRANSLATION SPECIFIC METHODS
    # =========================================================================
    
    def translate(self, text: str, source_lang: str, target_lang: str, allow_google_fallback: bool = True) -> dict:
        """Translate text using Waterfall strategy with optional Google fallback."""
        glossary_part = self._build_glossary_prompt_part(text, source_lang, target_lang)

        prompt = f"""Translate the following text from {source_lang} to {target_lang}.
Provide ONLY the translation, without any explanations or notes.
{glossary_part}
TEXT: {text}

TRANSLATION:"""
        result = self.generate_response(prompt)
        
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
