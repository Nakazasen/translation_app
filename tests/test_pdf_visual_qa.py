import subprocess
import sys

import fitz

from tests.helpers.pdf_fixtures import FakeTranslationService, create_simple_text_pdf, create_two_page_pdf
from translation_app.core.file_handlers.pdf_handler import PDFHandler
from translation_app.core.file_handlers.pdf_qa_report import build_pdf_qa_report, merge_visual_diff_into_pdf_qa_report
from translation_app.core.file_handlers.pdf_visual_qa import (
    compare_pdf_visual_snapshots,
    render_pdf_snapshots,
    result_to_public_dict,
)


def _make_position_shifted_pdf(path, text: str, rect: fitz.Rect) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(rect, text, fontsize=14, fontname="helv")
    doc.save(path)
    doc.close()


def test_render_pdf_snapshots_simple_text(tmp_path):
    pdf_path = create_simple_text_pdf(tmp_path / "simple.pdf", "Hello snapshot")

    snapshots = render_pdf_snapshots(str(pdf_path))

    assert len(snapshots) == 1
    assert snapshots[0].page_index == 0
    assert snapshots[0].width > 0
    assert snapshots[0].height > 0
    assert snapshots[0].hash
    assert snapshots[0].render_dpi == 72


def test_visual_diff_identical_pdf_is_low(tmp_path):
    pdf_path = create_simple_text_pdf(tmp_path / "same.pdf", "Stable content")

    result = compare_pdf_visual_snapshots(str(pdf_path), str(pdf_path))

    assert result.page_count_match is True
    assert result.pages_compared == 1
    assert result.mean_diff_ratio == 0.0
    assert result.max_diff_ratio == 0.0


def test_visual_diff_detects_changed_output(tmp_path):
    before_path = tmp_path / "before.pdf"
    after_path = tmp_path / "after.pdf"
    _make_position_shifted_pdf(before_path, "Original text", fitz.Rect(72, 72, 320, 180))
    _make_position_shifted_pdf(after_path, "Translated text", fitz.Rect(92, 96, 340, 210))

    result = compare_pdf_visual_snapshots(str(before_path), str(after_path))

    assert result.page_count_match is True
    assert result.pages_compared == 1
    assert result.mean_diff_ratio > 0.0
    assert result.max_diff_ratio > 0.0


def test_visual_diff_detects_page_count_mismatch(tmp_path):
    before_path = create_simple_text_pdf(tmp_path / "one_page.pdf", "One page")
    after_path = create_two_page_pdf(tmp_path / "two_page.pdf", ["One page", "Two page"])

    result = compare_pdf_visual_snapshots(str(before_path), str(after_path))

    assert result.page_count_match is False
    assert "page_count_mismatch" in result.warnings


def test_visual_diff_public_dict_safe(tmp_path):
    before_path = create_simple_text_pdf(tmp_path / "public_before.pdf", "Safe public text")
    after_path = create_simple_text_pdf(tmp_path / "public_after.pdf", "Changed public text")

    result = compare_pdf_visual_snapshots(str(before_path), str(after_path))
    public = result_to_public_dict(result)

    assert "hash" not in repr(public)
    assert "image_bytes" not in repr(public)
    assert "api_key" not in repr(public)
    assert "Authorization" not in repr(public)
    assert "prompt" not in repr(public)
    assert "Safe public text" not in repr(public)


def test_pdf_experimental_output_visual_diff_smoke(tmp_path):
    input_path = create_simple_text_pdf(tmp_path / "input.pdf", "Hello world")
    output_path = tmp_path / "output.pdf"

    service = FakeTranslationService(translations={"Hello world": "Xin chao the gioi"})
    handler = PDFHandler(service)
    try:
        handler.translate_to_pdf_experimental(str(input_path), str(output_path), "en", "vi")
    finally:
        service.executor.shutdown(wait=True)

    result = compare_pdf_visual_snapshots(str(input_path), str(output_path))
    report = build_pdf_qa_report(
        input_file=str(input_path),
        output_file=str(output_path),
        mode="experimental_pdf",
        page_count=1,
        translated_blocks=1,
        engine_version="phase_5h7",
    )
    merged_report = merge_visual_diff_into_pdf_qa_report(report, result_to_public_dict(result))

    assert result.page_count_match is True
    assert result.pages_compared == 1
    assert "mean_diff_ratio" in result_to_public_dict(result)
    assert merged_report.warning_count >= 0


def test_visual_qa_no_mojibake():
    result = subprocess.run(
        [sys.executable, "tools/check_mojibake.py"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Found 0 issues" in result.stdout
