import json
import subprocess
import sys

from tests.helpers.pdf_fixtures import create_simple_text_pdf
from translation_app.core.file_handlers.pdf_protection import detect_protected_regions, model_to_protection_summary
from translation_app.core.file_handlers.pdf_qa_report import build_pdf_qa_report, report_to_public_dict
from translation_app.core.file_handlers.pdf_regression_report import (
    build_pdf_regression_report_bundle,
    bundle_to_public_dict,
    export_pdf_regression_report_html,
    export_pdf_regression_report_json,
)
from translation_app.core.file_handlers.pdf_translation_plan import build_pdf_translation_plan, plan_to_public_summary
from translation_app.core.file_handlers.pdf_visual_qa import (
    PDFVisualDiffResult,
    evaluate_visual_diff,
    result_to_public_dict,
    visual_evaluation_to_public_dict,
)
from translation_app.core.file_handlers.pdf_model import build_pdf_document_model


def _make_bundle(**overrides):
    qa_report = report_to_public_dict(
        build_pdf_qa_report(
            input_file=r"C:\sensitive\client_a\input.pdf",
            output_file=r"C:\sensitive\client_a\output.pdf",
            mode="experimental_pdf",
            page_count=1,
            translated_units=1,
            translated_blocks=2,
            skipped_units=1,
            overflow_units=0,
            warning_count=1,
            warnings_by_type={"font_shrunk": 1},
            protected_regions_by_kind={"formula": 1},
            visual_status="warning",
            visual_warnings=["high_mean_visual_diff"],
            visual_mean_diff_ratio=0.2,
            visual_max_diff_ratio=0.3,
            engine_version="phase_5h12",
        )
    )
    bundle = build_pdf_regression_report_bundle(
        qa_report=qa_report,
        visual_diff={
            "page_count_match": True,
            "mean_diff_ratio": 0.2,
            "max_diff_ratio": 0.3,
            "safe_summary": {"pages": [{"diff_ratio": 0.2}]},
        },
        visual_evaluation={
            "status": "warning",
            "warnings": ["high_mean_visual_diff"],
            "failures": [],
            "mean_diff_ratio": 0.2,
            "max_diff_ratio": 0.3,
        },
        translation_plan_summary={"unit_count": 2, "warning_count": 0},
        protection_summary={"counts_by_kind": {"formula": 1}},
        metadata={
            "engine_version": "phase_5h12",
            "input_file": r"C:\sensitive\client_a\input.pdf",
            "output_file": r"C:\sensitive\client_a\output.pdf",
        },
    )
    for key, value in overrides.items():
        setattr(bundle, key, value)
    return bundle


def test_export_pdf_regression_report_json(tmp_path):
    bundle = _make_bundle()
    output_path = tmp_path / "reports" / "report.json"

    export_pdf_regression_report_json(bundle, output_path)

    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "pdf_regression_report"
    assert payload["schema_version"] == "1"
    assert payload["qa_report"]["translated_units"] == 1
    assert payload["metadata"]["input_file"] == "input.pdf"


def test_export_pdf_regression_report_html(tmp_path):
    bundle = _make_bundle(
        visual_evaluation={
            "status": "warning",
            "warnings": ["<script>alert(1)</script>"],
            "failures": [],
            "mean_diff_ratio": 0.2,
            "max_diff_ratio": 0.3,
        }
    )
    output_path = tmp_path / "reports" / "report.html"

    export_pdf_regression_report_html(bundle, output_path)

    html = output_path.read_text(encoding="utf-8")
    assert output_path.exists()
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "PDF Regression Report" in html


def test_regression_report_sanitizes_secret_like_values(tmp_path):
    bundle = _make_bundle(
        visual_diff={
            "hash": "abcd",
            "image_bytes": "raw",
            "prompt": "translate this",
            "Authorization": "Bearer sk-secret",
            "token": "AIza-SECRET",
            "safe_summary": {"text": "raw text"},
        }
    )
    output_path = tmp_path / "sanitized.json"

    export_pdf_regression_report_json(bundle, output_path)

    public = json.loads(output_path.read_text(encoding="utf-8"))
    assert "hash" not in repr(public)
    assert "image_bytes" not in repr(public)
    assert "prompt" not in repr(public)
    assert "Authorization" not in repr(public)
    assert "AIza" not in repr(public)
    assert "sk-secret" not in repr(public)


def test_regression_report_uses_basename_not_full_sensitive_path():
    public = bundle_to_public_dict(_make_bundle())

    assert public["metadata"]["input_file"] == "input.pdf"
    assert public["metadata"]["output_file"] == "output.pdf"
    assert public["qa_report"]["input_file"] == "input.pdf"
    assert public["qa_report"]["output_file"] == "output.pdf"
    assert "client_a" not in repr(public)


def test_regression_report_can_include_visual_evaluation():
    evaluation = visual_evaluation_to_public_dict(
        evaluate_visual_diff(
            PDFVisualDiffResult(
                page_count_before=1,
                page_count_after=2,
                page_count_match=False,
                dimension_mismatches=0,
                mean_diff_ratio=0.0,
                max_diff_ratio=0.0,
                pages_compared=1,
                warnings=["page_count_mismatch"],
                safe_summary={"render_dpi": 72, "pages": []},
            )
        )
    )
    public = bundle_to_public_dict(_make_bundle(visual_evaluation=evaluation))

    assert public["visual_evaluation"]["status"] == "fail"
    assert "page_count_mismatch" in public["visual_evaluation"]["failures"]


def test_regression_report_can_include_translation_plan_summary(tmp_path):
    pdf_path = create_simple_text_pdf(tmp_path / "plan.pdf", "Hello bundle")
    model = build_pdf_document_model(pdf_path)
    plan_summary = plan_to_public_summary(build_pdf_translation_plan(model))

    public = bundle_to_public_dict(_make_bundle(translation_plan_summary=plan_summary))

    assert public["translation_plan_summary"]["unit_count"] >= 1
    assert "Hello bundle" not in repr(public)
    assert "source_span_ids" not in repr(public)


def test_regression_report_no_mojibake(tmp_path):
    pdf_path = create_simple_text_pdf(tmp_path / "safe.pdf", "Xin chao")
    model = build_pdf_document_model(pdf_path)
    regions = detect_protected_regions(model)
    bundle = _make_bundle(
        protection_summary=model_to_protection_summary(model, regions),
        metadata={
            "engine_version": "phase_5h12",
            "label": "Bao cao tieng Viet / 日本語",
            "input_file": str(pdf_path),
            "output_file": str(pdf_path),
        },
    )
    output_path = tmp_path / "utf8-report.json"

    export_pdf_regression_report_json(bundle, output_path)

    payload = output_path.read_text(encoding="utf-8")
    assert "Bao cao tieng Viet / 日本語" in payload

    result = subprocess.run(
        [sys.executable, "tools/check_mojibake.py"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Found 0 issues" in result.stdout
