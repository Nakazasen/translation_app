import fitz

from tests.helpers.pdf_fixtures import (
    create_formula_like_pdf,
    create_image_caption_pdf,
    create_scanned_image_pdf,
    create_simple_text_pdf,
    create_table_like_pdf,
)
from translation_app.core.file_handlers.pdf_model import build_pdf_document_model
from translation_app.core.file_handlers.pdf_translation_plan import (
    PDFTranslationPlan,
    PDFTranslationUnit,
    build_pdf_translation_plan,
    get_skipped_units,
    get_translatable_units,
    plan_to_public_summary,
    validate_translation_plan,
)


def _make_adjacent_paragraph_pdf(path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(72, 72, 320, 102), "First paragraph line", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(72, 104, 320, 134), "Second paragraph line", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(72, 220, 320, 250), "Separate paragraph", fontsize=12, fontname="helv")
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


def test_translation_plan_builds_units_from_simple_pdf(tmp_path):
    pdf_path = create_simple_text_pdf(tmp_path / "simple.pdf", "Hello world")

    model = build_pdf_document_model(pdf_path)
    plan = build_pdf_translation_plan(model)
    units = get_translatable_units(plan)

    assert plan.page_count == 1
    assert units
    assert [unit.reading_order for unit in units] == sorted(unit.reading_order for unit in units)
    assert units[0].text == "Hello world"
    assert "translatable" in units[0].flags


def test_translation_plan_uses_paragraph_candidates(tmp_path):
    pdf_path = tmp_path / "paragraphs.pdf"
    _make_adjacent_paragraph_pdf(pdf_path)

    model = build_pdf_document_model(pdf_path)
    plan = build_pdf_translation_plan(model, use_paragraph_candidates=True)
    units = get_translatable_units(plan)

    assert len(units) == 2
    assert units[0].unit_type == "paragraph"
    assert units[0].source_block_ids != []
    assert len(units[0].source_block_ids) == 2
    assert units[0].text == "First paragraph line\nSecond paragraph line"


def test_translation_plan_skips_formula_and_table_regions(tmp_path):
    formula_path = create_formula_like_pdf(tmp_path / "formula.pdf")
    table_path = create_table_like_pdf(tmp_path / "table.pdf")

    formula_plan = build_pdf_translation_plan(build_pdf_document_model(formula_path))
    table_plan = build_pdf_translation_plan(build_pdf_document_model(table_path))

    assert get_translatable_units(formula_plan) == []
    assert any("formula_skipped" in unit.flags for unit in get_skipped_units(formula_plan))
    assert any("table_skipped" in unit.flags for unit in get_skipped_units(table_plan))
    assert all("formula_skipped" not in unit.flags for unit in get_translatable_units(table_plan))


def test_translation_plan_keeps_caption_as_translatable_caption_unit(tmp_path):
    pdf_path = create_image_caption_pdf(tmp_path / "caption.pdf", caption_text="Figure 1: Chart sample")

    model = build_pdf_document_model(pdf_path)
    plan = build_pdf_translation_plan(model)
    units = get_translatable_units(plan)
    skipped = get_skipped_units(plan)

    caption_units = [unit for unit in units if unit.unit_type == "caption"]
    assert caption_units
    assert "caption" in caption_units[0].flags
    assert "translatable" in caption_units[0].flags
    assert caption_units[0].metadata.get("caption_for_block_id")
    assert any("image_skipped" in unit.flags for unit in skipped)


def test_translation_plan_two_column_order_left_then_right(tmp_path):
    pdf_path = tmp_path / "two_column.pdf"
    _make_true_two_column_pdf(pdf_path)

    plan = build_pdf_translation_plan(build_pdf_document_model(pdf_path), use_paragraph_candidates=False)
    units = get_translatable_units(plan)

    assert [unit.text for unit in units] == ["LEFT A", "LEFT B", "RIGHT A", "RIGHT B"]
    assert [unit.reading_order for unit in units] == [0, 1, 2, 3]


def test_translation_plan_scanned_pdf_has_no_translatable_units(tmp_path):
    pdf_path = create_scanned_image_pdf(tmp_path / "scanned.pdf")

    plan = build_pdf_translation_plan(build_pdf_document_model(pdf_path))

    assert get_translatable_units(plan) == []
    assert "scanned_or_image_only_pdf" in plan.warnings


def test_translation_plan_public_summary_safe(tmp_path):
    fake_key = "AI" + "za" + "-FAKE-KEY"
    fake_prompt = "Source" + " Text:"
    pdf_path = create_simple_text_pdf(tmp_path / "safe.pdf", f"{fake_key}\n{fake_prompt}")

    plan = build_pdf_translation_plan(build_pdf_document_model(pdf_path))
    summary = plan_to_public_summary(plan)

    assert summary["unit_count"] >= 1
    assert "warnings" in summary
    assert fake_key not in repr(summary)
    assert fake_prompt not in repr(summary)
    assert "Hello world" not in repr(summary)


def test_translation_plan_validation_detects_missing_bbox_or_duplicate_ids():
    bad_bbox_unit = PDFTranslationUnit(
        unit_id="dup-id",
        page_index=0,
        source_block_ids=["p0-b0"],
        source_span_ids=[],
        bbox=(0.0, 0.0, 0.0, 0.0),
        text="Text",
        reading_order=0,
        unit_type="single_block",
    )
    duplicate_unit = PDFTranslationUnit(
        unit_id="dup-id",
        page_index=0,
        source_block_ids=["p0-b1"],
        source_span_ids=[],
        bbox=(1.0, 1.0, 2.0, 2.0),
        text="Other",
        reading_order=1,
        unit_type="single_block",
    )
    plan = PDFTranslationPlan(
        document_id="sample.pdf",
        page_count=1,
        units=[bad_bbox_unit],
        skipped_units=[duplicate_unit],
    )

    errors = validate_translation_plan(plan)

    assert any(error.startswith("missing_or_invalid_bbox:dup-id") for error in errors)
    assert any(error.startswith("duplicate_unit_id:dup-id") for error in errors)
