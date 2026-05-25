"""
Translation service using Google Translate
"""
import concurrent.futures
from typing import Optional
from deep_translator import GoogleTranslator

from translation_app.config import config
from translation_app.utils.error_handler import TranslationServiceError, handle_translation_error
from translation_app.utils.logger import logger
from translation_app.core.ai_service import get_ai_service


class TranslationService:
    """
    Translation service with optimized ThreadPoolExecutor usage
    """
    
    def __init__(self, max_workers: Optional[int] = None, timeout: Optional[int] = None):
        """
        Initialize translation service
        
        Args:
            max_workers: Maximum number of worker threads (defaults to config.max_workers)
            timeout: Translation timeout in seconds (defaults to config.translation_timeout)
        """
        self.max_workers = max_workers or config.max_workers
        self.timeout = timeout or config.translation_timeout
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)
        self.strategy = "waterfall"  # options: "google", "ai", "waterfall"
        logger.info(f"TranslationService initialized with {self.max_workers} workers. Strategy: {self.strategy}")
    
    def set_strategy(self, strategy: str):
        """Update translation strategy at runtime."""
        # Map UI display names to internal codes
        mapping = {
            "google translate (mặc định)": "google",
            "gemini ai (chỉ dùng ai)": "ai",
            "google translate -> gemini ai": "waterfall",
            "google -> gemini (waterfall)": "waterfall",
            "gemini ai -> google translate": "ai_waterfall"
        }
        self.strategy = mapping.get(strategy.lower(), "waterfall")
        logger.info(f"🔄 Translation strategy changed to: {self.strategy}")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - shutdown executor"""
        self.shutdown()
    
    def shutdown(self, wait: bool = True):
        """Shutdown the thread pool executor"""
        self.executor.shutdown(wait=wait)
        logger.info("TranslationService executor shut down")
    
    def translate_text(self, text: str, src_lang: str, dest_lang: str) -> str:
        """
        Translate text using Google Translate with automatic chunking
        
        Args:
            text: Text to translate
            src_lang: Source language code
            dest_lang: Destination language code
        
        Returns:
            Translated text
        
        Raises:
            TranslationServiceError: If translation fails
        """
        if text is None:
            return ""
        
        text = str(text)
        if not text.strip():
            return text

        # NEW STRATEGY: AI -> GOOGLE (ai_waterfall)
        if self.strategy == "ai_waterfall":
            logger.info("⚡ Mode: AI -> GOOGLE - Attempting Gemini first...")
            try:
                ai_service = get_ai_service()
                if ai_service.is_available():
                    result = ai_service.translate(text, src_lang, dest_lang, allow_google_fallback=False)
                    if result.get("status") == "success":
                        return result["text"]
                logger.warning("⚠️ Gemini fails in AI->GOOGLE mode, falling back to Google Translate")
            except Exception as e:
                logger.warning(f"⚠️ Gemini error in AI->GOOGLE mode: {e}. Falling back to Google Translate")

        # STRATEGY: AI ONLY
        if self.strategy == "ai":
            logger.info("⚡ Mode: AI ONLY - Using Gemini for translation...")
            ai_service = get_ai_service()
            if ai_service.is_available():
                result = ai_service.translate(text, src_lang, dest_lang, allow_google_fallback=False)
                if result.get("status") == "success":
                    return result["text"]
                else:
                    error_msg = result.get("error_message") or result.get("text") or "AI Translation failed"
                    raise TranslationServiceError(f"Gemini AI translation failed: {error_msg}")
            raise TranslationServiceError("Gemini AI translation failed or not configured.")
        
        # STRATEGY: GOOGLE or WATERFALL
        try:
            logger.info(f"🌐 Mode: {self.strategy.upper()} - Attempting Google Translate...")
            # Handle auto-detect language
            if src_lang.lower() == 'auto':
                normalized_src = 'auto'
            else:
                normalized_src = config.normalize_language_code(src_lang)
            
            normalized_dest = config.normalize_language_code(dest_lang)
            translator = GoogleTranslator(source=normalized_src, target=normalized_dest)
            max_length = config.max_text_length
            text_chunks = []
            
            # Split text into chunks
            start = 0
            while start < len(text):
                chunk = text[start:start + max_length]
                if chunk.strip():
                    text_chunks.append(chunk)
                start += max_length
            
            # Translate each chunk
            translated_chunks = []
            for chunk in text_chunks:
                try:
                    # Check chunk length before translation
                    if len(chunk) > 5000:
                        # If chunk is still too long, split further
                        sub_chunks = [chunk[i:i + 4000] for i in range(0, len(chunk), 4000)]
                        for sub_chunk in sub_chunks:
                            if sub_chunk.strip():
                                translated = translator.translate(sub_chunk)
                                translated_chunks.append(translated)
                    else:
                        translated = translator.translate(chunk)
                        translated_chunks.append(translated)
                except Exception as e:
                    error_msg = str(e).lower()
                    if "text length" in error_msg or "5000" in error_msg:
                        # If chunk is too long, split further
                        logger.warning(f"Chunk too long ({len(chunk)} chars), splitting further...")
                        sub_chunks = [chunk[i:i + 4000] for i in range(0, len(chunk), 4000)]
                        for sub_chunk in sub_chunks:
                            if sub_chunk.strip():
                                try:
                                    translated = translator.translate(sub_chunk)
                                    translated_chunks.append(translated)
                                except Exception as e2:
                                    logger.warning(f"Error translating sub-chunk: {e2}. Keeping original.")
                                    translated_chunks.append(sub_chunk)
                    else:
                        logger.warning(f"Error translating chunk: {e}. Keeping original.")
                        translated_chunks.append(chunk)
            
            translated_text = ''.join(translated_chunks)
            return translated_text
        
        except Exception as e:
            # AI WATERFALL FALLBACK
            logger.warning(f"⚠️ Primary translation (Google) failed: {e}. Attempting AI Waterfall...")
            try:
                ai_service = get_ai_service()
                if ai_service.is_available():
                    result = ai_service.translate(text, src_lang, dest_lang, allow_google_fallback=False)
                    if result.get("status") == "success":
                        logger.info(f"✅ AI Waterfall success using: {result.get('model_used')}")
                        return result["text"]
                
                # If AI fallback also failed or not available
                error_msg = handle_translation_error(e, "Translation failed")
                logger.error(f"Translation error: {e}")
                raise TranslationServiceError(error_msg, original_error=e) from e
            except Exception as ai_err:
                logger.error(f"❌ AI Fallback also failed: {ai_err}")
                error_msg = handle_translation_error(e, "Translation failed")
                raise TranslationServiceError(error_msg, original_error=e) from e
    
    def translate_long_text(self, text: str, src_lang: str, dest_lang: str, max_length: Optional[int] = None) -> str:
        """
        Translate long text by splitting into chunks
        
        Args:
            text: Text to translate
            src_lang: Source language code
            dest_lang: Destination language code
            max_length: Maximum length per chunk (defaults to config.max_text_length)
        
        Returns:
            Translated text
        
        Raises:
            TranslationServiceError: If translation fails
        """
        if text is None:
            return ""
        
        text = str(text)
        # Skip if text is only whitespace or too short
        if not text.strip() or len(text.strip()) < 2:
            return text
        
        # Ensure max_length doesn't exceed 4500
        if max_length is None:
            max_length = config.max_text_length
        elif max_length > config.max_text_length:
            max_length = config.max_text_length
        
        result = []
        start = 0
        while start < len(text):
            chunk = text[start:start + max_length]
            # Skip invalid chunks
            if not chunk.strip() or len(chunk.strip()) < 2:
                result.append(chunk)
            else:
                try:
                    # translate_text will handle splitting if needed
                    result.append(self.translate_text(chunk, src_lang, dest_lang))
                except Exception as exc:
                    error_msg = str(exc).lower()
                    if "text length" in error_msg or "5000" in error_msg:
                        # If chunk is too long, split further
                        logger.warning(f"Chunk too long ({len(chunk)} chars), splitting in translate_long_text...")
                        sub_chunks = [chunk[i:i + 4000] for i in range(0, len(chunk), 4000)]
                        for sub_chunk in sub_chunks:
                            if sub_chunk.strip():
                                try:
                                    result.append(self.translate_text(sub_chunk, src_lang, dest_lang))
                                except Exception as e2:
                                    logger.warning(f"Error translating sub-chunk: {e2}. Keeping original.")
                                    result.append(sub_chunk)
                    else:
                        logger.warning(f"Error translating chunk (len={len(chunk)}): {exc}. Keeping original.")
                        result.append(chunk)  # Keep original on error
            start += max_length
        
        return ''.join(result)
    
    def translate_batch(self, texts: list[str], src_lang: str, dest_lang: str) -> list[str]:
        """
        Translate multiple texts in parallel using ThreadPoolExecutor
        
        Args:
            texts: List of texts to translate
            src_lang: Source language code
            dest_lang: Destination language code
        
        Returns:
            List of translated texts
        """
        if not texts:
            return []
        
        # Đảm bảo alignment giữa input và output luôn khớp nhau
        # Sử dụng dictionary để map index -> text và index -> result
        results_map: dict[int, str] = {}
        
        # Track valid texts và their indices
        valid_texts_with_indices: list[tuple[int, str]] = []
        
        for i, text in enumerate(texts):
            if text is not None and isinstance(text, str) and text.strip():
                valid_texts_with_indices.append((i, text))
            else:
                # Với None/empty text, lưu trực tiếp vào results_map ngay lập tức
                results_map[i] = text if text is not None else ''
        
        # Submit tasks cho các valid texts
        futures_with_indices: list[tuple[int, concurrent.futures.Future]] = []
        
        for idx, text in valid_texts_with_indices:
            future = self.executor.submit(
                self.translate_text,
                text,
                src_lang,
                dest_lang
            )
            futures_with_indices.append((idx, future))
        
        # Collect results với đảm bảo alignment
        for idx, future in futures_with_indices:
            try:
                result = future.result(timeout=self.timeout)
                results_map[idx] = result if result is not None else ''
            except concurrent.futures.TimeoutError:
                logger.warning(f"Translation timeout for text at index {idx}, keeping original")
                original_text = texts[idx] if idx < len(texts) else ''
                results_map[idx] = original_text if original_text is not None else ''
            except Exception as e:
                logger.error(f"Translation failed for text at index {idx}: {e}, keeping original")
                original_text = texts[idx] if idx < len(texts) else ''
                results_map[idx] = original_text if original_text is not None else ''
        
        # Reconstruct results list theo đúng thứ tự index từ 0 đến len(texts)-1
        results = [results_map[i] for i in range(len(texts))]
        
        return results


# Global translation service instance (will be initialized in main)
_translation_service: Optional[TranslationService] = None


def get_translation_service() -> TranslationService:
    """Get or create global translation service instance"""
    global _translation_service
    if _translation_service is None:
        _translation_service = TranslationService()
    return _translation_service


def set_translation_service(service: TranslationService):
    """Set global translation service instance"""
    global _translation_service
    _translation_service = service
