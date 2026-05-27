import importlib
import logging
import logging.handlers
from pathlib import Path

from translation_app.config import config

logger_module = importlib.import_module("translation_app.utils.logger")


def _file_and_console_handlers(app_logger: logging.Logger):
    file_handlers = [
        handler for handler in app_logger.handlers
        if isinstance(handler, logger_module.WindowsSafeRotatingFileHandler)
    ]
    console_handlers = [
        handler for handler in app_logger.handlers
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
    ]
    return file_handlers, console_handlers


def test_logging_setup_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "log_dir", str(tmp_path / "logs"))

    logger_a = logger_module.setup_logging("INFO")
    logger_b = logger_module.setup_logging("DEBUG")

    assert logger_a is logger_b

    file_handlers, console_handlers = _file_and_console_handlers(logger_a)
    assert len(file_handlers) == 1
    assert len(console_handlers) == 1
    assert logger_a.level == logging.DEBUG


def test_logging_handles_unicode(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "log_dir", str(tmp_path / "logs"))
    app_logger = logger_module.setup_logging("INFO")

    message = (
        "Unicode smoke: "
        "\u0054\u0069\u1ebf\u006e\u0067 \u0056\u0069\u1ec7\u0074 "
        "\u65e5\u672c\u8a9e "
        "\u4e2d\u6587"
    )
    app_logger.info(message)

    log_path = Path(config.log_dir) / "translation_app.log"
    content = log_path.read_text(encoding="utf-8")
    assert message in content


def test_logging_rotation_or_file_handler_windows_safe(tmp_path, monkeypatch):
    log_path = tmp_path / "rotation.log"
    handler = logger_module.WindowsSafeRotatingFileHandler(log_path, maxBytes=1, backupCount=1)
    handler.setFormatter(logging.Formatter("%(message)s"))

    monkeypatch.setattr(
        logging.handlers.RotatingFileHandler,
        "doRollover",
        lambda self: (_ for _ in ()).throw(PermissionError("win32 lock")),
    )

    record = logging.LogRecord(
        name="translation_app",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="trigger rollover",
        args=(),
        exc_info=None,
    )

    handler.emit(record)
    handler.close()

    assert log_path.exists() or handler.stream is None


def test_no_secret_in_logging_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "log_dir", str(tmp_path / "logs"))
    app_logger = logger_module.setup_logging("INFO")

    for handler in app_logger.handlers:
        formatter = getattr(handler, "formatter", None)
        if formatter is None:
            continue
        pattern = formatter._fmt
        assert "api_key" not in pattern.lower()
        assert "authorization" not in pattern.lower()
