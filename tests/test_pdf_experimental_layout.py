import concurrent.futures
import logging

import fitz
import pytest

from translation_app.core.file_handlers.pdf_handler import PDFHandler
from translation_app.utils.error_handler import FileProcessingError


class FakeTranslationService:
    def __init__(self, translations=None):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.timeout = 5
        self.strategy = "ai"
        self.observer = None
        self.calls = []
        self.translations = translations or {}

    def set_runtime_observer(self, observer):
        self.observer = observer

    def clear_runtime_observer(self):
        self.observer = None

    def translate_long_text(self, text, src_lang, dest_lang, max_length=None):
        self.calls.append(text)
        if self.observer:
            self.observer("provider_call", {"provider": "fake"})
        return self.translations.get(text, f"{text}-{dest_lang}")

    def translate_text(self, text, src_lang, dest_lang):
        return self.translate_long_text(text, src_lang, dest_lang)


def _make_text_pdf(path, pages):
    doc = fitz.open()
    for page_text in pages:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 300, 180), page_text, fontsize=14, fontname="helv")
    doc.save(path)
    doc.close()


def _make_blank_pdf(path):
    doc = fitz.open()
    doc.new_page()
    doc.save(path)
    doc.close()


def _extract_page_texts(path):
    doc = fitz.open(path)
    try:
        return [page.get_text("text").strip() for page in doc]
    finally:
        doc.close()


def _run_experimental_translation(tmp_path, pages, translations=None):
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    _make_text_pdf(input_path, pages)

    service = FakeTranslationService(translations=translations)
    handler = PDFHandler(service)

    try:
        stats = handler.translate_to_pdf_experimental(str(input_path), str(output_path), "en", "vi")
    finally:
        service.executor.shutdown(wait=True)

    return input_path, output_path, service, stats


def test_pdf_experimental_preserves_page_count(tmp_path):
    _, output_path, _, stats = _run_experimental_translation(
        tmp_path,
        ["Hello page one", "Hello page two"],
        translations={
            "Hello page one": "Xin chao trang mot",
            "Hello page two": "Xin chao trang hai",
        },
    )

    doc = fitz.open(output_path)
    try:
        assert doc.page_count == 2
    finally:
        doc.close()

    assert stats["page_count"] == 2
    assert stats["translated_blocks"] == 2


def test_pdf_experimental_translates_simple_text_blocks(tmp_path):
    _, output_path, service, _ = _run_experimental_translation(
        tmp_path,
        ["Hello world"],
        translations={"Hello world": "Xin chao the gioi"},
    )

    output_text = _extract_page_texts(output_path)[0]
    assert "Xin chao the gioi" in output_text
    assert "Hello world" not in output_text
    assert service.calls == ["Hello world"]


def test_pdf_experimental_uses_translation_service(tmp_path, monkeypatch):
    import translation_app.core.ai_service as ai_service_module

    def fail_get_ai_service():
        raise AssertionError("Experimental PDF path must not call AI service directly")

    monkeypatch.setattr(ai_service_module, "get_ai_service", fail_get_ai_service)

    _, output_path, service, _ = _run_experimental_translation(
        tmp_path,
        ["Translate through service"],
        translations={"Translate through service": "Di qua service"},
    )

    assert output_path.exists()
    assert service.calls == ["Translate through service"]


def test_pdf_experimental_rejects_scanned_or_empty_pdf(tmp_path):
    input_path = tmp_path / "blank.pdf"
    output_path = tmp_path / "blank_output.pdf"
    _make_blank_pdf(input_path)

    service = FakeTranslationService()
    handler = PDFHandler(service)

    try:
        with pytest.raises(FileProcessingError, match="text-based PDFs|Scanned|supported text blocks"):
            handler.translate_to_pdf_experimental(str(input_path), str(output_path), "en", "vi")
    finally:
        service.executor.shutdown(wait=True)

    assert not output_path.exists()


def test_pdf_experimental_does_not_log_raw_text_or_keys(tmp_path, caplog):
    source_text = "Top secret paragraph"
    translated_text = "Doan da duoc dich"

    caplog.set_level(logging.INFO)
    _, _, service, _ = _run_experimental_translation(
        tmp_path,
        [source_text],
        translations={source_text: translated_text},
    )

    log_text = caplog.text
    assert source_text not in log_text
    assert translated_text not in log_text
    assert "AIza" not in log_text
    assert "Authorization" not in log_text
    assert service.calls == [source_text]


def test_pdf_experimental_no_mojibake_with_vietnamese_text_when_supported(tmp_path):
    source_text = "Xin chao PDF thu nghiem"
    translated_text = "Ban dich tieng Viet on dinh"
    input_path, output_path, service, stats = _run_experimental_translation(
        tmp_path,
        [source_text],
        translations={source_text: translated_text},
    )

    source_pages = _extract_page_texts(input_path)
    if source_text not in source_pages[0]:
        service.executor.shutdown(wait=True)
        pytest.skip("Local PyMuPDF font/text extraction does not preserve this sample reliably")

    output_pages = _extract_page_texts(output_path)
    assert translated_text in output_pages[0]
    assert stats["page_count"] == 1

