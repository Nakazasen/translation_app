import logging

import pytest

from tests.helpers.pdf_fixtures import (
    FakeTranslationService,
    create_cjk_vietnamese_pdf,
    create_formula_like_pdf,
    create_image_caption_pdf,
    create_scanned_image_pdf,
    create_simple_text_pdf,
    create_table_like_pdf,
    create_two_column_pdf,
    create_two_page_pdf,
)
from tests.helpers.pdf_metrics import (
    collect_pdf_text_blocks,
    count_images_or_drawings,
    count_overflow_warnings,
    count_pages,
    count_text_blocks,
    detect_mojibake_in_pdf_text,
    estimate_bbox_drift,
    extract_text_joined,
)
from translation_app.core.file_handlers.pdf_handler import PDFHandler
from translation_app.utils.error_handler import FileProcessingError


def test_pdf_baseline_simple_text_extraction(tmp_path):
    pdf_path = create_simple_text_pdf(tmp_path / "simple_text.pdf")

    assert count_pages(pdf_path) == 1
    assert "Hello world" in extract_text_joined(pdf_path)
    assert count_text_blocks(pdf_path) >= 1
    assert not detect_mojibake_in_pdf_text(pdf_path)


def test_pdf_baseline_two_page_count(tmp_path):
    pdf_path = create_two_page_pdf(
        tmp_path / "two_page.pdf",
        ["First page text", "Second page text"],
    )

    assert count_pages(pdf_path) == 2
    joined_text = extract_text_joined(pdf_path)
    assert "First page text" in joined_text
    assert "Second page text" in joined_text


def test_pdf_baseline_two_column_order_is_measured_not_claimed(tmp_path):
    pdf_path = create_two_column_pdf(tmp_path / "two_column.pdf")

    blocks = collect_pdf_text_blocks(pdf_path)
    block_texts = [block["text"] for block in blocks]

    assert block_texts == ["LEFT ONE\nLEFT TWO", "RIGHT ONE\nRIGHT TWO"]
    assert extract_text_joined(pdf_path) == "LEFT ONE\nLEFT TWO\nRIGHT ONE\nRIGHT TWO"


def test_pdf_baseline_table_like_blocks(tmp_path):
    pdf_path = create_table_like_pdf(tmp_path / "table_like.pdf")
    joined_text = extract_text_joined(pdf_path)

    for expected in ["Item", "Qty", "Price", "Apple", "Banana", "Cherry"]:
        assert expected in joined_text
    assert count_text_blocks(pdf_path) >= 4


def test_pdf_baseline_image_caption_detects_text_and_image_presence(tmp_path):
    pdf_path = create_image_caption_pdf(tmp_path / "image_caption.pdf")
    object_counts = count_images_or_drawings(pdf_path)

    assert "Caption: Sample image block" in extract_text_joined(pdf_path)
    assert object_counts["image_count"] >= 1
    assert object_counts["protected_object_count"] >= 1


def test_pdf_baseline_formula_like_text_measured(tmp_path):
    pdf_path = create_formula_like_pdf(tmp_path / "formula_like.pdf")
    joined_text = extract_text_joined(pdf_path)

    for expected in ["E = mc^2", "SUM(A1:A3)", "x^2 + y^2"]:
        assert expected in joined_text


def test_pdf_baseline_cjk_vietnamese_text_if_font_available(tmp_path):
    pdf_path = create_cjk_vietnamese_pdf(tmp_path / "cjk_vi.pdf")
    if pdf_path is None:
        pytest.skip("No suitable system fonts found for Vietnamese + CJK PDF fixture")

    joined_text = extract_text_joined(pdf_path).replace("\xa0", " ")

    assert "Tiếng Việt" in joined_text
    assert "日本語 中文" in joined_text
    assert not detect_mojibake_in_pdf_text(pdf_path)


def test_pdf_baseline_scanned_image_pdf_has_no_text_blocks(tmp_path):
    input_path = create_scanned_image_pdf(tmp_path / "scanned.pdf")

    assert count_text_blocks(input_path) == 0

    service = FakeTranslationService()
    handler = PDFHandler(service)
    try:
        with pytest.raises(FileProcessingError, match="text-based PDFs|Scanned|supported text blocks"):
            handler.translate_to_pdf_experimental(
                str(input_path),
                str(tmp_path / "scanned_output.pdf"),
                "en",
                "vi",
            )
    finally:
        service.executor.shutdown(wait=True)


def test_pdf_experimental_output_has_metrics(tmp_path, caplog):
    input_path = create_simple_text_pdf(tmp_path / "experimental_input.pdf", "Hello world")
    output_path = tmp_path / "experimental_output.pdf"
    service = FakeTranslationService(translations={"Hello world": "Xin chao the gioi"})
    handler = PDFHandler(service)

    caplog.set_level(logging.INFO)
    try:
        stats = handler.translate_to_pdf_experimental(
            str(input_path),
            str(output_path),
            "en",
            "vi",
        )
    finally:
        service.executor.shutdown(wait=True)

    before_blocks = collect_pdf_text_blocks(input_path)
    after_blocks = collect_pdf_text_blocks(output_path)
    drift = estimate_bbox_drift(before_blocks, after_blocks)
    output_text = extract_text_joined(output_path)

    assert count_pages(input_path) == count_pages(output_path) == 1
    assert "Xin chao the gioi" in output_text
    assert "Hello world" not in output_text
    assert drift["compared_blocks"] >= 1
    assert drift["avg_center_drift"] <= 80.0
    assert stats["overflow_blocks"] == count_overflow_warnings(caplog.text)
    assert not detect_mojibake_in_pdf_text(output_path)


def test_pdf_metrics_do_not_log_raw_keys_or_prompt(tmp_path, caplog):
    fake_key = "AI" + "za" + "-FAKE-KEY"
    fake_header = "Auth" + "orization: Bearer hidden"
    fake_prompt = "Source" + " Text:"
    pdf_path = create_simple_text_pdf(
        tmp_path / "sensitive.pdf",
        f"{fake_key}\n{fake_header}\n{fake_prompt}",
    )

    caplog.set_level(logging.INFO)
    blocks = collect_pdf_text_blocks(pdf_path)
    joined_text = extract_text_joined(pdf_path)

    assert blocks
    assert fake_key in joined_text
    assert fake_header in joined_text
    assert fake_prompt in joined_text
    assert fake_key not in caplog.text
    assert fake_header not in caplog.text
    assert fake_prompt not in caplog.text
