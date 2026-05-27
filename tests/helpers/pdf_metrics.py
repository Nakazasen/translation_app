"""Lightweight PDF metrics for baseline tests."""

from __future__ import annotations

import math
from pathlib import Path

from translation_app.core.encoding_utils import detect_mojibake
from translation_app.core.file_handlers.pdf_model import (
    build_pdf_document_model,
    collect_text_blocks_from_model,
    extract_text_joined_from_model,
    model_to_public_metrics,
)


def collect_pdf_text_blocks(path: str | Path) -> list[dict[str, Any]]:
    return collect_text_blocks_from_model(build_pdf_document_model(path))


def count_pages(path: str | Path) -> int:
    return build_pdf_document_model(path).page_count


def count_text_blocks(path: str | Path) -> int:
    return len(collect_pdf_text_blocks(path))


def extract_text_joined(path: str | Path) -> str:
    return extract_text_joined_from_model(build_pdf_document_model(path))


def estimate_bbox_drift(
    before_blocks: list[dict[str, Any]], after_blocks: list[dict[str, Any]]
) -> dict[str, float | int]:
    compared = min(len(before_blocks), len(after_blocks))
    if compared == 0:
        return {
            "compared_blocks": 0,
            "avg_center_drift": 0.0,
            "max_center_drift": 0.0,
        }

    drifts: list[float] = []
    for before, after in zip(before_blocks[:compared], after_blocks[:compared]):
        bx0, by0, bx1, by1 = before["bbox"]
        ax0, ay0, ax1, ay1 = after["bbox"]
        before_center = ((bx0 + bx1) / 2.0, (by0 + by1) / 2.0)
        after_center = ((ax0 + ax1) / 2.0, (ay0 + ay1) / 2.0)
        drifts.append(math.dist(before_center, after_center))

    return {
        "compared_blocks": compared,
        "avg_center_drift": sum(drifts) / compared,
        "max_center_drift": max(drifts),
    }


def count_images_or_drawings(path: str | Path) -> dict[str, int]:
    metrics = model_to_public_metrics(build_pdf_document_model(path))
    return {
        "image_count": int(metrics["image_block_count"]),
        "drawing_count": int(metrics["drawing_block_count"]),
        "protected_object_count": int(metrics["protected_object_count"]),
    }


def detect_mojibake_in_pdf_text(path: str | Path) -> bool:
    return detect_mojibake(extract_text_joined(path))


def count_overflow_warnings(log_text: str) -> int:
    return log_text.lower().count("overflow fallback")
