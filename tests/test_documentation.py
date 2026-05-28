from pathlib import Path

from translation_app.core.encoding_utils import detect_mojibake


DOC_PATH = Path(__file__).parent.parent / "docs" / "pdf_report_workflow.md"


def test_pdf_docs_explain_experimental_vs_stable():
    content = DOC_PATH.read_text(encoding="utf-8")

    assert "PDF -> DOCX ổn định" in content
    assert "PDF thử nghiệm" in content
    assert "JSON" in content
    assert "HTML" in content


def test_pdf_docs_explain_report_statuses():
    content = DOC_PATH.read_text(encoding="utf-8")

    assert "pass" in content
    assert "warning" in content
    assert "fail" in content
    assert "page count mismatch" in content or "page_count_mismatch" in content


def test_pdf_docs_explain_key_metrics():
    content = DOC_PATH.read_text(encoding="utf-8")

    required_terms = (
        "translated_units",
        "skipped_units",
        "skipped_protected_blocks",
        "overflow_units",
        "overflow_blocks",
        "protected_regions_by_kind",
        "visual_status",
        "visual_mean_diff_ratio",
        "visual_max_diff_ratio",
    )
    for term in required_terms:
        assert term in content


def test_pdf_docs_avoid_overclaim_wording():
    content = DOC_PATH.read_text(encoding="utf-8")

    assert "không đảm bảo giữ layout tuyệt đối" in content
    assert "không tương đương Google Document Translation" in content
    assert "không phải chứng nhận enterprise" in content

    banned_phrases = (
        "giữ nguyên PDF",
        "layout chính xác",
        "bảo toàn 100%",
    )
    for banned in banned_phrases:
        assert banned not in content


def test_pdf_docs_no_mojibake():
    content = DOC_PATH.read_text(encoding="utf-8")

    assert not detect_mojibake(content)
