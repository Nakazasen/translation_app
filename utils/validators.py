"""
Input validation and security utilities
"""
import os
from pathlib import Path
from typing import Optional

from translation_app.config import config
from translation_app.utils.error_handler import ValidationError, FileNotFoundError, UnsupportedFileTypeError
from translation_app.utils.logger import logger


class FileValidator:
    """File validation utilities"""
    
    @staticmethod
    def validate_file_path(file_path: str) -> bool:
        """
        Validate file path for security (prevent path traversal)
        
        Args:
            file_path: Path to validate
        
        Returns:
            True if valid, False otherwise
        """
        if not file_path or not isinstance(file_path, str):
            return False
        
        try:
            # Normalize path
            normalized_path = os.path.normpath(file_path)
            
            # Check for path traversal attempts
            if '..' in normalized_path:
                logger.warning(f"Path traversal attempt detected: {file_path}")
                return False
            
            # Check if path is absolute and within reasonable bounds
            if os.path.isabs(normalized_path):
                # On Windows, check if it's a valid drive path
                if os.name == 'nt':
                    if len(normalized_path) > 260:  # Windows MAX_PATH
                        logger.warning(f"Path too long: {file_path}")
                        return False
                else:
                    # On Unix, check for root directory access attempts
                    if normalized_path.startswith('/etc') or normalized_path.startswith('/sys'):
                        logger.warning(f"Restricted path access attempt: {file_path}")
                        return False
            
            return True
        except Exception as e:
            logger.error(f"Error validating file path: {e}")
            return False
    
    @staticmethod
    def validate_file_extension(file_path: str) -> bool:
        """
        Validate file extension against allowed extensions
        
        Args:
            file_path: Path to validate
        
        Returns:
            True if extension is allowed
        """
        if not file_path:
            return False
        
        _, ext = os.path.splitext(file_path.lower())
        return ext in config.allowed_extensions
    
    @staticmethod
    def validate_file_exists(file_path: str) -> bool:
        """
        Check if file exists
        
        Args:
            file_path: Path to check
        
        Returns:
            True if file exists
        """
        if not file_path:
            return False
        
        return os.path.exists(file_path) and os.path.isfile(file_path)
    
    @staticmethod
    def validate_file_size(file_path: str) -> bool:
        """
        Validate file size against maximum limit
        
        Args:
            file_path: Path to validate
        
        Returns:
            True if file size is within limit
        """
        if not file_path or not os.path.exists(file_path):
            return False
        
        try:
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            return file_size_mb <= config.max_file_size_mb
        except Exception as e:
            logger.error(f"Error checking file size: {e}")
            return False
    
    @staticmethod
    def validate_file_content(file_path: str) -> bool:
        """
        Validate file content using MIME type (optional, requires python-magic)
        Falls back to extension check if python-magic is not available
        
        Args:
            file_path: Path to validate
        
        Returns:
            True if file content is valid
        """
        if not file_path or not os.path.exists(file_path):
            return False
        
        # Try to use python-magic if available
        try:
            import magic
            mime = magic.from_file(file_path, mime=True)
            
            allowed_mimes = {
                'application/vnd.openxmlformats-officedocument',
                'application/vnd.ms-excel',
                'application/vnd.ms-powerpoint',
                'application/msword',
                'application/pdf',
                'text/plain',
                'image/png',
                'image/jpeg',
                'image/jpg',
                'image/gif',
                'image/bmp',
                'image/tiff',
                'image/webp'
            }
            
            return any(mime.startswith(allowed) for allowed in allowed_mimes)
        except ImportError:
            # Fallback to extension validation if python-magic is not available
            logger.debug("python-magic not available, using extension validation")
            return FileValidator.validate_file_extension(file_path)
        except Exception as e:
            logger.warning(f"Error validating file content: {e}, falling back to extension check")
            return FileValidator.validate_file_extension(file_path)
    
    @staticmethod
    def validate_file(file_path: str, check_content: bool = False) -> None:
        """
        Comprehensive file validation
        
        Args:
            file_path: Path to validate
            check_content: Whether to validate file content (MIME type)
        
        Raises:
            ValidationError: If validation fails
            FileNotFoundError: If file doesn't exist
            UnsupportedFileTypeError: If file type is not supported
        """
        if not file_path:
            raise ValidationError("Đường dẫn file không được để trống")
        
        # Validate path security
        if not FileValidator.validate_file_path(file_path):
            raise ValidationError(f"Đường dẫn file không hợp lệ: {file_path}")
        
        # Check if file exists
        if not FileValidator.validate_file_exists(file_path):
            raise FileNotFoundError(f"File không tồn tại: {file_path}")
        
        # Validate extension
        if not FileValidator.validate_file_extension(file_path):
            raise UnsupportedFileTypeError(
                f"Loại file không được hỗ trợ: {file_path}\n"
                f"Các định dạng được hỗ trợ: {', '.join(config.allowed_extensions)}"
            )
        
        # Validate file size
        if not FileValidator.validate_file_size(file_path):
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            raise ValidationError(
                f"File quá lớn ({file_size_mb:.1f}MB). "
                f"Kích thước tối đa: {config.max_file_size_mb}MB"
            )
        
        # Validate content if requested
        if check_content:
            if not FileValidator.validate_file_content(file_path):
                raise ValidationError(f"Nội dung file không hợp lệ: {file_path}")


class LanguageValidator:
    """Language validation utilities"""
    
    @staticmethod
    def validate_language_code(lang_code: str) -> bool:
        """
        Validate language code
        
        Args:
            lang_code: Language code to validate
        
        Returns:
            True if language is supported
        """
        if not lang_code:
            return False
        
        return config.is_language_supported(lang_code)
    
    @staticmethod
    def validate_language_pair(src_lang: str, dest_lang: str) -> None:
        """
        Validate language pair for translation
        
        Args:
            src_lang: Source language code (can be 'auto' for auto-detect)
            dest_lang: Destination language code
            
        Raises:
            ValidationError: If validation fails
        """
        if not src_lang:
            raise ValidationError("Ngôn ngữ nguồn không được để trống")
        
        if not dest_lang:
            raise ValidationError("Ngôn ngữ đích không được để trống")
        
        # Allow auto-detect as source language
        if src_lang.lower() == 'auto':
            if dest_lang.lower() == 'auto':
                raise ValidationError("Không thể dùng 'Tự động phát hiện' cho cả ngôn ngữ nguồn và đích")
            # Skip validation for auto-detect source
            if not LanguageValidator.validate_language_code(dest_lang):
                raise ValidationError(f"Ngôn ngữ đích không được hỗ trợ: {dest_lang}")
            return
        
        if not LanguageValidator.validate_language_code(src_lang):
            raise ValidationError(f"Ngôn ngữ nguồn không được hỗ trợ: {src_lang}")
        
        if not LanguageValidator.validate_language_code(dest_lang):
            raise ValidationError(f"Ngôn ngữ đích không được hỗ trợ: {dest_lang}")
        
        if src_lang == dest_lang:
            raise ValidationError("Ngôn ngữ nguồn và đích không được giống nhau")

