from translation_app.core.file_handlers.pdf_qa_report import (
    PDFQAReport,
    build_pdf_qa_report,
    report_to_public_dict,
    sanitize_pdf_qa_report,
    summarize_pdf_processing,
)


def test_pdf_qa_report_public_dict_has_counts_only():
    report = build_pdf_qa_report(
        input_file=r"C:\temp\input.pdf",
        output_file=r"C:\temp\output.pdf",
        mode="experimental_pdf",
        page_count=2,
        translated_blocks=4,
        skipped_protected_blocks=2,
        skipped_noisy_blocks=1,
        overflow_blocks=1,
        warning_count=3,
        warnings_by_type={"text_overflow": 1, "font_shrunk": 2},
        protected_regions_by_kind={"formula": 1, "table": 1, "image": 1},
        engine_version="phase_5h6",
    )

    public = report_to_public_dict(report)

    assert public["input_file"] == "input.pdf"
    assert public["output_file"] == "output.pdf"
    assert public["page_count"] == 2
    assert public["warnings_by_type"]["text_overflow"] == 1
    assert "Source Text:" not in repr(public)
    assert "Bearer " not in repr(public)


def test_pdf_qa_report_sanitizes_secret_like_values():
    report = PDFQAReport(
        input_file=r"C:\safe\input.pdf",
        output_file=r"C:\safe\output.pdf",
        mode="experimental_pdf",
        page_count=1,
        rejection_reason="Prompt leaked with AIza-secret and Bearer token",
        warnings_by_type={"prompt_details": 1, "text_overflow": 1},
        protected_regions_by_kind={"formula": 1},
    )

    public = report_to_public_dict(sanitize_pdf_qa_report(report))

    assert public["rejection_reason"] == "[redacted]"
    assert "[redacted]" in public["warnings_by_type"]
    assert "AIza" not in repr(public)
    assert "Bearer " not in repr(public)


def test_summarize_pdf_processing_creates_public_safe_report():
    public = summarize_pdf_processing(
        input_file=r"C:\temp\sample.pdf",
        output_file=r"C:\temp\sample_out.pdf",
        mode="experimental_pdf",
        page_count=1,
        translated_blocks=1,
        warning_count=2,
        warnings_by_type={"font_shrunk": 1, "text_overflow": 1},
        protected_regions_by_kind={"formula": 1},
    )

    assert public["input_file"] == "sample.pdf"
    assert public["output_file"] == "sample_out.pdf"
    assert public["translated_blocks"] == 1
    assert public["protected_regions_by_kind"]["formula"] == 1
