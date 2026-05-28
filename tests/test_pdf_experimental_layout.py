import concurrent.futures
import logging

import fitz
import pytest

from tests.helpers.pdf_fixtures import create_image_caption_pdf, create_scanned_image_pdf, create_table_like_pdf
from translation_app.core.file_handlers.pdf_text_fit import PDFTextFitResult
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


def _make_formula_mixed_pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(
        fitz.Rect(72, 72, 320, 130),
        "Translate this paragraph",
        fontsize=14,
        fontname="helv",
    )
    page.insert_textbox(
        fitz.Rect(72, 170, 360, 240),
        "E = mc^2\nSUM(A1:A3)",
        fontsize=14,
        fontname="cour",
    )
    doc.save(path)
    doc.close()


def _make_adjacent_paragraph_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(72, 72, 320, 102), "First paragraph line", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(72, 104, 320, 134), "Second paragraph line", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(72, 220, 320, 250), "Separate paragraph", fontsize=12, fontname="helv")
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
    _, output_path, service, stats = _run_experimental_translation(
        tmp_path,
        ["Hello world"],
        translations={"Hello world": "Xin chao the gioi"},
    )

    output_text = _extract_page_texts(output_path)[0]
    assert "Xin chao the gioi" in output_text
    assert "Hello world" not in output_text
    assert service.calls == ["Hello world"]
    assert stats["translated_blocks"] == 1


def test_pdf_experimental_generates_success_report(tmp_path):
    input_path = tmp_path / "success_report_input.pdf"
    output_path = tmp_path / "success_report_output.pdf"
    _make_text_pdf(input_path, ["Hello world"])

    service = FakeTranslationService(translations={"Hello world": "Xin chao the gioi"})
    handler = PDFHandler(service)
    try:
        stats = handler.translate_to_pdf_experimental(str(input_path), str(output_path), "en", "vi")
    finally:
        service.executor.shutdown(wait=True)

    assert output_path.exists()
    assert stats["translated_blocks"] == 1
    assert handler.last_pdf_qa_report is not None
    assert handler.last_pdf_qa_report["translated_blocks"] == 1
    assert handler.last_pdf_qa_report["page_count"] == 1
    assert handler.last_pdf_qa_report["rejected"] is False


def test_pdf_experimental_report_is_available_on_handler(tmp_path):
    input_path = tmp_path / "report_input.pdf"
    output_path = tmp_path / "report_output.pdf"
    _make_text_pdf(input_path, ["Hello world"])

    service = FakeTranslationService(translations={"Hello world": "Xin chao the gioi"})
    handler = PDFHandler(service)
    try:
        handler.translate_to_pdf_experimental(str(input_path), str(output_path), "en", "vi")
    finally:
        service.executor.shutdown(wait=True)

    report = handler.last_pdf_qa_report
    assert report is not None
    assert report["mode"] == "experimental_pdf"
    assert report["page_count"] == 1
    assert report["translated_blocks"] == 1
    assert report["rejected"] is False
    assert report["input_file"] == "report_input.pdf"
    assert report["output_file"] == "report_output.pdf"
    assert "Hello world" not in repr(report)


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
    assert handler.last_pdf_qa_report is not None
    assert handler.last_pdf_qa_report["rejected"] is True
    assert handler.last_pdf_qa_report["translated_units"] == 0
    assert handler.last_pdf_qa_report["rejection_reason"] is not None


def test_pdf_experimental_rejected_scanned_report(tmp_path):
    input_path = create_scanned_image_pdf(tmp_path / "scanned_input.pdf")
    output_path = tmp_path / "scanned_output.pdf"

    service = FakeTranslationService()
    handler = PDFHandler(service)
    try:
        with pytest.raises(FileProcessingError, match="Scanned or image-only PDFs are not supported"):
            handler.translate_to_pdf_experimental(str(input_path), str(output_path), "en", "vi")
    finally:
        service.executor.shutdown(wait=True)

    report = handler.last_pdf_qa_report
    assert report is not None
    assert report["rejected"] is True
    assert report["translated_units"] == 0
    assert report["protected_regions_by_kind"]["scanned_page"] == 1
    assert report["warnings_by_type"]["scanned_or_image_only_pdf"] >= 1
    assert "Scanned or image-only PDFs are not supported." in report["rejection_reason"]


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


def test_pdf_experimental_uses_canonical_model_and_protection(tmp_path, monkeypatch):
    import translation_app.core.file_handlers.pdf_handler as pdf_handler_module

    call_counts = {
        "build_model": 0,
        "detect_regions": 0,
        "apply_flags": 0,
        "build_plan": 0,
    }

    original_build = pdf_handler_module.build_pdf_document_model
    original_detect = pdf_handler_module.detect_protected_regions
    original_apply = pdf_handler_module.apply_protected_flags
    original_plan = pdf_handler_module.build_pdf_translation_plan

    def wrapped_build(*args, **kwargs):
        call_counts["build_model"] += 1
        return original_build(*args, **kwargs)

    def wrapped_detect(*args, **kwargs):
        call_counts["detect_regions"] += 1
        return original_detect(*args, **kwargs)

    def wrapped_apply(*args, **kwargs):
        call_counts["apply_flags"] += 1
        return original_apply(*args, **kwargs)

    def wrapped_plan(*args, **kwargs):
        call_counts["build_plan"] += 1
        return original_plan(*args, **kwargs)

    monkeypatch.setattr(pdf_handler_module, "build_pdf_document_model", wrapped_build)
    monkeypatch.setattr(pdf_handler_module, "detect_protected_regions", wrapped_detect)
    monkeypatch.setattr(pdf_handler_module, "apply_protected_flags", wrapped_apply)
    monkeypatch.setattr(pdf_handler_module, "build_pdf_translation_plan", wrapped_plan)

    _, output_path, _, stats = _run_experimental_translation(
        tmp_path,
        ["Hello world"],
        translations={"Hello world": "Xin chao the gioi"},
    )

    assert output_path.exists()
    assert stats["translated_blocks"] == 1
    assert call_counts == {
        "build_model": 1,
        "detect_regions": 1,
        "apply_flags": 1,
        "build_plan": 1,
    }


def test_pdf_experimental_translates_paragraph_unit_once(tmp_path):
    input_path = tmp_path / "paragraph_input.pdf"
    output_path = tmp_path / "paragraph_output.pdf"
    _make_adjacent_paragraph_pdf(input_path)

    translations = {
        "First paragraph line\nSecond paragraph line": "Doan mot da dich",
        "Separate paragraph": "Doan hai da dich",
    }
    service = FakeTranslationService(translations=translations)
    handler = PDFHandler(service)
    try:
        stats = handler.translate_to_pdf_experimental(str(input_path), str(output_path), "en", "vi")
    finally:
        service.executor.shutdown(wait=True)

    assert service.calls == ["First paragraph line\nSecond paragraph line", "Separate paragraph"]
    assert stats["translated_units"] == 2
    assert stats["translated_blocks"] == 3


def test_pdf_experimental_preserves_caption_unit_translation(tmp_path):
    input_path = create_image_caption_pdf(tmp_path / "caption_input.pdf", caption_text="Figure 1: Chart sample")
    output_path = tmp_path / "caption_output.pdf"

    service = FakeTranslationService(translations={"Figure 1: Chart sample": "Hinh 1: Mau bieu do"})
    handler = PDFHandler(service)
    try:
        stats = handler.translate_to_pdf_experimental(str(input_path), str(output_path), "en", "vi")
    finally:
        service.executor.shutdown(wait=True)

    output_text = _extract_page_texts(output_path)[0]
    assert service.calls == ["Figure 1: Chart sample"]
    assert "Hinh 1: Mau bieu do" in output_text
    assert stats["translated_units"] == 1
    assert handler.last_pdf_qa_report["unit_types_by_kind"]["caption"] == 1


def test_pdf_experimental_skips_formula_like_blocks(tmp_path):
    input_path = tmp_path / "formula_mixed.pdf"
    output_path = tmp_path / "formula_mixed_output.pdf"
    _make_formula_mixed_pdf(input_path)

    service = FakeTranslationService(translations={"Translate this paragraph": "Doan van da dich"})
    handler = PDFHandler(service)
    try:
        stats = handler.translate_to_pdf_experimental(str(input_path), str(output_path), "en", "vi")
    finally:
        service.executor.shutdown(wait=True)

    output_text = _extract_page_texts(output_path)[0]
    assert service.calls == ["Translate this paragraph"]
    assert "Doan van da dich" in output_text
    assert "E = mc^2" in output_text
    assert stats["translated_units"] == 1
    assert stats["skipped_protected_blocks"] >= 1
    assert handler.last_pdf_qa_report["protected_regions_by_kind"]["formula"] >= 1


def test_pdf_experimental_skips_table_regions(tmp_path):
    input_path = create_table_like_pdf(tmp_path / "table_like.pdf")
    output_path = tmp_path / "table_like_output.pdf"

    service = FakeTranslationService()
    handler = PDFHandler(service)
    try:
        stats = handler.translate_to_pdf_experimental(str(input_path), str(output_path), "en", "vi")
    finally:
        service.executor.shutdown(wait=True)

    assert service.calls == ["Item\nQty\nPrice"]
    assert stats["translated_units"] == 1
    assert stats["skipped_protected_blocks"] >= 1
    assert handler.last_pdf_qa_report["protected_regions_by_kind"]["table"] >= 1


def test_pdf_experimental_report_counts_image_protection(tmp_path):
    input_path = create_image_caption_pdf(tmp_path / "image_caption.pdf", caption_text="Figure 1: Chart sample")
    output_path = tmp_path / "image_caption_output.pdf"

    service = FakeTranslationService()
    handler = PDFHandler(service)
    try:
        stats = handler.translate_to_pdf_experimental(str(input_path), str(output_path), "en", "vi")
    finally:
        service.executor.shutdown(wait=True)

    assert stats["translated_blocks"] >= 1
    assert handler.last_pdf_qa_report["protected_regions_by_kind"]["chart"] >= 1
    assert handler.last_pdf_qa_report["protected_regions_by_kind"]["caption"] >= 1


def test_pdf_experimental_uses_text_fit_for_insert(tmp_path, monkeypatch):
    import translation_app.core.file_handlers.pdf_handler as pdf_handler_module

    calls = {"fit": 0}

    def fake_fit(request):
        calls["fit"] += 1
        return PDFTextFitResult(
            fitted_text="Wrapped\ntranslation",
            lines=["Wrapped", "translation"],
            font_size=max(6.0, request.font_size - 2.0),
            line_height=max(6.0, request.font_size - 2.0) * request.line_height_ratio,
            bbox=request.bbox,
            overflow=True,
            overflow_reason="text_overflow",
            warnings=["font_shrunk", "text_overflow"],
            scale_ratio=0.75,
        )

    monkeypatch.setattr(pdf_handler_module, "fit_text_to_bbox", fake_fit)

    _, output_path, _, stats = _run_experimental_translation(
        tmp_path,
        ["Hello world"],
        translations={"Hello world": "A much longer translated paragraph for fitting"},
    )

    assert output_path.exists()
    assert calls["fit"] == 1
    assert stats["overflow_units"] == 1
    assert stats["overflow_blocks"] == 1
    assert stats["warning_count"] >= 2


def test_pdf_experimental_report_counts_overflow(tmp_path, monkeypatch):
    import translation_app.core.file_handlers.pdf_handler as pdf_handler_module

    def fake_fit(request):
        return PDFTextFitResult(
            fitted_text="Wrapped\ntranslation",
            lines=["Wrapped", "translation"],
            font_size=max(6.0, request.font_size - 2.0),
            line_height=max(6.0, request.font_size - 2.0) * request.line_height_ratio,
            bbox=request.bbox,
            overflow=True,
            overflow_reason="text_overflow",
            warnings=["font_shrunk", "text_overflow"],
            scale_ratio=0.75,
        )

    monkeypatch.setattr(pdf_handler_module, "fit_text_to_bbox", fake_fit)

    input_path = tmp_path / "overflow_input.pdf"
    output_path = tmp_path / "overflow_output.pdf"
    _make_text_pdf(input_path, ["Hello world"])

    service = FakeTranslationService(translations={"Hello world": "Very long translated block"})
    handler = PDFHandler(service)
    try:
        handler.translate_to_pdf_experimental(str(input_path), str(output_path), "en", "vi")
    finally:
        service.executor.shutdown(wait=True)

    report = handler.last_pdf_qa_report
    assert report["translated_units"] == 1
    assert report["overflow_blocks"] == 1
    assert report["overflow_units"] == 1
    assert report["warning_count"] >= 2
    assert report["warnings_by_type"]["text_overflow"] >= 1
    assert "Very long translated block" not in repr(report)


def test_pdf_experimental_outputs_warning_summary_without_raw_text(tmp_path):
    _, _, _, stats = _run_experimental_translation(
        tmp_path,
        ["Hello world"],
        translations={"Hello world": "Xin chao the gioi"},
    )

    assert "warning_count" in stats
    assert "skipped_protected_blocks" in stats
    assert "skipped_noisy_blocks" in stats
    assert "Hello world" not in repr(stats)


def test_pdf_experimental_outputs_warning_summary_without_raw_text_in_report(tmp_path):
    input_path = tmp_path / "warning_input.pdf"
    output_path = tmp_path / "warning_output.pdf"
    _make_text_pdf(input_path, ["Hello world"])

    service = FakeTranslationService(translations={"Hello world": "Xin chao the gioi"})
    handler = PDFHandler(service)
    try:
        handler.translate_to_pdf_experimental(str(input_path), str(output_path), "en", "vi")
    finally:
        service.executor.shutdown(wait=True)

    report = handler.last_pdf_qa_report
    assert report is not None
    assert "translated_units" in report
    assert "skipped_units" in report
    assert "overflow_units" in report
    assert "unit_types_by_kind" in report
    assert "warning_count" in report
    assert "warnings_by_type" in report
    assert "Hello world" not in repr(report)
    assert "Xin chao the gioi" not in repr(report)
    assert "prompt" not in repr(report)
    assert "AIza" not in repr(report)


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
