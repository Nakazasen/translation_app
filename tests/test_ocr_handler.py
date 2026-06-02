import pytest
from translation_app.core.ocr_handler import OCRHandler
from translation_app.utils.error_handler import OCRError


def test_ocr_handler_ja_missing_jpn_raises_ocr_error(monkeypatch):
    handler = OCRHandler()
    monkeypatch.setattr(handler, "is_installed", lambda: True)
    monkeypatch.setattr(handler, "get_installed_languages", lambda: ["eng"])

    with pytest.raises(OCRError) as excinfo:
        handler.get_ocr_language("ja")

    assert "Gói ngôn ngữ OCR 'jpn' chưa được cài đặt" in str(excinfo.value)


def test_ocr_handler_auto_filters_installed_languages(monkeypatch):
    handler = OCRHandler()
    monkeypatch.setattr(handler, "is_installed", lambda: True)

    # 1. only eng is installed
    monkeypatch.setattr(handler, "get_installed_languages", lambda: ["eng"])
    assert handler.get_ocr_language("auto") == "eng"

    # 2. eng and jpn are installed
    monkeypatch.setattr(handler, "get_installed_languages", lambda: ["eng", "jpn"])
    assert handler.get_ocr_language("auto") == "jpn+eng"

    # 3. all except vie are installed
    monkeypatch.setattr(handler, "get_installed_languages", lambda: ["eng", "jpn", "chi_sim"])
    assert handler.get_ocr_language("auto") == "jpn+eng+chi_sim"


def test_ocr_handler_missing_jpn_error_contains_instructions(monkeypatch):
    handler = OCRHandler()
    monkeypatch.setattr(handler, "is_installed", lambda: True)
    monkeypatch.setattr(handler, "get_installed_languages", lambda: ["eng"])

    with pytest.raises(OCRError) as excinfo:
        handler.get_ocr_language("ja")

    error_msg = str(excinfo.value)
    assert "jpn.traineddata" in error_msg
    assert "C:\\Program Files\\Tesseract-OCR\\tessdata" in error_msg
