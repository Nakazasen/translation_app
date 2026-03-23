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
# DEFAULT MODELS - Ported from leetcode_mastery (giữ nguyên, không tự bịa)
# =============================================================================
DEFAULT_MODELS = [
    {"model_id": "gemini-3-pro-preview", "is_active": True, "timeout": 10},
    {"model_id": "gemini-3-flash-preview", "is_active": True, "timeout": 10},
    {"model_id": "gemini-2.5-pro", "is_active": True, "timeout": 10},
    {"model_id": "gemini-2.5-flash", "is_active": True, "timeout": 12},
    {"model_id": "gemini-robotics-er-1.5-preview", "is_active": True, "timeout": 28},
    {"model_id": "gemma-3-27b-it", "is_active": True, "timeout": 17},
    {"model_id": "gemma-3-12b-it", "is_active": True, "timeout": 18},
    {"model_id": "gemma-3-4b-it", "is_active": True, "timeout": 10},
    {"model_id": "gemma-3n-e2b-it", "is_active": True, "timeout": 9},
    {"model_id": "gemini-2.5-flash-lite", "is_active": True, "timeout": 7},
    {"model_id": "gemini-2.5-computer-use-preview-10-2025", "is_active": True, "timeout": 10},
    {"model_id": "gemini-2.5-flash-native-audio-latest", "is_active": True, "timeout": 10},
    {"model_id": "gemini-2.5-flash-preview-tts", "is_active": True, "timeout": 10},
    {"model_id": "gemma-3-1b-it", "is_active": True, "timeout": 10},
    {"model_id": "imagen-4.0-ultra-generate-001", "is_active": True, "timeout": 10},
    {"model_id": "veo-3.1-generate-preview", "is_active": True, "timeout": 10},
]


class AIConfigManager:
    """
    Manages AI configuration from external JSON file.
    Allows runtime updates without code changes.
    Supports API Key rotation for high-availability.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config = None
        self.load_config()
    
    def load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
                logger.info(f"✅ Loaded AI config from: {self.config_path}")
            else:
                logger.warning(f"⚠️ Config not found, using defaults: {self.config_path}")
                self._config = self._get_default_config()
                self.save_config()  # Create default config file
        except Exception as e:
            logger.error(f"❌ Failed to load config: {e}")
            self._config = self._get_default_config()
        
        return self._config
    
    def save_config(self) -> bool:
        """Save current configuration to JSON file."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logger.info(f"✅ Saved AI config to: {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to save config: {e}")
            return False
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Return default configuration."""
        return {
            "api_key": os.getenv("GEMINI_API_KEY", ""),
            "api_keys": [],
            "waterfall_strategy": DEFAULT_MODELS.copy()
        }
    
    # =========================================================================
    # API KEY MANAGEMENT - with Rotation Support
    # =========================================================================
    
    @property
    def api_key(self) -> str:
        """Get the current API key from config or environment.
        Priority: api_keys list > api_key > env variable
        """
        keys = self._config.get("api_keys", [])
        if keys and isinstance(keys, list) and len(keys) > 0:
            return keys[0]
        
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
        if value:
            self._config["api_key"] = value[0]
    
    def rotate_api_key(self) -> bool:
        """
        Cycle to the next API key in the pool.
        Moves the current key to the end of the 'api_keys' list.
        This is called automatically when quota/rate limit errors occur.
        """
        keys = self._config.get("api_keys", [])
        if not keys or not isinstance(keys, list) or len(keys) < 2:
            logger.warning("⚠️ Cannot rotate: Need at least 2 API keys")
            return False
            
        # Rotate: move first to last
        current_key = keys.pop(0)
        keys.append(current_key)
        self._config["api_keys"] = keys
        
        # Update the single api_key field for backward compatibility
        self._config["api_key"] = keys[0]
        
        self.save_config()
        logger.info(f"🔄 Rotated to next API key: {keys[0][:8]}...")
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
            logger.info(f"🔧 Configuring Gemini with new SDK, key: {self.api_key[:8]}...")
            self._client = genai.Client(api_key=self.api_key)
            self._is_new_sdk = True
            self._configured = True
            logger.info("✅ Gemini API (New SDK) configured successfully")
            return True
        except (ImportError, Exception):
            # Attempt 2: Legacy SDK (google.generativeai)
            try:
                import google.generativeai as genai_legacy
                logger.info(f"🔧 Configuring Gemini with legacy SDK, key: {self.api_key[:8]}...")
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
        
        for model_name in self.models_priority:
            try:
                logger.info(f"🔄 Attempting model: {model_name}...")
                
                if self._is_new_sdk:
                    # New SDK syntax
                    response = self._client.models.generate_content(
                        model=model_name,
                        contents=prompt
                    )
                    text_result = response.text
                else:
                    # Legacy SDK syntax
                    model = self._client.GenerativeModel(model_name)
                    response = model.generate_content(prompt)
                    text_result = response.text
                
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
                                if self._is_new_sdk:
                                    response = self._client.models.generate_content(
                                        model=model_name,
                                        contents=prompt
                                    )
                                    text_result = response.text
                                else:
                                    model = self._client.GenerativeModel(model_name)
                                    response = model.generate_content(prompt)
                                    text_result = response.text

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
    
    # =========================================================================
    # TRANSLATION SPECIFIC METHODS
    # =========================================================================
    
    def translate(self, text: str, source_lang: str, target_lang: str) -> dict:
        """Translate text using Waterfall strategy with Google fallback."""
        prompt = f"""Translate the following text from {source_lang} to {target_lang}.
Provide ONLY the translation, without any explanations or notes.

TEXT: {text}

TRANSLATION:"""
        result = self.generate_response(prompt)
        
        # If AI failed, use Google Translate fallback
        if result.get("status") == "fallback":
            return self._google_translate_fallback(text, source_lang, target_lang)
            
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
        import base64
        
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
        
        # Convert image to base64
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        
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
        
        # Try vision-capable models first
        vision_models = [
            "gemini-2.5-flash",
            "gemini-2.5-pro", 
            "gemini-3-flash-preview",
            "gemini-3-pro-preview",
        ]
        
        for model_name in vision_models:
            try:
                logger.info(f"🖼️ Vision OCR+Translate with: {model_name}...")
                
                if self._is_new_sdk:
                    # New SDK with vision
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
                    text_result = response.text
                else:
                    # Legacy SDK with vision
                    model = self._client.GenerativeModel(model_name)
                    
                    # Create image part
                    image_part = {
                        "mime_type": "image/png",
                        "data": image_b64
                    }
                    
                    response = model.generate_content([prompt, image_part])
                    text_result = response.text
                
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
            "reply": response.text[:200]  # Truncate for display
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
                "reply": response.text[:200]
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
