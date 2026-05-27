"""
Logging system for translation application
"""
import logging
import logging.handlers
import os
from pathlib import Path
import sys
import threading
from typing import Optional

from translation_app.config import config


_LOGGER_LOCK = threading.RLock()
_LOGGER_NAME = "translation_app"


def _get_console_stream():
    """Return a console stream that won't fail on unencodable Unicode."""
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    return stream


class WindowsSafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Rotating file handler that degrades gracefully when rollover is locked on Windows."""

    def __init__(self, filename, *args, **kwargs):
        kwargs.setdefault("encoding", "utf-8")
        kwargs.setdefault("delay", True)
        try:
            super().__init__(filename, *args, errors="replace", **kwargs)
        except TypeError:
            super().__init__(filename, *args, **kwargs)

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            self._recover_after_rollover_lock()
        except OSError as exc:
            if os.name == "nt" and getattr(exc, "winerror", None) == 32:
                self._recover_after_rollover_lock()
            else:
                raise

    def emit(self, record):
        try:
            super().emit(record)
        except PermissionError:
            self._recover_after_rollover_lock()
        except OSError as exc:
            if os.name == "nt" and getattr(exc, "winerror", None) == 32:
                self._recover_after_rollover_lock()
            else:
                raise

    def _recover_after_rollover_lock(self):
        """Close the current stream and continue without crashing or stderr spam."""
        try:
            if self.stream:
                self.stream.close()
        except Exception:
            pass
        self.stream = None


def _close_handler(handler: logging.Handler) -> None:
    try:
        handler.flush()
    except Exception:
        pass
    try:
        handler.close()
    except Exception:
        pass


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

    with _LOGGER_LOCK:
        # Create log directory
        log_dir = Path(config.log_dir)
        log_dir.mkdir(exist_ok=True)

        # Create logger
        logger = logging.getLogger(_LOGGER_NAME)
        logger.setLevel(getattr(logging, str(log_level).upper(), logging.INFO))

        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        log_file = log_dir / 'translation_app.log'
        expected_log_path = str(log_file.resolve())

        file_handler = None
        console_handler = None
        stale_handlers = []

        for handler in list(logger.handlers):
            if isinstance(handler, WindowsSafeRotatingFileHandler):
                handler_path = str(Path(handler.baseFilename).resolve())
                if file_handler is None and handler_path == expected_log_path:
                    file_handler = handler
                else:
                    stale_handlers.append(handler)
            elif isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                if console_handler is None:
                    console_handler = handler
                else:
                    stale_handlers.append(handler)
            else:
                stale_handlers.append(handler)

        for handler in stale_handlers:
            logger.removeHandler(handler)
            _close_handler(handler)

        if file_handler is None:
            file_handler = WindowsSafeRotatingFileHandler(
                log_file,
                maxBytes=config.log_max_bytes,
                backupCount=config.log_backup_count,
            )
            logger.addHandler(file_handler)

        if console_handler is None:
            console_handler = logging.StreamHandler(_get_console_stream())
            logger.addHandler(console_handler)

        file_handler.setLevel(logger.level)
        console_handler.setLevel(logger.level)
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Prevent propagation to root logger
        logger.propagate = False

        logger.info(f"Logging initialized. Level: {log_level}, Log file: {log_file}")

        return logger


# Create default logger instance
logger = setup_logging()

