"""Heuristic protected-region detection for canonical PDF models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

import fitz

from translation_app.core.file_handlers.pdf_model import PDFBlockModel, PDFDocumentModel


BBox = tuple[float, float, float, float]

CHART_CAPTION_PATTERN = re.compile(
    r"(?:\bfigure\b|\bfig\.\b|\bchart\b|h\u00ecnh|\u56f3|\u8868|bi\u1ec3u\s+\u0111\u1ed3)",
    re.IGNORECASE,
)
FORMULA_HINT_PATTERN = re.compile(
    r"(?:\bSUM\(|\bAVG\(|\b[A-Za-z]\d+:\w+\d+\b|mc\^2|x\^2|y\^2|=|\^|\u2211|\u221a|\u222b|\u00b1|\u2264|\u2265|\u2248)",
    re.IGNORECASE,
)
TABLE_DELIMITER_PATTERN = re.compile(r"(?:\s{2,}|[|;,]\s*\S)")


@dataclass
class PDFProtectedRegion:
    region_id: str
    page_index: int
    bbox: BBox
    kind: str
    source_block_ids: list[str]
    confidence: float
    reason: str


def _bbox_union(bboxes: Iterable[BBox]) -> BBox:
    coords = list(bboxes)
    if not coords:
        return (0.0, 0.0, 0.0, 0.0)
    x0 = min(b[0] for b in coords)
    y0 = min(b[1] for b in coords)
    x1 = max(b[2] for b in coords)
    y1 = max(b[3] for b in coords)
    return (x0, y0, x1, y1)


def _symbol_digit_ratio(text: str) -> float:
    normalized = re.sub(r"\s+", "", text or "")
    if not normalized:
        return 0.0
    symbol_digit_count = sum(1 for ch in normalized if ch.isdigit() or not ch.isalnum())
    return symbol_digit_count / len(normalized)


def _is_formula_candidate(block: PDFBlockModel) -> tuple[bool, float, str]:
    text = block.text or ""
    if "formula_like" in block.flags:
        return True, 0.95, "formula_like flag from canonical model"
    if FORMULA_HINT_PATTERN.search(text):
        return True, 0.9, "math-like token pattern"
    if len(text.strip()) <= 20 and _symbol_digit_ratio(text) >= 0.35:
        return True, 0.72, "short block with high symbol/digit ratio"
    return False, 0.0, ""


def _is_table_candidate(block: PDFBlockModel) -> tuple[bool, float, str]:
    text = block.text or ""
    if "table_like" in block.flags:
        return True, 0.88, "table_like flag from canonical model"
    if TABLE_DELIMITER_PATTERN.search(text) and sum(1 for ch in text if ch.isdigit()) >= 2:
        return True, 0.7, "delimiter-heavy block with numeric content"
    return False, 0.0, ""


def _find_nearby_caption(page_blocks: list[PDFBlockModel], visual_block: PDFBlockModel) -> PDFBlockModel | None:
    visual_rect = fitz.Rect(visual_block.bbox)
    candidates: list[PDFBlockModel] = []
    for block in page_blocks:
        if block.kind != "text" or not block.text:
            continue
        if "caption_like" not in block.flags:
            continue
        block_rect = fitz.Rect(block.bbox)
        if 0 <= block_rect.y0 - visual_rect.y1 <= 60 and block_rect.x0 <= visual_rect.x1 + 40:
            candidates.append(block)
    if not candidates:
        return None
    candidates.sort(key=lambda block: (block.bbox[1], block.bbox[0], block.block_id))
    return candidates[0]


def detect_protected_regions(model: PDFDocumentModel) -> list[PDFProtectedRegion]:
    regions: list[PDFProtectedRegion] = []

    for page in model.pages:
        translatable_text_blocks = [
            block for block in page.blocks if block.kind == "text" and "translatable" in block.flags
        ]
        visual_block_ids: list[str] = []

        for block in page.blocks:
            if block.kind == "text":
                is_formula, formula_confidence, formula_reason = _is_formula_candidate(block)
                if is_formula:
                    regions.append(
                        PDFProtectedRegion(
                            region_id=f"p{page.page_index}-formula-{block.block_id}",
                            page_index=page.page_index,
                            bbox=block.bbox,
                            kind="formula",
                            source_block_ids=[block.block_id],
                            confidence=formula_confidence,
                            reason=formula_reason,
                        )
                    )

                is_table, table_confidence, table_reason = _is_table_candidate(block)
                if is_table:
                    regions.append(
                        PDFProtectedRegion(
                            region_id=f"p{page.page_index}-table-{block.block_id}",
                            page_index=page.page_index,
                            bbox=block.bbox,
                            kind="table",
                            source_block_ids=[block.block_id],
                            confidence=table_confidence,
                            reason=table_reason,
                        )
                    )

                if "noisy" in block.flags:
                    regions.append(
                        PDFProtectedRegion(
                            region_id=f"p{page.page_index}-noisy-{block.block_id}",
                            page_index=page.page_index,
                            bbox=block.bbox,
                            kind="noisy",
                            source_block_ids=[block.block_id],
                            confidence=0.93,
                            reason="tiny or non-informative text block",
                        )
                    )

                if "caption_like" in block.flags:
                    regions.append(
                        PDFProtectedRegion(
                            region_id=f"p{page.page_index}-caption-{block.block_id}",
                            page_index=page.page_index,
                            bbox=block.bbox,
                            kind="caption",
                            source_block_ids=[block.block_id],
                            confidence=0.68,
                            reason="caption-like block near image or drawing",
                        )
                    )

            if block.kind in {"image", "drawing"} or "image_like" in block.flags:
                kind = "image" if block.kind == "image" else "drawing"
                reason = "non-text visual block"
                confidence = 0.99
                caption_block = _find_nearby_caption(page.blocks, block)
                if caption_block and CHART_CAPTION_PATTERN.search(caption_block.text):
                    kind = "chart"
                    reason = "visual block with nearby chart or figure caption cue"
                    confidence = 0.83
                regions.append(
                    PDFProtectedRegion(
                        region_id=f"p{page.page_index}-{kind}-{block.block_id}",
                        page_index=page.page_index,
                        bbox=block.bbox,
                        kind=kind,
                        source_block_ids=[block.block_id],
                        confidence=confidence,
                        reason=reason,
                    )
                )
                visual_block_ids.append(block.block_id)

        if visual_block_ids and not translatable_text_blocks:
            regions.append(
                PDFProtectedRegion(
                    region_id=f"p{page.page_index}-scanned",
                    page_index=page.page_index,
                    bbox=(0.0, 0.0, page.width, page.height),
                    kind="scanned_page",
                    source_block_ids=visual_block_ids,
                    confidence=0.97,
                    reason="page contains only visual blocks and no translatable text",
                )
            )

    return regions


def apply_protected_flags(
    model: PDFDocumentModel, regions: list[PDFProtectedRegion]
) -> PDFDocumentModel:
    region_map: dict[str, list[PDFProtectedRegion]] = {}
    for region in regions:
        for block_id in region.source_block_ids:
            region_map.setdefault(block_id, []).append(region)

    for page in model.pages:
        page_regions = [region for region in regions if region.page_index == page.page_index]
        scanned_page = any(region.kind == "scanned_page" for region in page_regions)

        for block in page.blocks:
            for region in region_map.get(block.block_id, []):
                block.flags.add(f"protected_region:{region.kind}")
                if region.kind in {"formula", "image", "drawing", "table", "chart", "scanned_page"}:
                    block.flags.add("protected")
                    block.flags.discard("translatable")
                if region.kind == "noisy":
                    block.flags.add("noisy")
                    block.flags.add("non_translatable")
                    block.flags.discard("translatable")
                if region.kind == "caption":
                    block.flags.add("caption_like")

            if scanned_page and block.kind == "text":
                block.flags.add("page_scanned")
                block.flags.discard("translatable")

    return model


def is_block_protected(block: PDFBlockModel, regions: list[PDFProtectedRegion]) -> bool:
    protected_kinds = {"formula", "image", "drawing", "table", "chart", "scanned_page"}
    return any(
        block.block_id in region.source_block_ids and region.kind in protected_kinds
        for region in regions
    )


def get_translatable_blocks(
    model: PDFDocumentModel,
    regions: list[PDFProtectedRegion] | None = None,
    exclude_protected: bool = True,
) -> list[PDFBlockModel]:
    protected_ids: set[str] = set()
    if regions and exclude_protected:
        protected_kinds = {"formula", "image", "drawing", "table", "chart", "scanned_page", "noisy"}
        for region in regions:
            if region.kind in protected_kinds:
                protected_ids.update(region.source_block_ids)

    blocks: list[PDFBlockModel] = []
    for page in model.pages:
        for block in page.blocks:
            if block.kind != "text":
                continue
            if "translatable" not in block.flags:
                continue
            if exclude_protected and block.block_id in protected_ids:
                continue
            blocks.append(block)
    return blocks


def model_to_protection_summary(
    model: PDFDocumentModel, regions: list[PDFProtectedRegion]
) -> dict[str, object]:
    counts_by_kind: dict[str, int] = {}
    pages_with_scanned_marker: set[int] = set()
    for region in regions:
        counts_by_kind[region.kind] = counts_by_kind.get(region.kind, 0) + 1
        if region.kind == "scanned_page":
            pages_with_scanned_marker.add(region.page_index)

    protected_ids = {
        block_id
        for region in regions
        if region.kind in {"formula", "image", "drawing", "table", "chart", "scanned_page"}
        for block_id in region.source_block_ids
    }
    caption_ids = {
        block_id for region in regions if region.kind == "caption" for block_id in region.source_block_ids
    }

    return {
        "page_count": model.page_count,
        "region_count": len(regions),
        "counts_by_kind": counts_by_kind,
        "protected_block_count": len(protected_ids),
        "caption_block_count": len(caption_ids),
        "scanned_page_count": len(pages_with_scanned_marker),
        "translatable_block_count": len(get_translatable_blocks(model, regions, exclude_protected=True)),
    }
