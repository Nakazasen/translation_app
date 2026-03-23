"""Utility functions and helpers"""

def safe_import_config():
    """Safely import config with fallback"""
    try:
        from translation_app.config import config
    except ImportError:
        from .config import config
    return config

def safe_import_logger():
    """Safely import logger with fallback"""
    try:
        from translation_app.utils.logger import setup_logging, logger
    except ImportError:
        from .logger import setup_logging, logger
    return setup_logging, logger

