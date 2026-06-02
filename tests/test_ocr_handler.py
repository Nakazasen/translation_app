import pytest
from PIL import Image

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


def test_ocr_handler_rejects_latin_garbage_for_japanese_auto():
    handler = OCRHandler()
    garbage_text = "= @)YouTube m' Tim kiem = Q\nBACH bys — CISD EIA CUT EE é"

    with pytest.raises(OCRError) as excinfo:
        handler.validate_ocr_text_quality(garbage_text, "jpn+eng")

    assert "ký tự Latin vô nghĩa" in str(excinfo.value)


def test_ocr_handler_accepts_japanese_text_for_japanese_auto():
    handler = OCRHandler()

    handler.validate_ocr_text_quality("こんにちは 世界", "jpn+eng")


def test_ocr_handler_does_not_apply_japanese_guard_to_english():
    handler = OCRHandler()

    handler.validate_ocr_text_quality("= @)YouTube m' Tim kiem = Q", "eng")


def test_ocr_quality_warns_on_latin_only_for_japanese_context(monkeypatch):
    handler = OCRHandler()
    monkeypatch.setattr(handler, "get_installed_languages", lambda: ["eng", "jpn"])

    # Text contains latin garbage and metadata word
    res = handler.check_ocr_quality("tesseract resolution dpi bad text", "ja", "vi")
    assert res["is_low_quality"] is True
    assert "tesseract" in res["reason"]
    assert res["missing_jpn_pack"] is False

    # Text contains no Japanese at all
    res2 = handler.check_ocr_quality("this is normal english sentence without any japanese script", "auto", "vi")
    assert res2["is_low_quality"] is True
    assert "Không tìm thấy ký tự tiếng Nhật" in res2["reason"]


def test_ocr_quality_warns_when_text_too_short(monkeypatch):
    handler = OCRHandler()
    monkeypatch.setattr(handler, "get_installed_languages", lambda: ["eng", "jpn"])

    res = handler.check_ocr_quality("abc", "en", "vi")
    assert res["is_low_quality"] is True
    assert "Văn bản nhận diện quá ngắn" in res["reason"]


def test_ocr_quality_missing_jpn_pack_in_japanese_context(monkeypatch):
    handler = OCRHandler()
    monkeypatch.setattr(handler, "get_installed_languages", lambda: ["eng"])

    res = handler.check_ocr_quality("abc", "ja", "vi")
    assert res["is_low_quality"] is True
    assert res["missing_jpn_pack"] is True
    assert "Thiếu gói OCR tiếng Nhật" in res["reason"]


def test_ocr_uses_upscaled_image_for_small_text(monkeypatch):
    handler = OCRHandler()
    handler.is_available = True
    image = Image.new("RGB", (40, 20), "white")
    seen_sizes = []

    def fake_ocr(processed_image, lang):
        seen_sizes.append(processed_image.size)
        return "字幕テスト"

    monkeypatch.setattr("translation_app.core.ocr_handler.pytesseract.image_to_string", fake_ocr)

    text = handler.extract_text_from_image(image, lang="jpn", mode="auto")

    assert text == "字幕テスト"
    assert seen_sizes[0] == (80, 40)


def test_ocr_falls_back_to_bottom_subtitle_crop_when_full_image_empty(monkeypatch):
    handler = OCRHandler()
    handler.is_available = True
    image = Image.new("RGB", (100, 60), "white")
    attempted_sizes = []

    def fake_ocr(processed_image, lang):
        attempted_sizes.append(processed_image.size)
        if len(attempted_sizes) <= 2:
            return ""
        return "字幕が見えます"

    monkeypatch.setattr("translation_app.core.ocr_handler.pytesseract.image_to_string", fake_ocr)

    result = handler.extract_text_with_metadata(image, lang="jpn", mode="auto")

    assert result.text == "字幕が見えます"
    assert result.used_subtitle_crop is True
    assert result.strategy_used == "bottom_40_3x"
    assert result.attempted_strategies[:3] == ["full_image_2x", "full_image_3x", "bottom_40_3x"]
    assert attempted_sizes[2] == (300, 72)


def test_ocr_reports_clear_message_when_no_text_after_preprocessing(monkeypatch):
    handler = OCRHandler()
    handler.is_available = True
    image = Image.new("RGB", (80, 40), "white")

    monkeypatch.setattr(
        "translation_app.core.ocr_handler.pytesseract.image_to_string",
        lambda *_args, **_kwargs: "",
    )

    result = handler.extract_text_with_metadata(image, lang="eng", mode="subtitle")

    assert result.text == ""
    assert result.strategy_used == "none"
    assert result.attempted_strategies == [
        "subtitle_full_3x",
        "subtitle_bottom_40_3x",
        "subtitle_bottom_35_3x",
    ]
    assert result.used_subtitle_crop is False
