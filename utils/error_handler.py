"""
Custom exceptions and error handling utilities
"""
from typing import Optional


class TranslationError(Exception):
    """Base exception for translation operations"""
    
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.message = message
        self.original_error = original_error
    
    def __str__(self):
        if self.original_error:
            return f"{self.message} (Original error: {self.original_error})"
        return self.message


class FileProcessingError(TranslationError):
    """File processing specific errors"""
    pass


class TranslationServiceError(TranslationError):
    """Translation service errors (API failures, timeouts, etc.)"""
    pass


class OCRError(TranslationError):
    """OCR processing errors"""
    pass


class EmailError(TranslationError):
    """Email processing errors"""
    pass


class ValidationError(TranslationError):
    """Input validation errors"""
    pass


class FileNotFoundError(TranslationError):
    """File not found errors"""
    pass


class UnsupportedFileTypeError(FileProcessingError):
    """Unsupported file type errors"""
    pass


def handle_translation_error(error: Exception, context: str = "") -> str:
    """
    Convert exceptions to user-friendly error messages
    
    Args:
        error: The exception that occurred
        context: Additional context about where the error occurred
    
    Returns:
        User-friendly error message
    """
    if isinstance(error, TranslationError):
        return f"{context}: {error.message}" if context else error.message
    
    # Handle specific exception types
    error_type = type(error).__name__
    error_msg = str(error)
    
    # Common error patterns
    if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
        return f"{context}: Quá trình dịch mất quá nhiều thời gian. Vui lòng thử lại." if context else "Quá trình dịch mất quá nhiều thời gian. Vui lòng thử lại."
    
    if "network" in error_msg.lower() or "connection" in error_msg.lower():
        return f"{context}: Lỗi kết nối mạng. Vui lòng kiểm tra kết nối internet." if context else "Lỗi kết nối mạng. Vui lòng kiểm tra kết nối internet."
    
    if "permission" in error_msg.lower() or "access denied" in error_msg.lower():
        return f"{context}: Không có quyền truy cập file. Vui lòng kiểm tra quyền truy cập." if context else "Không có quyền truy cập file. Vui lòng kiểm tra quyền truy cập."
    
    if "file not found" in error_msg.lower() or "no such file" in error_msg.lower():
        return f"{context}: Không tìm thấy file. Vui lòng kiểm tra đường dẫn." if context else "Không tìm thấy file. Vui lòng kiểm tra đường dẫn."
    
    # Generic error message
    return f"{context}: {error_type}: {error_msg}" if context else f"{error_type}: {error_msg}"

