"""Public-safe QA report helpers for PDF processing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _safe_file_label(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).name


def _sanitize_text_value(value: str | None) -> str | None:
    if value is None:
        return None
    redaction_markers = ("AIza", "sk-", "Bearer ", "prompt", "source text:", "translated text:")
    lowered = value.lower()
    if any(marker.lower() in lowered for marker in redaction_markers):
        return "[redacted]"
    return value


@dataclass
class PDFQAReport:
    input_file: str | None
    output_file: str | None
    mode: str
    page_count: int
    translated_blocks: int = 0
    skipped_protected_blocks: int = 0
    skipped_noisy_blocks: int = 0
    overflow_blocks: int = 0
    warning_count: int = 0
    warnings_by_type: dict[str, int] = field(default_factory=dict)
    protected_regions_by_kind: dict[str, int] = field(default_factory=dict)
    rejected: bool = False
    rejection_reason: str | None = None
    engine_version: str | None = None
    created_at: str | None = None


def build_pdf_qa_report(
    *,
    input_file: str | None,
    output_file: str | None,
    mode: str,
    page_count: int,
    translated_blocks: int = 0,
    skipped_protected_blocks: int = 0,
    skipped_noisy_blocks: int = 0,
    overflow_blocks: int = 0,
    warning_count: int = 0,
    warnings_by_type: dict[str, int] | None = None,
    protected_regions_by_kind: dict[str, int] | None = None,
    rejected: bool = False,
    rejection_reason: str | None = None,
    engine_version: str | None = None,
) -> PDFQAReport:
    return PDFQAReport(
        input_file=_safe_file_label(input_file),
        output_file=_safe_file_label(output_file),
        mode=mode,
        page_count=page_count,
        translated_blocks=translated_blocks,
        skipped_protected_blocks=skipped_protected_blocks,
        skipped_noisy_blocks=skipped_noisy_blocks,
        overflow_blocks=overflow_blocks,
        warning_count=warning_count,
        warnings_by_type=dict(warnings_by_type or {}),
        protected_regions_by_kind=dict(protected_regions_by_kind or {}),
        rejected=rejected,
        rejection_reason=_sanitize_text_value(rejection_reason),
        engine_version=engine_version,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def merge_fit_summary_into_report(report: PDFQAReport, fit_summary: dict[str, object] | None) -> PDFQAReport:
    if not fit_summary:
        return report
    warning_counts = fit_summary.get("warning_counts", {})
    if isinstance(warning_counts, dict):
        merged = dict(report.warnings_by_type)
        for warning, count in warning_counts.items():
            merged[str(warning)] = merged.get(str(warning), 0) + int(count)
        report.warnings_by_type = merged
    report.overflow_blocks = max(report.overflow_blocks, int(fit_summary.get("overflow_count", 0) or 0))
    report.warning_count = sum(report.warnings_by_type.values())
    return report


def merge_protection_summary_into_report(
    report: PDFQAReport, protection_summary: dict[str, object] | None
) -> PDFQAReport:
    if not protection_summary:
        return report
    counts_by_kind = protection_summary.get("counts_by_kind", {})
    if isinstance(counts_by_kind, dict):
        report.protected_regions_by_kind = {
            str(kind): int(count) for kind, count in counts_by_kind.items()
        }
    return report


def merge_visual_diff_into_pdf_qa_report(
    report: PDFQAReport, visual_result: dict[str, object] | None
) -> PDFQAReport:
    if not visual_result:
        return report

    warnings = visual_result.get("warnings", [])
    if isinstance(warnings, list):
        merged = dict(report.warnings_by_type)
        for warning in warnings:
            label = _sanitize_text_value(str(warning)) or "[redacted]"
            merged[label] = merged.get(label, 0) + 1
        report.warnings_by_type = merged
        report.warning_count = sum(report.warnings_by_type.values())
    return report


def sanitize_pdf_qa_report(report: PDFQAReport) -> PDFQAReport:
    report.input_file = _safe_file_label(report.input_file)
    report.output_file = _safe_file_label(report.output_file)
    report.rejection_reason = _sanitize_text_value(report.rejection_reason)
    sanitized_warnings: dict[str, int] = {}
    for warning, count in report.warnings_by_type.items():
        sanitized_warnings[_sanitize_text_value(str(warning)) or "[redacted]"] = int(count)
    report.warnings_by_type = sanitized_warnings
    sanitized_regions: dict[str, int] = {}
    for kind, count in report.protected_regions_by_kind.items():
        sanitized_regions[_sanitize_text_value(str(kind)) or "[redacted]"] = int(count)
    report.protected_regions_by_kind = sanitized_regions
    return report


def report_to_public_dict(report: PDFQAReport) -> dict[str, Any]:
    sanitized = sanitize_pdf_qa_report(report)
    return asdict(sanitized)


def summarize_pdf_processing(
    *,
    input_file: str | None,
    output_file: str | None,
    mode: str,
    page_count: int,
    translated_blocks: int = 0,
    skipped_protected_blocks: int = 0,
    skipped_noisy_blocks: int = 0,
    overflow_blocks: int = 0,
    warning_count: int = 0,
    warnings_by_type: dict[str, int] | None = None,
    protected_regions_by_kind: dict[str, int] | None = None,
    rejected: bool = False,
    rejection_reason: str | None = None,
    engine_version: str | None = None,
) -> dict[str, Any]:
    report = build_pdf_qa_report(
        input_file=input_file,
        output_file=output_file,
        mode=mode,
        page_count=page_count,
        translated_blocks=translated_blocks,
        skipped_protected_blocks=skipped_protected_blocks,
        skipped_noisy_blocks=skipped_noisy_blocks,
        overflow_blocks=overflow_blocks,
        warning_count=warning_count,
        warnings_by_type=warnings_by_type,
        protected_regions_by_kind=protected_regions_by_kind,
        rejected=rejected,
        rejection_reason=rejection_reason,
        engine_version=engine_version,
    )
    return report_to_public_dict(report)
