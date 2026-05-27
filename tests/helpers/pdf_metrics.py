"""Lightweight PDF metrics for baseline tests."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import fitz

from translation_app.core.encoding_utils import detect_mojibake


def _normalize_block_text(block: dict[str, Any]) -> str:
    parts: list[str] = []
    for line in block.get("lines", []):
        span_parts: list[str] = []
        for span in line.get("spans", []):
            text = str(span.get("text", "") or "").strip()
            if text:
                span_parts.append(text)
        if span_parts:
            parts.append(" ".join(span_parts))
    return "\n".join(parts).strip()


def collect_pdf_text_blocks(path: str | Path) -> list[dict[str, Any]]:
    blocks_out: list[dict[str, Any]] = []
    doc = fitz.open(path)
    try:
        for page_index, page in enumerate(doc):
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                text = _normalize_block_text(block)
                if not text:
                    continue
                bbox = tuple(float(v) for v in block.get("bbox", (0, 0, 0, 0)))
                blocks_out.append(
                    {
                        "page_index": page_index,
                        "text": text,
                        "text_preview": text[:80],
                        "bbox": bbox,
                        "length": len(text),
                    }
                )
    finally:
        doc.close()
    return blocks_out


def count_pages(path: str | Path) -> int:
    doc = fitz.open(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def count_text_blocks(path: str | Path) -> int:
    return len(collect_pdf_text_blocks(path))


def extract_text_joined(path: str | Path) -> str:
    return "\n".join(block["text"] for block in collect_pdf_text_blocks(path))


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
    image_count = 0
    drawing_count = 0
    doc = fitz.open(path)
    try:
        for page in doc:
            image_count += len(page.get_images(full=True))
            drawing_count += len(page.get_drawings())
    finally:
        doc.close()
    return {
        "image_count": image_count,
        "drawing_count": drawing_count,
        "protected_object_count": image_count + drawing_count,
    }


def detect_mojibake_in_pdf_text(path: str | Path) -> bool:
    return detect_mojibake(extract_text_joined(path))


def count_overflow_warnings(log_text: str) -> int:
    return log_text.lower().count("overflow fallback")
