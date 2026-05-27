import pytest

from tests.helpers.pdf_fixtures import (
    create_formula_like_pdf,
    create_image_caption_pdf,
    create_scanned_image_pdf,
    create_simple_text_pdf,
    create_table_like_pdf,
    create_two_column_pdf,
    create_two_page_pdf,
)
from translation_app.core.file_handlers.pdf_model import (
    build_pdf_document_model,
    collect_text_blocks_from_model,
    model_to_public_metrics,
)


def test_pdf_model_builds_simple_document(tmp_path):
    pdf_path = create_simple_text_pdf(tmp_path / "simple_model.pdf", "Hello world")

    model = build_pdf_document_model(pdf_path)

    assert model.page_count == 1
    assert model.source_path == str(pdf_path)
    assert model.pages[0].width > 0
    assert model.pages[0].height > 0
    assert any(block.kind == "text" for block in model.pages[0].blocks)
    assert "Hello world" in "\n".join(block.text for block in model.pages[0].blocks if block.text)


def test_pdf_model_preserves_page_geometry(tmp_path):
    pdf_path = create_two_page_pdf(
        tmp_path / "geometry.pdf",
        ["First page text", "Second page text"],
    )

    model = build_pdf_document_model(pdf_path)

    assert model.page_count == 2
    assert [page.page_index for page in model.pages] == [0, 1]
    assert all(page.width > 0 and page.height > 0 for page in model.pages)


def test_pdf_model_extracts_spans_with_font_metadata(tmp_path):
    pdf_path = create_simple_text_pdf(tmp_path / "spans.pdf", "Span metadata")

    model = build_pdf_document_model(pdf_path)
    text_block = next(block for block in model.pages[0].blocks if block.kind == "text" and block.lines)
    span = text_block.lines[0].spans[0]

    assert span.text
    assert span.bbox[2] > span.bbox[0]
    assert span.font
    assert span.size > 0


def test_pdf_model_reading_order_is_deterministic(tmp_path):
    pdf_path = create_two_column_pdf(tmp_path / "reading_order.pdf")

    first_model = build_pdf_document_model(pdf_path)
    second_model = build_pdf_document_model(pdf_path)

    first_blocks = collect_text_blocks_from_model(first_model)
    second_blocks = collect_text_blocks_from_model(second_model)

    assert [block["text"] for block in first_blocks] == ["LEFT ONE\nLEFT TWO", "RIGHT ONE\nRIGHT TWO"]
    assert [block["reading_order"] for block in first_blocks] == [0, 1]
    assert first_blocks == second_blocks


def test_pdf_model_marks_formula_like_blocks(tmp_path):
    pdf_path = create_formula_like_pdf(tmp_path / "formula_model.pdf")

    model = build_pdf_document_model(pdf_path)
    formula_blocks = [
        block
        for page in model.pages
        for block in page.blocks
        if "formula_like" in block.flags
    ]

    assert formula_blocks
    assert any("protected" in block.flags for block in formula_blocks)


def test_pdf_model_detects_image_blocks(tmp_path):
    pdf_path = create_image_caption_pdf(tmp_path / "image_model.pdf")

    model = build_pdf_document_model(pdf_path)
    metrics = model_to_public_metrics(model)

    assert metrics["image_block_count"] >= 1
    assert metrics["protected_object_count"] >= 1
    assert any(
        "caption_like" in block.flags
        for page in model.pages
        for block in page.blocks
        if block.kind == "text"
    )


def test_pdf_model_marks_table_like_blocks_with_rough_heuristic(tmp_path):
    pdf_path = create_table_like_pdf(tmp_path / "table_model.pdf")

    model = build_pdf_document_model(pdf_path)
    table_like_blocks = [
        block
        for page in model.pages
        for block in page.blocks
        if "table_like" in block.flags
    ]

    assert table_like_blocks


def test_pdf_model_scanned_pdf_has_no_translatable_text_blocks(tmp_path):
    pdf_path = create_scanned_image_pdf(tmp_path / "scanned_model.pdf")

    model = build_pdf_document_model(pdf_path)
    text_blocks = [block for page in model.pages for block in page.blocks if block.kind == "text"]
    translatable_blocks = [
        block
        for page in model.pages
        for block in page.blocks
        if "translatable" in block.flags
    ]

    assert text_blocks == []
    assert translatable_blocks == []


def test_pdf_model_public_metrics_has_no_raw_secret(tmp_path):
    fake_key = "AI" + "za" + "-FAKE-KEY"
    fake_prompt = "Source" + " Text:"
    pdf_path = create_simple_text_pdf(tmp_path / "secret_model.pdf", f"{fake_key}\n{fake_prompt}")

    model = build_pdf_document_model(pdf_path)
    metrics = model_to_public_metrics(model)

    assert metrics["page_count"] == 1
    assert metrics["text_block_count"] >= 1
    assert fake_key not in repr(metrics)
    assert fake_prompt not in repr(metrics)


def test_existing_pdf_baseline_metrics_still_pass(tmp_path):
    pdf_path = create_simple_text_pdf(tmp_path / "compatibility.pdf", "Hello world")

    model = build_pdf_document_model(pdf_path)
    blocks = collect_text_blocks_from_model(model)

    assert len(blocks) >= 1
    assert blocks[0]["text"] == "Hello world"
