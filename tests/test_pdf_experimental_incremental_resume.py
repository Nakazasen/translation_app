import types

import pytest

import translation_app.core.file_handlers.pdf_handler as pdf_handler
from translation_app.core.file_handlers.pdf_handler import PDFHandler
from translation_app.core.incremental_translation_cache import get_cache_path


class FakePDFTranslationService:
    def __init__(self, fail_on_call=None):
        self.calls = []
        self.fail_on_call = fail_on_call

    def translate_long_text(self, text, src_lang, dest_lang):
        self.calls.append(text)
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise RuntimeError("simulated provider failure")
        return f"[{dest_lang}:{text}]"


class FakePDFPage:
    def add_redact_annot(self, rect, fill=None):
        return None

    def apply_redactions(self, **kwargs):
        return None


class FakePDFDoc:
    def __init__(self, page_count):
        self.pages = [FakePDFPage() for _ in range(page_count)]
        self.saved_to = None
        self.closed = False

    def __getitem__(self, index):
        return self.pages[index]

    def save(self, output_file):
        self.saved_to = output_file

    def close(self):
        self.closed = True


@pytest.fixture
def isolated_cache(monkeypatch, tmp_path):
    import translation_app.core.incremental_translation_cache as incremental_cache

    monkeypatch.setattr(incremental_cache, "get_incremental_cache_dir", lambda: tmp_path / "cache")
    return tmp_path / "cache"


@pytest.fixture
def experimental_pdf_harness(monkeypatch, tmp_path):
    input_file = tmp_path / "source.pdf"
    output_file = tmp_path / "translated.pdf"
    input_file.write_bytes(b"%PDF-1.4\n% fake text pdf fixture\n")

    model = types.SimpleNamespace(page_count=1)
    plan = types.SimpleNamespace(warnings=[])
    units = [
        {
            "unit_id": "u1",
            "unit_type": "text_block",
            "page_number": 1,
            "page_index": 0,
            "text": "Alpha",
            "redact_rects": ["r1"],
            "source_block_count": 1,
            "source_block_ids": ["b1"],
        },
        {
            "unit_id": "u2",
            "unit_type": "text_block",
            "page_number": 1,
            "page_index": 0,
            "text": "Beta",
            "redact_rects": ["r2"],
            "source_block_count": 1,
            "source_block_ids": ["b2"],
        },
        {
            "unit_id": "u3",
            "unit_type": "text_block",
            "page_number": 1,
            "page_index": 0,
            "text": "Gamma",
            "redact_rects": ["r3"],
            "source_block_count": 1,
            "source_block_ids": ["b3"],
        },
    ]
    selection_summary = {
        "skipped_units": 0,
        "skipped_protected_blocks": 0,
        "skipped_noisy_blocks": 0,
        "warnings_by_type": {},
        "unit_types_by_kind": {"text_block": 3},
    }

    monkeypatch.setattr(pdf_handler, "PYMUPDF_AVAILABLE", True)
    monkeypatch.setattr(pdf_handler, "build_pdf_document_model", lambda path: model)
    monkeypatch.setattr(pdf_handler, "detect_protected_regions", lambda current_model: [])
    monkeypatch.setattr(pdf_handler, "apply_protected_flags", lambda current_model, regions: None)
    monkeypatch.setattr(pdf_handler, "build_pdf_translation_plan", lambda current_model, regions: plan)
    monkeypatch.setattr(pdf_handler, "model_to_protection_summary", lambda current_model, regions: {"counts_by_kind": {}})
    monkeypatch.setattr(
        PDFHandler,
        "_collect_experimental_page_units",
        lambda self, current_model, current_plan: ([[dict(unit) for unit in units]], selection_summary),
    )
    monkeypatch.setattr(
        PDFHandler,
        "_insert_translated_unit",
        lambda self, page, unit: types.SimpleNamespace(
            overflow=False,
            scale_ratio=1.0,
            warnings=[],
        ),
    )
    monkeypatch.setattr(
        pdf_handler,
        "fitz",
        types.SimpleNamespace(
            open=lambda path: FakePDFDoc(model.page_count),
            PDF_REDACT_IMAGE_NONE=0,
            PDF_REDACT_LINE_ART_NONE=0,
            PDF_REDACT_TEXT_REMOVE=0,
        ),
    )

    return input_file, output_file


def test_experimental_pdf_resume_skips_cached_text_units(
    tmp_path,
    isolated_cache,
    experimental_pdf_harness,
):
    input_file, output_file = experimental_pdf_harness

    first_service = FakePDFTranslationService(fail_on_call=3)
    first_result = PDFHandler(first_service).translate_to_pdf_experimental(
        str(input_file),
        str(output_file),
        "en",
        "vi",
    )

    cache_path = get_cache_path(str(input_file), "en", "vi", pdf_handler.PDF_EXPERIMENTAL_CACHE_HANDLER)
    assert cache_path.exists()
    assert first_service.calls == ["Alpha", "Beta", "Gamma"]
    assert first_result["translated_units"] == 2

    second_service = FakePDFTranslationService()
    second_result = PDFHandler(second_service).translate_to_pdf_experimental(
        str(input_file),
        str(output_file),
        "en",
        "vi",
    )

    assert second_service.calls == ["Gamma"]
    assert second_result["translated_units"] == 3
    assert not cache_path.exists()


def test_experimental_pdf_source_change_does_not_reuse_cache(
    tmp_path,
    isolated_cache,
    experimental_pdf_harness,
):
    input_file, output_file = experimental_pdf_harness

    PDFHandler(FakePDFTranslationService(fail_on_call=2)).translate_to_pdf_experimental(
        str(input_file),
        str(output_file),
        "en",
        "vi",
    )
    input_file.write_bytes(b"%PDF-1.4\n% changed fake text pdf fixture\n")

    service = FakePDFTranslationService()
    PDFHandler(service).translate_to_pdf_experimental(
        str(input_file),
        str(output_file),
        "en",
        "vi",
    )

    assert service.calls == ["Alpha", "Beta", "Gamma"]


def test_experimental_pdf_target_language_change_does_not_reuse_cache(
    tmp_path,
    isolated_cache,
    experimental_pdf_harness,
):
    input_file, output_file = experimental_pdf_harness

    PDFHandler(FakePDFTranslationService(fail_on_call=2)).translate_to_pdf_experimental(
        str(input_file),
        str(output_file),
        "en",
        "vi",
    )

    service = FakePDFTranslationService()
    PDFHandler(service).translate_to_pdf_experimental(
        str(input_file),
        str(output_file),
        "en",
        "ja",
    )

    assert service.calls == ["Alpha", "Beta", "Gamma"]
