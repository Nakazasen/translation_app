import fitz

from tests.helpers.pdf_fixtures import create_image_caption_pdf
from translation_app.core.file_handlers.pdf_model import build_pdf_document_model, collect_text_blocks_from_model
from translation_app.core.file_handlers.pdf_reading_order import (
    build_paragraph_candidates,
    model_to_reading_order_summary,
    paragraph_candidates_to_public_summary,
)


def _make_single_column_blocks_pdf(path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(72, 72, 280, 105), "Top block", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(72, 136, 280, 169), "Middle block", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(72, 200, 280, 233), "Bottom block", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def _make_true_two_column_pdf(path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(50, 60, 220, 96), "LEFT A", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(320, 72, 520, 108), "RIGHT A", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(50, 132, 220, 168), "LEFT B", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(320, 144, 520, 180), "RIGHT B", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def _make_ambiguous_layout_pdf(path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(50, 60, 220, 96), "LEFT BLOCK", fontsize=12, fontname="helv")
    page.insert_textbox(
        fitz.Rect(110, 116, 520, 168),
        "CENTER WIDE BLOCK CROSSING THE PAGE MIDPOINT",
        fontsize=16,
        fontname="helv",
    )
    page.insert_textbox(fitz.Rect(320, 180, 520, 216), "RIGHT BLOCK", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def _make_adjacent_paragraph_pdf(path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(72, 72, 320, 102), "First paragraph line", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(72, 104, 320, 134), "Second paragraph line", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(72, 220, 320, 250), "Separate paragraph", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def _make_formula_barrier_pdf(path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(72, 72, 320, 102), "Intro text", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(72, 112, 320, 154), "E = mc^2", fontsize=12, fontname="cour")
    page.insert_textbox(fitz.Rect(72, 160, 320, 190), "Outro text", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def _make_table_caption_pdf(path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(72, 72, 360, 160),
        "Item   Qty   Price\nApple   2   10\nBanana   5   8",
        fontsize=12,
        fontname="cour",
    )
    page.insert_textbox(
        fitz.Rect(72, 172, 360, 206),
        "Table 1: Inventory sample",
        fontsize=12,
        fontname="helv",
    )
    doc.save(path)
    doc.close()


def test_reading_order_single_column_is_top_to_bottom(tmp_path):
    pdf_path = tmp_path / "single_column.pdf"
    _make_single_column_blocks_pdf(pdf_path)

    model = build_pdf_document_model(pdf_path)
    blocks = collect_text_blocks_from_model(model)

    assert [block["text"] for block in blocks] == ["Top block", "Middle block", "Bottom block"]
    assert [block["reading_order"] for block in blocks] == [0, 1, 2]


def test_reading_order_two_column_reads_left_column_then_right_column(tmp_path):
    pdf_path = tmp_path / "two_column.pdf"
    _make_true_two_column_pdf(pdf_path)

    model = build_pdf_document_model(pdf_path)
    blocks = collect_text_blocks_from_model(model)

    assert [block["text"] for block in blocks] == ["LEFT A", "LEFT B", "RIGHT A", "RIGHT B"]
    assert [block["column_index"] for block in blocks] == [0, 0, 1, 1]


def test_reading_order_ambiguous_layout_sets_warning_or_fallback(tmp_path):
    pdf_path = tmp_path / "ambiguous.pdf"
    _make_ambiguous_layout_pdf(pdf_path)

    model = build_pdf_document_model(pdf_path)
    summary = model_to_reading_order_summary(model)
    blocks = collect_text_blocks_from_model(model)

    assert [block["text"] for block in blocks] == [
        "LEFT BLOCK",
        "CENTER WIDE BLOCK CROSSING THE PAGE\nMIDPOINT",
        "RIGHT BLOCK",
    ]
    assert summary["ambiguous_page_count"] == 1
    assert "ambiguous_reading_order" in summary["pages"][0]["warnings"]


def test_paragraph_candidates_group_adjacent_lines(tmp_path):
    pdf_path = tmp_path / "paragraphs.pdf"
    _make_adjacent_paragraph_pdf(pdf_path)

    model = build_pdf_document_model(pdf_path)
    candidates = build_paragraph_candidates(model)

    assert len(candidates) == 2
    assert candidates[0].block_ids != []
    assert len(candidates[0].block_ids) == 2
    assert candidates[0].text == "First paragraph line\nSecond paragraph line"
    assert candidates[1].text == "Separate paragraph"


def test_paragraph_candidates_do_not_merge_protected_formula_or_table(tmp_path):
    pdf_path = tmp_path / "formula_barrier.pdf"
    _make_formula_barrier_pdf(pdf_path)

    model = build_pdf_document_model(pdf_path)
    candidates = build_paragraph_candidates(model)
    formula_blocks = {
        block.block_id
        for page in model.pages
        for block in page.blocks
        if "formula_like" in block.flags
    }

    assert len(candidates) == 2
    assert formula_blocks
    assert all(not formula_blocks.intersection(candidate.block_ids) for candidate in candidates)
    assert [candidate.text for candidate in candidates] == ["Intro text", "Outro text"]


def test_caption_relationship_near_image_or_table(tmp_path):
    image_path = create_image_caption_pdf(tmp_path / "image_caption.pdf", caption_text="Figure 1: Chart sample")
    table_path = tmp_path / "table_caption.pdf"
    _make_table_caption_pdf(table_path)

    image_model = build_pdf_document_model(image_path)
    table_model = build_pdf_document_model(table_path)

    image_caption = next(
        block
        for page in image_model.pages
        for block in page.blocks
        if block.kind == "text" and "caption_like" in block.flags
    )
    table_caption = next(
        block
        for page in table_model.pages
        for block in page.blocks
        if block.kind == "text" and "caption_like" in block.flags
    )

    assert image_caption.metadata.get("caption_for_block_id")
    assert table_caption.metadata.get("caption_for_block_id")
    assert "related_block_ids" in image_caption.metadata
    assert "related_block_ids" in table_caption.metadata


def test_reading_order_public_summary_safe(tmp_path):
    fake_key = "AI" + "za" + "-FAKE-KEY"
    fake_prompt = "Source" + " Text:"
    pdf_path = tmp_path / "safe_summary.pdf"

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(72, 72, 320, 140), f"{fake_key}\n{fake_prompt}", fontsize=12, fontname="helv")
    doc.save(pdf_path)
    doc.close()

    model = build_pdf_document_model(pdf_path)
    reading_summary = model_to_reading_order_summary(model)
    paragraph_summary = paragraph_candidates_to_public_summary(build_paragraph_candidates(model))

    assert reading_summary["page_count"] == 1
    assert paragraph_summary["paragraph_candidate_count"] >= 1
    assert fake_key not in repr(reading_summary)
    assert fake_prompt not in repr(reading_summary)
    assert fake_key not in repr(paragraph_summary)
    assert fake_prompt not in repr(paragraph_summary)
