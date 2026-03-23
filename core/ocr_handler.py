"""
OCR handler using Tesseract OCR
"""
import os
import sys
import platform
import zipfile
from typing import Optional
from PIL import Image
import pytesseract

from translation_app.config import config
from translation_app.utils.error_handler import OCRError
from translation_app.utils.logger import logger


class OCRHandler:
    """OCR handler for extracting text from images"""
    
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
    
    def get_ocr_language(self, src_lang: str) -> str:
        """
        Get OCR language code from source language code
        
        Args:
            src_lang: Source language code (can be 'auto' for auto-detect)
            
        Returns:
            OCR language code (defaults to 'eng' if auto-detect)
        """
        if src_lang.lower() == 'auto':
            # For auto-detect, use a combination of common project languages (JP, EN, VI, CN)
            # This allows Tesseract to detect multiple languages in the same image
            return 'jpn+eng+vie+chi_sim'
        return config.get_ocr_language(src_lang)
    
    def extract_text_from_image(self, image: Image.Image, lang: Optional[str] = None) -> str:
        """
        Extract text from image using OCR
        
        Args:
            image: PIL Image object
            lang: OCR language code (defaults to 'eng')
        
        Returns:
            Extracted text
        
        Raises:
            OCRError: If OCR fails
        """
        if not self.is_available:
            raise OCRError("Tesseract OCR is not installed or not available")
        
        if lang is None:
            lang = 'eng'
        
        try:
            # PRE-PROCESSING for better OCR accuracy
            # 1. Convert to grayscale (L)
            processed_img = image.convert('L')
            
            # 2. Upscale image (2x) to help with small text
            w, h = processed_img.size
            processed_img = processed_img.resize((w * 2, h * 2), Image.Resampling.LANCZOS)
            
            logger.info(f"Performing OCR with language: {lang}")
            
            # Extract text
            text = pytesseract.image_to_string(processed_img, lang=lang)
            return text
        except pytesseract.TesseractNotFoundError:
            raise OCRError("Tesseract OCR executable not found")
        except pytesseract.TesseractError as e:
            # Try with English if language-specific fails
            if lang != 'eng':
                try:
                    logger.warning(f"OCR failed with language {lang}, trying English: {e}")
                    text = pytesseract.image_to_string(image, lang='eng')
                    return text
                except Exception as e2:
                    raise OCRError(f"OCR failed with both {lang} and English: {e2}") from e2
            else:
                raise OCRError(f"OCR failed: {e}") from e
        except Exception as e:
            raise OCRError(f"Unexpected OCR error: {e}") from e
    
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

