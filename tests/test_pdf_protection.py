import pytest

from tests.helpers.pdf_fixtures import (
    create_formula_like_pdf,
    create_image_caption_pdf,
    create_noisy_text_pdf,
    create_scanned_image_pdf,
    create_simple_text_pdf,
    create_table_like_pdf,
)
from translation_app.core.file_handlers.pdf_model import build_pdf_document_model
from translation_app.core.file_handlers.pdf_protection import (
    apply_protected_flags,
    detect_protected_regions,
    get_translatable_blocks,
    is_block_protected,
    model_to_protection_summary,
)


def test_detects_formula_like_regions(tmp_path):
    pdf_path = create_formula_like_pdf(tmp_path / "formula_protection.pdf")

    model = build_pdf_document_model(pdf_path)
    regions = detect_protected_regions(model)
    apply_protected_flags(model, regions)

    formula_regions = [region for region in regions if region.kind == "formula"]
    assert formula_regions

    formula_block_ids = {block_id for region in formula_regions for block_id in region.source_block_ids}
    flagged_blocks = [
        block
        for page in model.pages
        for block in page.blocks
        if block.block_id in formula_block_ids
    ]
    assert flagged_blocks
    assert any("formula_like" in block.flags for block in flagged_blocks)
    assert any("protected" in block.flags for block in flagged_blocks)


def test_detects_image_regions(tmp_path):
    pdf_path = create_image_caption_pdf(tmp_path / "image_protection.pdf")

    model = build_pdf_document_model(pdf_path)
    regions = detect_protected_regions(model)
    apply_protected_flags(model, regions)

    assert any(region.kind in {"image", "drawing"} for region in regions)
    caption_blocks = [
        block
        for page in model.pages
        for block in page.blocks
        if "caption_like" in block.flags
    ]
    assert caption_blocks
    assert all("protected" not in block.flags for block in caption_blocks)


def test_detects_table_like_regions(tmp_path):
    pdf_path = create_table_like_pdf(tmp_path / "table_protection.pdf")

    model = build_pdf_document_model(pdf_path)
    regions = detect_protected_regions(model)
    apply_protected_flags(model, regions)

    table_regions = [region for region in regions if region.kind == "table"]
    assert table_regions
    protected_blocks = [
        block
        for page in model.pages
        for block in page.blocks
        if any(block.block_id in region.source_block_ids for region in table_regions)
    ]
    assert protected_blocks
    assert all("table_like" in block.flags for block in protected_blocks)
    assert any("protected" in block.flags for block in protected_blocks)


def test_detects_scanned_page_region(tmp_path):
    pdf_path = create_scanned_image_pdf(tmp_path / "scanned_protection.pdf")

    model = build_pdf_document_model(pdf_path)
    regions = detect_protected_regions(model)
    apply_protected_flags(model, regions)

    scanned_regions = [region for region in regions if region.kind == "scanned_page"]
    assert len(scanned_regions) == 1
    assert get_translatable_blocks(model, regions, exclude_protected=True) == []


def test_noisy_blocks_are_not_translatable(tmp_path):
    pdf_path = create_noisy_text_pdf(tmp_path / "noisy_protection.pdf")

    model = build_pdf_document_model(pdf_path)
    regions = detect_protected_regions(model)
    apply_protected_flags(model, regions)

    noisy_regions = [region for region in regions if region.kind == "noisy"]
    assert noisy_regions

    noisy_block_ids = {block_id for region in noisy_regions for block_id in region.source_block_ids}
    noisy_blocks = [
        block
        for page in model.pages
        for block in page.blocks
        if block.block_id in noisy_block_ids
    ]
    assert noisy_blocks
    assert all("translatable" not in block.flags for block in noisy_blocks)
    assert any(block.text == "Stable text block" for block in get_translatable_blocks(model, regions))


def test_protection_summary_is_public_and_safe(tmp_path):
    fake_key = "AI" + "za" + "-FAKE-KEY"
    fake_prompt = "Source" + " Text:"
    pdf_path = create_simple_text_pdf(tmp_path / "safe_summary.pdf", f"{fake_key}\n{fake_prompt}")

    model = build_pdf_document_model(pdf_path)
    regions = detect_protected_regions(model)
    summary = model_to_protection_summary(model, regions)

    assert summary["page_count"] == 1
    assert "counts_by_kind" in summary
    assert fake_key not in repr(summary)
    assert fake_prompt not in repr(summary)


@pytest.mark.parametrize(
    ("caption_text", "expected_region_kind"),
    [
        ("Figure 1: Sample chart", "chart"),
        ("H\u00ecnh 1: Sample chart", "chart"),
        ("\u56f31: Sample chart", "chart"),
        ("\u88681: Sample chart", "chart"),
    ],
)
def test_caption_detection_multilingual(tmp_path, caption_text, expected_region_kind):
    pdf_path = create_image_caption_pdf(tmp_path / "caption_cue.pdf", caption_text=caption_text)

    model = build_pdf_document_model(pdf_path)
    regions = detect_protected_regions(model)
    apply_protected_flags(model, regions)

    assert any(region.kind == "caption" for region in regions)
    assert any(region.kind == expected_region_kind for region in regions)


def test_blocks_with_protected_regions_are_detectable(tmp_path):
    pdf_path = create_formula_like_pdf(tmp_path / "protected_lookup.pdf")

    model = build_pdf_document_model(pdf_path)
    regions = detect_protected_regions(model)
    apply_protected_flags(model, regions)

    protected_blocks = [
        block
        for page in model.pages
        for block in page.blocks
        if is_block_protected(block, regions)
    ]
    assert protected_blocks


def test_existing_pdf_model_and_baseline_inputs_still_work(tmp_path):
    pdf_path = create_simple_text_pdf(tmp_path / "compatibility_protection.pdf", "Hello world")

    model = build_pdf_document_model(pdf_path)
    regions = detect_protected_regions(model)
    summary = model_to_protection_summary(model, regions)

    assert summary["page_count"] == 1
    assert summary["translatable_block_count"] >= 1
