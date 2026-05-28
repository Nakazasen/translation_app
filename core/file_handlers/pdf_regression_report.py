"""Public-safe PDF regression report export helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
from typing import Any


REDACTED_VALUE = "[redacted]"
SENSITIVE_KEY_PARTS = {
    "text",
    "prompt",
    "api_key",
    "authorization",
    "hash",
    "image_bytes",
    "grayscale_samples",
    "source_span_ids",
}
SAFE_PATH_KEYS = {"input_file", "output_file", "source_path", "path", "document_id"}
SECRET_MARKERS = ("AIza", "sk-", "Bearer ", "Authorization", "prompt", "source text:", "translated text:")


@dataclass
class PDFRegressionReportBundle:
    qa_report: dict[str, Any]
    visual_diff: dict[str, Any] | None = None
    visual_evaluation: dict[str, Any] | None = None
    translation_plan_summary: dict[str, Any] | None = None
    protection_summary: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _safe_file_label(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).name


def _sanitize_string(value: str) -> str:
    if any(marker.lower() in value.lower() for marker in SECRET_MARKERS):
        return REDACTED_VALUE
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def sanitize_regression_report_dict(data: Any) -> Any:
    if isinstance(data, dict):
        sanitized: dict[str, Any] = {}
        for key, value in data.items():
            key_str = str(key)
            if _is_sensitive_key(key_str):
                continue
            if key_str in SAFE_PATH_KEYS and isinstance(value, str):
                sanitized[key_str] = _safe_file_label(value)
                continue
            sanitized[key_str] = sanitize_regression_report_dict(value)
        return sanitized
    if isinstance(data, list):
        return [sanitize_regression_report_dict(item) for item in data]
    if isinstance(data, tuple):
        return [sanitize_regression_report_dict(item) for item in data]
    if isinstance(data, set):
        return [sanitize_regression_report_dict(item) for item in sorted(data, key=str)]
    if isinstance(data, str):
        return _sanitize_string(data)
    return data


def build_pdf_regression_report_bundle(
    *,
    qa_report: dict[str, Any],
    visual_diff: dict[str, Any] | None = None,
    visual_evaluation: dict[str, Any] | None = None,
    translation_plan_summary: dict[str, Any] | None = None,
    protection_summary: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> PDFRegressionReportBundle:
    base_metadata = {
        "report_type": "pdf_regression_report",
        "schema_version": "1",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base_metadata.update(dict(metadata or {}))
    return PDFRegressionReportBundle(
        qa_report=dict(qa_report),
        visual_diff=dict(visual_diff) if visual_diff is not None else None,
        visual_evaluation=dict(visual_evaluation) if visual_evaluation is not None else None,
        translation_plan_summary=dict(translation_plan_summary) if translation_plan_summary is not None else None,
        protection_summary=dict(protection_summary) if protection_summary is not None else None,
        metadata=base_metadata,
    )


def bundle_to_public_dict(bundle: PDFRegressionReportBundle) -> dict[str, Any]:
    raw = asdict(bundle)
    metadata = dict(raw.get("metadata", {}))
    metadata["input_file"] = _safe_file_label(
        metadata.get("input_file") or raw.get("qa_report", {}).get("input_file")
    )
    metadata["output_file"] = _safe_file_label(
        metadata.get("output_file") or raw.get("qa_report", {}).get("output_file")
    )
    public = {
        "report_type": metadata.pop("report_type", "pdf_regression_report"),
        "schema_version": metadata.pop("schema_version", "1"),
        "metadata": metadata,
        "qa_report": raw.get("qa_report"),
        "visual_diff": raw.get("visual_diff"),
        "visual_evaluation": raw.get("visual_evaluation"),
        "translation_plan_summary": raw.get("translation_plan_summary"),
        "protection_summary": raw.get("protection_summary"),
    }
    return sanitize_regression_report_dict(public)


def export_pdf_regression_report_json(bundle: PDFRegressionReportBundle, output_path: str | Path) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    public = bundle_to_public_dict(bundle)
    destination.write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def _render_html_rows(data: dict[str, Any]) -> str:
    rows: list[str] = []
    for key, value in data.items():
        rendered = escape(json.dumps(value, ensure_ascii=False)) if isinstance(value, (dict, list)) else escape(str(value))
        rows.append(f"<tr><th>{escape(str(key))}</th><td>{rendered}</td></tr>")
    return "".join(rows)


def export_pdf_regression_report_html(bundle: PDFRegressionReportBundle, output_path: str | Path) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    public = bundle_to_public_dict(bundle)
    metadata = dict(public.get("metadata", {}))
    qa_report = dict(public.get("qa_report", {}))
    visual_evaluation = dict(public.get("visual_evaluation") or {})
    protection_summary = dict(public.get("protection_summary") or {})
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>PDF Regression Report</title>
</head>
<body>
  <h1>PDF Regression Report</h1>
  <p>Status: {escape(str(visual_evaluation.get("status", qa_report.get("visual_status", "unknown"))))}</p>
  <table>{_render_html_rows(metadata)}</table>
  <h2>QA Report</h2>
  <table>{_render_html_rows(qa_report)}</table>
  <h2>Visual Evaluation</h2>
  <table>{_render_html_rows(visual_evaluation)}</table>
  <h2>Protected Regions</h2>
  <table>{_render_html_rows(protection_summary)}</table>
</body>
</html>
"""
    destination.write_text(html, encoding="utf-8")
    return destination
