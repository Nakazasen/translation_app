"""
Logging system for translation application
"""
import logging
import logging.handlers
from pathlib import Path
import sys
from typing import Optional

from translation_app.config import config


def setup_logging(log_level: Optional[str] = None) -> logging.Logger:
    """
    Setup comprehensive logging system with file rotation
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
                  If None, uses config.log_level
    
    Returns:
        Configured logger instance
    """
    # Use config log level if not provided
    if log_level is None:
        log_level = config.log_level
    
    # Create log directory
    log_dir = Path(config.log_dir)
    log_dir.mkdir(exist_ok=True)
    
    # Create logger
    logger = logging.getLogger('translation_app')
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # File handler with rotation
    log_file = log_dir / 'translation_app.log'
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backup_count,
        encoding='utf-8'
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Prevent propagation to root logger
    logger.propagate = False
    
    logger.info(f"Logging initialized. Level: {log_level}, Log file: {log_file}")
    
    return logger


# Create default logger instance
logger = setup_logging()

