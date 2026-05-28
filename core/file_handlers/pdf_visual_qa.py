"""Public-safe visual QA helpers for experimental PDF output."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from statistics import mean
from typing import Any

import fitz


DEFAULT_RENDER_DPI = 72
WHITE_PIXEL_THRESHOLD = 250


@dataclass
class PDFPageVisualSnapshot:
    page_index: int
    width: int
    height: int
    hash: str
    non_white_ratio: float
    render_dpi: int


@dataclass
class PDFVisualDiffResult:
    page_count_before: int
    page_count_after: int
    page_count_match: bool
    dimension_mismatches: int
    mean_diff_ratio: float
    max_diff_ratio: float
    pages_compared: int
    warnings: list[str] = field(default_factory=list)
    safe_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class PDFVisualQAThresholds:
    warning_mean_diff_ratio: float = 0.15
    fail_mean_diff_ratio: float = 0.35
    warning_max_diff_ratio: float = 0.30
    fail_max_diff_ratio: float = 0.60
    allow_page_count_mismatch: bool = False
    allow_dimension_mismatch: bool = False


@dataclass
class PDFVisualQAEvaluation:
    status: str
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    mean_diff_ratio: float = 0.0
    max_diff_ratio: float = 0.0
    page_count_match: bool = True
    dimension_mismatches: int = 0
    public_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class _RenderedPageSnapshot:
    public: PDFPageVisualSnapshot
    grayscale_samples: bytes


def _build_matrix_for_dpi(dpi: int) -> fitz.Matrix:
    scale = float(dpi) / 72.0
    return fitz.Matrix(scale, scale)


def _render_page(doc: fitz.Document, page_index: int, dpi: int) -> _RenderedPageSnapshot:
    page = doc.load_page(page_index)
    pixmap = page.get_pixmap(matrix=_build_matrix_for_dpi(dpi), colorspace=fitz.csGRAY, alpha=False)
    grayscale_samples = bytes(pixmap.samples)
    pixel_count = max(pixmap.width * pixmap.height, 1)
    non_white_pixels = sum(1 for value in grayscale_samples if value < WHITE_PIXEL_THRESHOLD)
    public = PDFPageVisualSnapshot(
        page_index=page_index,
        width=int(pixmap.width),
        height=int(pixmap.height),
        hash=hashlib.sha256(grayscale_samples).hexdigest(),
        non_white_ratio=non_white_pixels / pixel_count,
        render_dpi=int(dpi),
    )
    return _RenderedPageSnapshot(public=public, grayscale_samples=grayscale_samples)


def render_pdf_page_snapshot(path: str, page_index: int, dpi: int = DEFAULT_RENDER_DPI) -> PDFPageVisualSnapshot:
    doc = fitz.open(path)
    try:
        return _render_page(doc, page_index, dpi).public
    finally:
        doc.close()


def render_pdf_snapshots(
    path: str, dpi: int = DEFAULT_RENDER_DPI, max_pages: int | None = None
) -> list[PDFPageVisualSnapshot]:
    doc = fitz.open(path)
    try:
        page_limit = doc.page_count if max_pages is None else min(doc.page_count, max_pages)
        return [_render_page(doc, page_index, dpi).public for page_index in range(page_limit)]
    finally:
        doc.close()


def _compare_grayscale_samples(before: bytes, after: bytes) -> float:
    if len(before) != len(after):
        return 1.0
    if not before:
        return 0.0
    total_delta = sum(abs(before_value - after_value) for before_value, after_value in zip(before, after))
    return total_delta / (len(before) * 255.0)


def compare_pdf_visual_snapshots(
    before_path: str, after_path: str, dpi: int = DEFAULT_RENDER_DPI, max_pages: int | None = None
) -> PDFVisualDiffResult:
    warnings: list[str] = []
    try:
        before_doc = fitz.open(before_path)
        after_doc = fitz.open(after_path)
    except Exception:
        return PDFVisualDiffResult(
            page_count_before=0,
            page_count_after=0,
            page_count_match=False,
            dimension_mismatches=0,
            mean_diff_ratio=0.0,
            max_diff_ratio=0.0,
            pages_compared=0,
            warnings=["render_failed"],
            safe_summary={"render_dpi": int(dpi), "pages": []},
        )

    try:
        before_count = before_doc.page_count
        after_count = after_doc.page_count
        page_count_match = before_count == after_count
        if not page_count_match:
            warnings.append("page_count_mismatch")

        comparable_count = min(before_count, after_count)
        if max_pages is not None:
            comparable_count = min(comparable_count, max_pages)

        dimension_mismatches = 0
        diff_ratios: list[float] = []
        page_summaries: list[dict[str, Any]] = []

        for page_index in range(comparable_count):
            before_render = _render_page(before_doc, page_index, dpi)
            after_render = _render_page(after_doc, page_index, dpi)

            before_snapshot = before_render.public
            after_snapshot = after_render.public
            same_dimensions = (
                before_snapshot.width == after_snapshot.width
                and before_snapshot.height == after_snapshot.height
            )
            if not same_dimensions:
                dimension_mismatches += 1
                diff_ratio = 1.0
            else:
                diff_ratio = _compare_grayscale_samples(
                    before_render.grayscale_samples, after_render.grayscale_samples
                )

            diff_ratios.append(diff_ratio)
            page_summaries.append(
                {
                    "page_index": page_index,
                    "dimensions_match": same_dimensions,
                    "before_size": [before_snapshot.width, before_snapshot.height],
                    "after_size": [after_snapshot.width, after_snapshot.height],
                    "diff_ratio": diff_ratio,
                    "before_non_white_ratio": before_snapshot.non_white_ratio,
                    "after_non_white_ratio": after_snapshot.non_white_ratio,
                }
            )

        if dimension_mismatches:
            warnings.append("page_dimension_mismatch")
        max_diff_ratio = max(diff_ratios, default=0.0)

        return PDFVisualDiffResult(
            page_count_before=before_count,
            page_count_after=after_count,
            page_count_match=page_count_match,
            dimension_mismatches=dimension_mismatches,
            mean_diff_ratio=mean(diff_ratios) if diff_ratios else 0.0,
            max_diff_ratio=max_diff_ratio,
            pages_compared=len(diff_ratios),
            warnings=warnings,
            safe_summary={
                "render_dpi": int(dpi),
                "pages": page_summaries,
                "mean_non_white_ratio_before": mean(
                    [page["before_non_white_ratio"] for page in page_summaries]
                )
                if page_summaries
                else 0.0,
                "mean_non_white_ratio_after": mean(
                    [page["after_non_white_ratio"] for page in page_summaries]
                )
                if page_summaries
                else 0.0,
            },
        )
    except Exception:
        return PDFVisualDiffResult(
            page_count_before=before_doc.page_count,
            page_count_after=after_doc.page_count,
            page_count_match=before_doc.page_count == after_doc.page_count,
            dimension_mismatches=0,
            mean_diff_ratio=0.0,
            max_diff_ratio=0.0,
            pages_compared=0,
            warnings=["render_failed"],
            safe_summary={"render_dpi": int(dpi), "pages": []},
        )
    finally:
        before_doc.close()
        after_doc.close()


def result_to_public_dict(result: PDFVisualDiffResult) -> dict[str, Any]:
    public = asdict(result)
    public["warnings"] = [str(warning) for warning in result.warnings]
    return public


def evaluate_visual_diff(
    result: PDFVisualDiffResult,
    thresholds: PDFVisualQAThresholds | None = None,
) -> PDFVisualQAEvaluation:
    resolved = thresholds or PDFVisualQAThresholds()
    warnings: list[str] = []
    failures: list[str] = []

    if "render_failed" in result.warnings:
        failures.append("render_failed")

    if not result.page_count_match:
        if resolved.allow_page_count_mismatch:
            warnings.append("page_count_mismatch")
        else:
            failures.append("page_count_mismatch")

    if result.dimension_mismatches > 0:
        if resolved.allow_dimension_mismatch:
            warnings.append("page_dimension_mismatch")
        else:
            failures.append("page_dimension_mismatch")

    if result.mean_diff_ratio >= resolved.fail_mean_diff_ratio:
        failures.append("high_mean_visual_diff")
    elif result.mean_diff_ratio >= resolved.warning_mean_diff_ratio:
        warnings.append("high_mean_visual_diff")

    if result.max_diff_ratio >= resolved.fail_max_diff_ratio:
        failures.append("high_max_visual_diff")
    elif result.max_diff_ratio >= resolved.warning_max_diff_ratio:
        warnings.append("high_max_visual_diff")

    status = "fail" if failures else "warning" if warnings else "pass"
    public_summary = {
        "status": status,
        "warning_count": len(warnings),
        "failure_count": len(failures),
        "warnings": list(warnings),
        "failures": list(failures),
        "mean_diff_ratio": float(result.mean_diff_ratio),
        "max_diff_ratio": float(result.max_diff_ratio),
        "page_count_match": bool(result.page_count_match),
        "dimension_mismatches": int(result.dimension_mismatches),
        "pages_compared": int(result.pages_compared),
        "thresholds": asdict(resolved),
    }
    return PDFVisualQAEvaluation(
        status=status,
        warnings=warnings,
        failures=failures,
        mean_diff_ratio=float(result.mean_diff_ratio),
        max_diff_ratio=float(result.max_diff_ratio),
        page_count_match=bool(result.page_count_match),
        dimension_mismatches=int(result.dimension_mismatches),
        public_summary=public_summary,
    )


def visual_evaluation_to_public_dict(evaluation: PDFVisualQAEvaluation) -> dict[str, Any]:
    public = asdict(evaluation)
    public["warnings"] = [str(warning) for warning in evaluation.warnings]
    public["failures"] = [str(failure) for failure in evaluation.failures]
    public["public_summary"] = dict(evaluation.public_summary)
    return public


def merge_visual_evaluation_into_pdf_qa_report(report, evaluation: PDFVisualQAEvaluation | dict[str, Any] | None):
    if not evaluation:
        return report

    if isinstance(evaluation, PDFVisualQAEvaluation):
        public = visual_evaluation_to_public_dict(evaluation)
    else:
        public = dict(evaluation)

    visual_status = str(public.get("status", "") or "").strip() or None
    visual_warnings = [str(item) for item in public.get("warnings", []) if str(item).strip()]
    visual_failures = [str(item) for item in public.get("failures", []) if str(item).strip()]

    report.visual_status = visual_status
    report.visual_warnings = visual_warnings
    report.visual_failures = visual_failures
    report.visual_mean_diff_ratio = float(public.get("mean_diff_ratio", 0.0) or 0.0)
    report.visual_max_diff_ratio = float(public.get("max_diff_ratio", 0.0) or 0.0)

    merged = dict(getattr(report, "warnings_by_type", {}))
    for warning in visual_warnings:
        merged[warning] = merged.get(warning, 0) + 1
    for failure in visual_failures:
        merged[f"visual_fail:{failure}"] = merged.get(f"visual_fail:{failure}", 0) + 1
    report.warnings_by_type = merged
    report.warning_count = sum(int(count) for count in merged.values())
    return report
