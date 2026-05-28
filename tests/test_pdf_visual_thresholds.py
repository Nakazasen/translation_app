import fitz

from tests.helpers.pdf_fixtures import (
    FakeTranslationService,
    create_formula_like_pdf,
    create_simple_text_pdf,
    create_two_page_pdf,
)
from translation_app.core.file_handlers.pdf_handler import PDFHandler
from translation_app.core.file_handlers.pdf_qa_report import build_pdf_qa_report, report_to_public_dict
from translation_app.core.file_handlers.pdf_visual_qa import (
    PDFVisualQAThresholds,
    compare_pdf_visual_snapshots,
    evaluate_visual_diff,
    merge_visual_evaluation_into_pdf_qa_report,
    visual_evaluation_to_public_dict,
)


def _make_sized_pdf(path, text: str, width: float, height: float) -> None:
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.insert_textbox(fitz.Rect(72, 72, min(width - 72, 320), min(height - 72, 180)), text, fontsize=14, fontname="helv")
    doc.save(path)
    doc.close()


def _make_different_pdf(path, text: str, rect: fitz.Rect) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(rect, text, fontsize=18, fontname="cour")
    doc.save(path)
    doc.close()


def test_visual_evaluation_identical_pdf_passes(tmp_path):
    pdf_path = create_simple_text_pdf(tmp_path / "same.pdf", "Stable content")

    result = compare_pdf_visual_snapshots(str(pdf_path), str(pdf_path))
    evaluation = evaluate_visual_diff(result)

    assert evaluation.status == "pass"
    assert evaluation.failures == []
    assert evaluation.warnings == []


def test_visual_evaluation_page_count_mismatch_fails(tmp_path):
    before_path = create_simple_text_pdf(tmp_path / "one_page.pdf", "One page")
    after_path = create_two_page_pdf(tmp_path / "two_page.pdf", ["One page", "Two page"])

    evaluation = evaluate_visual_diff(compare_pdf_visual_snapshots(str(before_path), str(after_path)))

    assert evaluation.status == "fail"
    assert "page_count_mismatch" in evaluation.failures


def test_visual_evaluation_dimension_mismatch_warns_or_fails(tmp_path):
    before_path = tmp_path / "before_size.pdf"
    after_path = tmp_path / "after_size.pdf"
    _make_sized_pdf(before_path, "Same text", 595, 842)
    _make_sized_pdf(after_path, "Same text", 700, 842)

    result = compare_pdf_visual_snapshots(str(before_path), str(after_path))
    strict = evaluate_visual_diff(result)
    relaxed = evaluate_visual_diff(
        result,
        PDFVisualQAThresholds(allow_dimension_mismatch=True),
    )

    assert result.dimension_mismatches > 0
    assert strict.status == "fail"
    assert "page_dimension_mismatch" in strict.failures
    assert relaxed.status in {"warning", "fail"}
    assert "page_dimension_mismatch" in relaxed.warnings


def test_visual_evaluation_high_diff_warns_or_fails(tmp_path):
    before_path = tmp_path / "before.pdf"
    after_path = tmp_path / "after.pdf"
    _make_different_pdf(before_path, "Original paragraph", fitz.Rect(72, 72, 320, 180))
    _make_different_pdf(after_path, "Completely changed translation", fitz.Rect(180, 240, 520, 420))

    result = compare_pdf_visual_snapshots(str(before_path), str(after_path))
    evaluation = evaluate_visual_diff(
        result,
        PDFVisualQAThresholds(
            warning_mean_diff_ratio=0.001,
            fail_mean_diff_ratio=0.01,
            warning_max_diff_ratio=0.001,
            fail_max_diff_ratio=0.01,
        ),
    )

    assert result.mean_diff_ratio > 0.0
    assert evaluation.status in {"warning", "fail"}
    assert evaluation.warnings or evaluation.failures


def test_visual_evaluation_public_dict_safe(tmp_path):
    before_path = create_simple_text_pdf(tmp_path / "safe_before.pdf", "AIza-FAKE-KEY\nprompt text")
    after_path = create_simple_text_pdf(tmp_path / "safe_after.pdf", "Different content")

    evaluation = evaluate_visual_diff(compare_pdf_visual_snapshots(str(before_path), str(after_path)))
    public = visual_evaluation_to_public_dict(evaluation)

    assert "hash" not in repr(public)
    assert "image_bytes" not in repr(public)
    assert "api_key" not in repr(public)
    assert "Authorization" not in repr(public)
    assert "prompt" not in repr(public)
    assert "AIza-FAKE-KEY" not in repr(public)


def test_visual_thresholds_merge_into_qa_report_public_safe(tmp_path):
    before_path = create_simple_text_pdf(tmp_path / "merge_before.pdf", "Before text")
    after_path = create_simple_text_pdf(tmp_path / "merge_after.pdf", "After text")

    evaluation = evaluate_visual_diff(compare_pdf_visual_snapshots(str(before_path), str(after_path)))
    report = build_pdf_qa_report(
        input_file=str(before_path),
        output_file=str(after_path),
        mode="experimental_pdf",
        page_count=1,
    )
    merged = merge_visual_evaluation_into_pdf_qa_report(report, evaluation)
    public = report_to_public_dict(merged)

    assert public["visual_status"] in {"pass", "warning", "fail"}
    assert "visual_warnings" in public
    assert "visual_failures" in public
    assert "visual_mean_diff_ratio" in public
    assert "visual_max_diff_ratio" in public
    assert "Before text" not in repr(public)
    assert "After text" not in repr(public)
    assert "prompt" not in repr(public)


def test_experimental_output_visual_evaluation_smoke(tmp_path):
    input_path = create_simple_text_pdf(tmp_path / "input.pdf", "Hello world")
    output_path = tmp_path / "output.pdf"

    service = FakeTranslationService(translations={"Hello world": "Xin chao the gioi"})
    handler = PDFHandler(service)
    try:
        handler.translate_to_pdf_experimental(str(input_path), str(output_path), "en", "vi")
    finally:
        service.executor.shutdown(wait=True)

    result = compare_pdf_visual_snapshots(str(input_path), str(output_path))
    evaluation = evaluate_visual_diff(result)
    public = visual_evaluation_to_public_dict(evaluation)

    assert "page_count_mismatch" not in evaluation.failures
    assert evaluation.status in {"pass", "warning"}
    assert public["page_count_match"] is True
    assert "hash" not in repr(public)
    assert "Hello world" not in repr(public)


def test_protected_formula_fixture_visual_metrics_generated(tmp_path):
    pdf_path = create_formula_like_pdf(tmp_path / "formula.pdf")

    result = compare_pdf_visual_snapshots(str(pdf_path), str(pdf_path))
    evaluation = evaluate_visual_diff(result)

    assert result.pages_compared == 1
    assert evaluation.status == "pass"
    assert evaluation.page_count_match is True
