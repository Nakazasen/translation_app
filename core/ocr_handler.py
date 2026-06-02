"""
OCR handler using Tesseract OCR
"""
import os
import sys
import platform
import zipfile
from dataclasses import dataclass
from typing import Optional
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract

from translation_app.config import config
from translation_app.utils.error_handler import OCRError
from translation_app.utils.logger import logger


@dataclass
class OCRExtractResult:
    """Structured OCR result with lightweight metadata for UI decisions."""

    text: str
    strategy_used: str
    attempted_strategies: list[str]
    used_subtitle_crop: bool


class OCRHandler:
    """OCR handler for extracting text from images"""

    SUBTITLE_CROP_RATIOS = (0.4, 0.35, 0.45)

    def __init__(self):
        """Initialize OCR handler and setup Tesseract"""
        self.tesseract_path: Optional[str] = None
        self.is_available: bool = False
        self._setup_tesseract()

    def _extract_tesseract_from_bundle(self) -> Optional[str]:
        """
        Extract Tesseract OCR from onefile bundle if needed

        Returns:
            Path to tesseract.exe if extracted, None otherwise
        """
        if platform.system() != 'Windows':
            return None

        # Target path for extraction (shared across programs)
        localappdata = os.getenv('LOCALAPPDATA', '')
        if not localappdata:
            return None

        tesseract_dir = os.path.join(localappdata, 'Tesseract-OCR')
        tesseract_exe = os.path.join(tesseract_dir, 'tesseract.exe')

        # If Tesseract already exists at this location and works, no need to extract
        if os.path.exists(tesseract_exe):
            try:
                pytesseract.pytesseract.tesseract_cmd = tesseract_exe
                pytesseract.get_tesseract_version()
                return tesseract_exe
            except Exception as e:
                logger.debug(f"Tesseract at {tesseract_exe} not working: {e}")

        # Check if running from onefile
        bundle_dir = None
        if getattr(sys, 'frozen', False):
            # Running from executable
            if hasattr(sys, '_MEIPASS'):
                # PyInstaller onefile - file data extracted to _MEIPASS
                bundle_dir = sys._MEIPASS
            else:
                bundle_dir = os.path.dirname(sys.executable)
        else:
            # Running from Python script
            bundle_dir = os.path.dirname(os.path.abspath(__file__))

        if not bundle_dir:
            return None

        # Check if Tesseract zip exists in bundle
        tesseract_zip = os.path.join(bundle_dir, 'tesseract.zip')
        if not os.path.exists(tesseract_zip):
            return None

        try:
            # Create target directory if not exists
            os.makedirs(tesseract_dir, exist_ok=True)

            # Extract Tesseract OCR
            logger.info("Extracting Tesseract OCR from bundle...")
            with zipfile.ZipFile(tesseract_zip, 'r') as zip_ref:
                zip_ref.extractall(tesseract_dir)

            # Verify after extraction
            if os.path.exists(tesseract_exe):
                pytesseract.pytesseract.tesseract_cmd = tesseract_exe
                pytesseract.get_tesseract_version()
                logger.info(f"Successfully extracted Tesseract OCR to: {tesseract_dir}")
                return tesseract_exe
        except Exception as e:
            logger.error(f"Error extracting Tesseract OCR: {e}")

        return None

    def _setup_tesseract(self) -> None:
        """Setup and configure Tesseract OCR"""
        try:
            if platform.system() == 'Windows':
                # Try extracting from bundle first (if running from onefile)
                extracted_path = self._extract_tesseract_from_bundle()

                # Try common Windows paths
                possible_paths = [extracted_path] + config.tesseract_paths

                # Remove None from list
                possible_paths = [p for p in possible_paths if p and os.path.exists(p)]

                # Check if tesseract is in PATH
                try:
                    pytesseract.get_tesseract_version()
                    self.is_available = True
                    logger.info("Tesseract OCR found in PATH")
                    return
                except Exception:
                    # If not in PATH, try the paths above
                    tesseract_found = False
                    for path in possible_paths:
                        if os.path.exists(path):
                            pytesseract.pytesseract.tesseract_cmd = path
                            try:
                                # Test if it works
                                pytesseract.get_tesseract_version()
                                self.tesseract_path = path
                                self.is_available = True
                                tesseract_found = True
                                logger.info(f"Found Tesseract at: {path}")
                                break
                            except Exception as e:
                                logger.debug(f"Tesseract at {path} not working: {e}")
                                continue

                    if not tesseract_found:
                        logger.warning("Tesseract OCR not found. Please install or add to PATH.")
                        self.is_available = False
            else:
                # Non-Windows: try to use system tesseract
                try:
                    pytesseract.get_tesseract_version()
                    self.is_available = True
                    logger.info("Tesseract OCR found in PATH")
                except Exception as e:
                    logger.warning(f"Tesseract OCR not found: {e}")
                    self.is_available = False
        except Exception as e:
            logger.error(f"Error setting up Tesseract: {e}")
            self.is_available = False

    def is_installed(self) -> bool:
        """
        Check if Tesseract OCR is installed and available

        Returns:
            True if Tesseract is available
        """
        return self.is_available

    def get_installed_languages(self) -> list[str]:
        """
        Get list of installed OCR languages

        Returns:
            List of installed language codes
        """
        if not self.is_available:
            return []
        try:
            return pytesseract.get_languages()
        except Exception as e:
            logger.warning(f"Failed to get installed OCR languages: {e}")
            return ['eng']

    def get_ocr_language(self, src_lang: str) -> str:
        """
        Get OCR language code from source language code

        Args:
            src_lang: Source language code (can be 'auto' for auto-detect)

        Returns:
            OCR language code (defaults to 'eng' if auto-detect)

        Raises:
            OCRError: If the requested language pack is not installed in Tesseract
        """
        installed = self.get_installed_languages()
        if not installed:
            installed = ['eng']

        if src_lang.lower() == 'auto':
            # For auto-detect, use a combination of common project languages (JP, EN, VI, CN)
            # but ONLY filter to ones that are actually installed on the system!
            candidates = ['jpn', 'eng', 'vie', 'chi_sim']
            available_candidates = [c for c in candidates if c in installed]
            if not available_candidates:
                return 'eng'
            return '+'.join(available_candidates)

        requested = config.get_ocr_language(src_lang)
        # Verify requested languages are installed. If a non-English requested part is missing,
        # raise a clean OCRError so the UI can notify the user.
        req_parts = requested.split('+')
        missing_parts = [p for p in req_parts if p not in installed]
        if missing_parts:
            non_eng_missing = [p for p in missing_parts if p != 'eng']
            if non_eng_missing:
                raise OCRError(
                    f"Gói ngôn ngữ OCR '{non_eng_missing[0]}' chưa được cài đặt trong Tesseract!\n\n"
                    f"Để quét được ngôn ngữ này, vui lòng:\n"
                    f"1. Tải file '{non_eng_missing[0]}.traineddata' từ GitHub:\n"
                    f"   https://github.com/tesseract-ocr/tessdata\n"
                    f"2. Sao chép/di chuyển file đó vào thư mục tessdata:\n"
                    f"   C:\\Program Files\\Tesseract-OCR\\tessdata\n"
                    f"3. Khởi động lại ứng dụng và thử lại."
                )
        return requested

    def _contains_japanese_script(self, text: str) -> bool:
        """
        Check whether text contains Japanese script characters.

        Args:
            text: OCR output text.

        Returns:
            True if Hiragana, Katakana, or CJK characters are present.
        """
        return any(
            '\u3040' <= char <= '\u30ff' or '\u4e00' <= char <= '\u9fff'
            for char in text
        )

    def _looks_like_latin_garbage(self, text: str) -> bool:
        """
        Detect OCR output that is likely Latin garbage.

        Args:
            text: OCR output text.

        Returns:
            True when text has enough ASCII fragments but too little readable content.
        """
        stripped_text = text.strip()
        if not stripped_text:
            return False

        chars = [char for char in stripped_text if not char.isspace()]
        if len(chars) < 8:
            return False

        ascii_chars = [char for char in chars if ord(char) < 128]
        alpha_chars = [char for char in chars if char.isalpha()]
        symbol_chars = [char for char in chars if not char.isalnum()]
        short_words = [word for word in stripped_text.split() if 1 <= len(word) <= 2]

        ascii_ratio = len(ascii_chars) / len(chars)
        symbol_ratio = len(symbol_chars) / len(chars)
        short_word_ratio = len(short_words) / max(len(stripped_text.split()), 1)

        return (
            ascii_ratio > 0.85
            and len(alpha_chars) >= 6
            and (symbol_ratio > 0.25 or short_word_ratio > 0.45)
        )

    def validate_ocr_text_quality(self, text: str, lang: str) -> None:
        """
        Validate OCR text quality for high-risk auto language combinations.

        Args:
            text: OCR output text.
            lang: Tesseract language expression used for OCR.

        Raises:
            OCRError: If the OCR output is likely garbage.
        """
        if 'jpn' not in lang:
            return
        if self._contains_japanese_script(text):
            return
        if self._looks_like_latin_garbage(text):
            raise OCRError(
                "OCR có thể đã nhận dạng sai ngôn ngữ và tạo ra ký tự Latin vô nghĩa.\n\n"
                "Vui lòng chọn rõ ngôn ngữ nguồn là Tiếng Nhật, kiểm tra gói jpn.traineddata "
                "trong Tesseract, hoặc dùng ảnh rõ nét hơn."
            )

    def check_ocr_quality(self, text: str, src_lang: str, dest_lang: str) -> dict:
        """
        Check OCR text quality for high-risk issues.

        Args:
            text: Extracted OCR text.
            src_lang: Source language chosen by user (e.g. 'auto' or 'ja').
            dest_lang: Destination language.

        Returns:
            Dict containing quality details:
            - 'is_low_quality': bool
            - 'reason': str
            - 'missing_jpn_pack': bool
        """
        installed = self.get_installed_languages()
        if not installed:
            installed = ['eng']

        src_lower = src_lang.lower()
        is_japanese_context = src_lower in ('auto', 'ja', 'jpn', 'japanese')

        # 1. Check if jpn pack is missing in Japanese/Auto context
        if is_japanese_context and 'jpn' not in installed:
            return {
                'is_low_quality': True,
                'reason': "Thiếu gói OCR tiếng Nhật jpn.traineddata.",
                'missing_jpn_pack': True
            }

        stripped = text.strip()

        # 2. Check if text is too short
        if stripped and len(stripped) < 10:
            return {
                'is_low_quality': True,
                'reason': "Văn bản nhận diện quá ngắn (dưới 10 ký tự).",
                'missing_jpn_pack': False
            }

        # 3. Check for symbol ratio > 30%
        if stripped:
            chars = [c for c in stripped if not c.isspace()]
            if chars:
                symbol_chars = [c for c in chars if not c.isalnum()]
                symbol_ratio = len(symbol_chars) / len(chars)
                if symbol_ratio > 0.3:
                    return {
                        'is_low_quality': True,
                        'reason': f"Tỷ lệ ký tự đặc biệt/ký hiệu quá cao ({symbol_ratio:.1%}).",
                        'missing_jpn_pack': False
                    }

        # 4. Check for no Japanese characters in Japanese/Auto context
        if is_japanese_context and not self._contains_japanese_script(text):
            metadata_keywords = {'metadata', 'filename', 'resolution', 'dpi', 'tesseract', 'listening', 'practice', 'n3', 'n2'}
            words = [w.strip('.,:;!?()[]{}*\'\"').lower() for w in text.split()]
            found_kws = [w for w in words if w in metadata_keywords]

            if found_kws:
                return {
                    'is_low_quality': True,
                    'reason': f"Phát hiện các từ khóa/metadata Latin ({', '.join(found_kws)}) nhưng không tìm thấy chữ tiếng Nhật.",
                    'missing_jpn_pack': False
                }

            return {
                'is_low_quality': True,
                'reason': "Không tìm thấy ký tự tiếng Nhật (Hiragana/Katakana/Kanji) nào trong văn bản nhận diện.",
                'missing_jpn_pack': False
            }

        return {
            'is_low_quality': False,
            'reason': "",
            'missing_jpn_pack': False
        }

    def _preprocess_image(
        self,
        image: Image.Image,
        upscale_factor: int = 2,
        apply_contrast: bool = True,
        apply_sharpen: bool = True,
    ) -> Image.Image:
        """Prepare an image for OCR without mutating the original input."""
        processed_img = image.convert('L')

        if upscale_factor > 1:
            width, height = processed_img.size
            processed_img = processed_img.resize(
                (max(1, width * upscale_factor), max(1, height * upscale_factor)),
                Image.Resampling.LANCZOS,
            )

        if apply_contrast:
            processed_img = ImageEnhance.Contrast(processed_img).enhance(1.6)

        if apply_sharpen:
            processed_img = processed_img.filter(ImageFilter.SHARPEN)

        return processed_img

    def _get_bottom_crop(self, image: Image.Image, crop_ratio: float) -> Image.Image:
        """Return the bottom crop used for subtitle-heavy screenshots."""
        width, height = image.size
        crop_ratio = min(max(crop_ratio, 0.1), 0.9)
        top = max(0, int(height * (1 - crop_ratio)))
        return image.crop((0, top, width, height))

    def _ocr_with_processed_image(self, image: Image.Image, lang: str, strategy_name: str) -> str:
        """Run Tesseract OCR for a single prepared image variant."""
        logger.info(f"Performing OCR with strategy={strategy_name}, language={lang}")
        return pytesseract.image_to_string(image, lang=lang)

    def _build_ocr_attempts(self, image: Image.Image, mode: str) -> list[tuple[str, Image.Image]]:
        """Build OCR attempts ordered from general to subtitle-specific fallbacks."""
        safe_mode = (mode or 'auto').lower()
        attempts: list[tuple[str, Image.Image]] = []

        if safe_mode == 'subtitle':
            attempts.append(('subtitle_full_3x', self._preprocess_image(image, upscale_factor=3)))
            attempts.append(
                (
                    'subtitle_bottom_40_3x',
                    self._preprocess_image(self._get_bottom_crop(image, 0.4), upscale_factor=3),
                )
            )
            attempts.append(
                (
                    'subtitle_bottom_35_3x',
                    self._preprocess_image(self._get_bottom_crop(image, 0.35), upscale_factor=3),
                )
            )
            return attempts

        attempts.append(('full_image_2x', self._preprocess_image(image, upscale_factor=2)))
        if safe_mode == 'document':
            attempts.append(('full_image_3x', self._preprocess_image(image, upscale_factor=3)))
            return attempts

        attempts.append(('full_image_3x', self._preprocess_image(image, upscale_factor=3)))
        for crop_ratio in self.SUBTITLE_CROP_RATIOS:
            label = int(crop_ratio * 100)
            attempts.append(
                (
                    f'bottom_{label}_3x',
                    self._preprocess_image(self._get_bottom_crop(image, crop_ratio), upscale_factor=3),
                )
            )
        return attempts

    def extract_text_with_metadata(
        self,
        image: Image.Image,
        lang: Optional[str] = None,
        mode: str = 'auto',
    ) -> OCRExtractResult:
        """Extract OCR text using multiple preprocessing strategies and return metadata."""
        if not self.is_available:
            raise OCRError("Tesseract OCR is not installed or not available")

        if lang is None:
            lang = 'eng'

        try:
            attempts = self._build_ocr_attempts(image, mode)
            attempted_names: list[str] = []
            fallback_result: Optional[OCRExtractResult] = None

            for strategy_name, candidate_image in attempts:
                attempted_names.append(strategy_name)
                text = self._ocr_with_processed_image(candidate_image, lang, strategy_name)
                stripped = text.strip()
                if not stripped:
                    continue

                used_subtitle_crop = strategy_name.startswith('bottom_') or strategy_name.startswith('subtitle_bottom_')
                result = OCRExtractResult(
                    text=text,
                    strategy_used=strategy_name,
                    attempted_strategies=list(attempted_names),
                    used_subtitle_crop=used_subtitle_crop,
                )

                if used_subtitle_crop:
                    return result

                fallback_result = result

            if fallback_result is not None:
                return fallback_result

            return OCRExtractResult(
                text='',
                strategy_used='none',
                attempted_strategies=attempted_names,
                used_subtitle_crop=False,
            )
        except pytesseract.TesseractNotFoundError:
            raise OCRError("Tesseract OCR executable not found")
        except pytesseract.TesseractError as e:
            if lang != 'eng':
                try:
                    logger.warning(f"OCR failed with language {lang}, trying English: {e}")
                    fallback = self.extract_text_with_metadata(image, lang='eng', mode=mode)
                    return fallback
                except Exception as e2:
                    raise OCRError(f"OCR failed with both {lang} and English: {e2}") from e2
            raise OCRError(f"OCR failed: {e}") from e
        except Exception as e:
            raise OCRError(f"Unexpected OCR error: {e}") from e

    def extract_text_from_image(self, image: Image.Image, lang: Optional[str] = None, mode: str = 'auto') -> str:
        """
        Extract text from image using OCR.

        Args:
            image: PIL Image object
            lang: OCR language code (defaults to 'eng')
            mode: OCR mode hint ('auto', 'document', 'subtitle')

        Returns:
            Extracted text

        Raises:
            OCRError: If OCR fails
        """
        result = self.extract_text_with_metadata(image, lang=lang, mode=mode)
        return result.text

    def is_text_clear(self, text: str) -> bool:
        """
        Check if OCR text is clear and readable

        Args:
            text: Text to check

        Returns:
            True if text is clear
        """
        if not text or not text.strip():
            return False

        text = text.strip()

        # Remove special characters and whitespace
        clean_text = ''.join(c for c in text if c.isalnum() or c.isspace())

        # Text must have at least 3 alphanumeric characters to be considered clear
        if len(clean_text) < 3:
            return False

        # Check ratio of valid characters (at least 30% should be alphanumeric)
        valid_chars = sum(1 for c in text if c.isalnum())
        if len(text) > 0 and valid_chars / len(text) < 0.3:
            return False

        return True


# Global OCR handler instance
_ocr_handler: Optional[OCRHandler] = None


def get_ocr_handler() -> OCRHandler:
    """Get or create global OCR handler instance"""
    global _ocr_handler
    if _ocr_handler is None:
        _ocr_handler = OCRHandler()
    return _ocr_handler
