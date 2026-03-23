"""
Configuration management for translation application
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import os
import sys


@dataclass
class AppConfig:
    """Application configuration"""
    
    # Supported languages mapping (using Google Translate API format)
    supported_languages: Dict[str, str] = field(default_factory=lambda: {
        'auto': 'Auto-detect (Tự động phát hiện)',
        'en': 'English',
        'ja': 'Japanese',
        'vi': 'Vietnamese',
        'zh': 'Chinese (Simplified)',
        'zh-CN': 'Chinese (Simplified)',
        'zh-TW': 'Chinese (Traditional)',
        # Backward compatibility
        'zh-cn': 'Chinese (Simplified)',
        'zh-tw': 'Chinese (Traditional)'
    })
    
    # File size limits (in MB)
    max_file_size_mb: int = 100
    warning_file_size_mb: int = 30
    
    # Translation settings
    translation_timeout: int = 30  # seconds
    max_text_length: int = 4500  # Max characters per translation chunk
    max_workers: int = 4  # ThreadPoolExecutor workers
    
    # Tesseract OCR paths (Windows)
    tesseract_paths: List[str] = field(default_factory=lambda: [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    ])
    
    # Translation service
    translation_service: str = "google"  # Currently only Google Translate
    
    # Allowed file extensions - stored as lowercase for case-insensitive comparison
    allowed_extensions: set = field(default_factory=lambda: {
        '.xlsx', '.xls',  # Excel
        '.docx', '.doc',  # Word
        '.pptx', '.ppt',  # PowerPoint
        '.txt',           # Text
        '.pdf',           # PDF
        '.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp'  # Images
    })
    
    def is_extension_allowed(self, file_path: str) -> bool:
        """Check if file extension is allowed (case-insensitive)"""
        _, ext = os.path.splitext(file_path)
        return ext.lower() in self.allowed_extensions
    
    # OCR language mapping
    ocr_language_map: Dict[str, str] = field(default_factory=lambda: {
        'ja': 'jpn+eng',      # Japanese + English
        'en': 'eng',          # English
        'vi': 'vie+eng',      # Vietnamese + English
        'zh': 'chi_sim+eng',  # Chinese Simplified + English
        'zh-CN': 'chi_sim+eng',
        'zh-TW': 'chi_tra+eng',  # Chinese Traditional + English
        # Backward compatibility
        'zh-cn': 'chi_sim+eng',
        'zh-tw': 'chi_tra+eng',
    })
    
    # Default languages
    default_src_lang: str = "auto"
    default_dest_lang: str = "vi"
    
    # Email settings
    max_emails_to_translate: int = 3
    
    # Logging
    log_level: str = "INFO"
    log_dir: str = "logs"
    log_max_bytes: int = 10 * 1024 * 1024  # 10MB
    log_backup_count: int = 5
    
    # Auto Update Configuration
    update_folders: List[str] = field(default_factory=lambda: [
        r"\\fstvn01\Data\10_Production Engineering Department(製造技術部)\02.製造技術課\PE Dept\15. FORM（BIEU MAU）-形式\Form_VBA\Form_phanmemdichfiletudong",
        r"\\fstvn01.kdtvn.local\Data\00_KDTVN Common(KDTVN共通)\⑤Production Engineering(製造技術)\vinh\Autotranslator"
    ])
    update_file_pattern: str = "DichTuDong_ver*.exe"
    
    def __post_init__(self):
        """Load configuration from environment variables if available"""
        # Override with environment variables
        if os.getenv('TRANSLATION_MAX_WORKERS'):
            self.max_workers = int(os.getenv('TRANSLATION_MAX_WORKERS'))
        
        if os.getenv('TRANSLATION_TIMEOUT'):
            self.translation_timeout = int(os.getenv('TRANSLATION_TIMEOUT'))
        
        if os.getenv('LOG_LEVEL'):
            self.log_level = os.getenv('LOG_LEVEL')
        
        # Add user-specific Tesseract paths
        username = os.getenv('USERNAME', '')
        if username:
            user_paths = [
                rf'C:\Users\{username}\AppData\Local\Programs\Tesseract-OCR\tesseract.exe',
                rf'C:\Users\{username}\AppData\Local\Tesseract-OCR\tesseract.exe',
                os.path.join(os.getenv('LOCALAPPDATA', ''), r'Programs\Tesseract-OCR\tesseract.exe'),
                os.path.join(os.getenv('LOCALAPPDATA', ''), r'Tesseract-OCR\tesseract.exe'),
            ]
            # Add to tesseract_paths if not already present
            for path in user_paths:
                if path and path not in self.tesseract_paths:
                    self.tesseract_paths.append(path)
        
        # Add relative path for portable usage (Tesseract-OCR folder next to exe)
        exe_dir = os.path.dirname(sys.executable)
        portable_paths = [
            os.path.join(exe_dir, "OCR", "tesseract.exe"),
            os.path.join(exe_dir, "Tesseract-OCR", "tesseract.exe"),
            os.path.join(exe_dir, "tesseract", "tesseract.exe"),
            os.path.join(os.getcwd(), "OCR", "tesseract.exe"),
            os.path.join(os.getcwd(), "Tesseract-OCR", "tesseract.exe")
        ]
        for path in portable_paths:
            if path not in self.tesseract_paths:
                self.tesseract_paths.insert(0, path) # Priority to portable path
    
    def get_ocr_language(self, src_lang: str) -> str:
        """Get OCR language code from source language code"""
        return self.ocr_language_map.get(src_lang.lower(), 'eng')

    def normalize_language_code(self, lang_code: str) -> str:
        """
        Normalize language code to Google Translate API format

        Args:
            lang_code: Input language code (can be 'auto' for auto-detect)

        Returns:
            Normalized language code
        """
        if not lang_code:
            return lang_code

        lang_lower = lang_code.lower()
        
        # Keep 'auto' as-is for auto-detect
        if lang_lower == 'auto':
            return 'auto'

        # Map common variations to Google Translate format
        normalization_map = {
            'zh': 'zh-CN',      # Generic Chinese -> Simplified Chinese (default)
            'zh-cn': 'zh-CN',
            'zh-tw': 'zh-TW',
            'zh_cn': 'zh-CN',
            'zh_tw': 'zh-TW',
        }

        return normalization_map.get(lang_lower, lang_code)
    
    def is_language_supported(self, lang_code: str) -> bool:
        """Check if language code is supported"""
        return lang_code.lower() in self.supported_languages
    
    def validate_file_extension(self, file_path: str) -> bool:
        """Validate file extension"""
        _, ext = os.path.splitext(file_path.lower())
        return ext in self.allowed_extensions


# Global configuration instance
config = AppConfig()

