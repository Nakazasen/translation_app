"""Heuristic reading-order and paragraph grouping for canonical PDF models."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import fitz

from translation_app.core.file_handlers.pdf_model import (
    BBox,
    PDFBlockModel,
    PDFDocumentModel,
    PDFLineModel,
    PDFPageModel,
    PDFSpanModel,
)


CAPTION_CUE_PATTERN = re.compile(
    r"(?:\bfigure\b|\bfig\.\b|\btable\b|\bchart\b|\bcaption\b|h\u00ecnh|\u56f3|\u8868|bi\u1ec3u\s+\u0111\u1ed3)",
    re.IGNORECASE,
)
PROTECTED_FLAGS = {"protected", "formula_like", "table_like", "noisy", "non_translatable"}


@dataclass
class PDFParagraphCandidate:
    paragraph_id: str
    page_index: int
    block_ids: list[str]
    bbox: BBox
    text: str
    reading_order: int
    flags: set[str] = field(default_factory=set)
    confidence: float = 0.0


def _legacy_sort_key(block: PDFBlockModel) -> tuple[float, float, str]:
    return (round(block.bbox[1], 3), round(block.bbox[0], 3), block.block_id)


def _primary_font_size(block: PDFBlockModel) -> float:
    sizes = [
        float(span.size)
        for line in block.lines
        for span in line.spans
        if getattr(span, "size", 0.0)
    ]
    return min(sizes) if sizes else 0.0


def _column_group_key(block: PDFBlockModel) -> tuple[float, float, str]:
    return (round(block.bbox[1], 3), round(block.bbox[0], 3), block.block_id)


def _classify_column(block: PDFBlockModel, page_width: float, gutter: float) -> int | None:
    rect = fitz.Rect(block.bbox)
    if rect.width <= 0 or rect.height <= 0:
        return None

    midpoint = page_width / 2.0
    if rect.x1 <= midpoint - gutter / 2.0:
        return 0
    if rect.x0 >= midpoint + gutter / 2.0:
        return 1

    center_x = (rect.x0 + rect.x1) / 2.0
    if rect.width <= page_width * 0.45:
        return 0 if center_x < midpoint else 1
    return None


def group_blocks_into_columns(page: PDFPageModel) -> list[list[PDFBlockModel]]:
    sorted_blocks = sorted(page.blocks, key=_legacy_sort_key)
    text_blocks = [block for block in sorted_blocks if block.kind == "text" and block.text]
    gutter = max(24.0, page.width * 0.04)

    if len(text_blocks) < 2:
        page.metadata["column_count"] = 1
        page.metadata["reading_order_strategy"] = "legacy"
        page.metadata["reading_order_warnings"] = []
        for block in sorted_blocks:
            block.metadata["column_index"] = 0
        return [sorted_blocks]

    left_text = [block for block in text_blocks if _classify_column(block, page.width, gutter) == 0]
    right_text = [block for block in text_blocks if _classify_column(block, page.width, gutter) == 1]
    ambiguous_text = [block for block in text_blocks if _classify_column(block, page.width, gutter) is None]

    if left_text and right_text and not ambiguous_text:
        groups: dict[int, list[PDFBlockModel]] = {0: [], 1: []}
        leftovers: list[PDFBlockModel] = []
        for block in sorted_blocks:
            column_index = _classify_column(block, page.width, gutter)
            if column_index is None:
                leftovers.append(block)
                continue
            block.metadata["column_index"] = column_index
            groups[column_index].append(block)

        if leftovers:
            page.metadata["column_count"] = 1
            page.metadata["reading_order_strategy"] = "legacy"
            page.metadata["reading_order_warnings"] = ["ambiguous_reading_order"]
            for block in sorted_blocks:
                block.metadata["column_index"] = block.metadata.get("column_index", 0)
            return [sorted_blocks]

        page.metadata["column_count"] = 2
        page.metadata["reading_order_strategy"] = "layout_aware"
        page.metadata["reading_order_warnings"] = []
        return [
            sorted(groups[0], key=_column_group_key),
            sorted(groups[1], key=_column_group_key),
        ]

    warnings: list[str] = []
    if left_text and right_text:
        warnings.append("ambiguous_reading_order")
    page.metadata["column_count"] = 1
    page.metadata["reading_order_strategy"] = "legacy"
    page.metadata["reading_order_warnings"] = warnings
    for block in sorted_blocks:
        block.metadata["column_index"] = 0
    return [sorted_blocks]


def assign_reading_order(model: PDFDocumentModel, strategy: str = "layout_aware") -> PDFDocumentModel:
    ambiguous_pages = 0
    for page in model.pages:
        groups = group_blocks_into_columns(page) if strategy == "layout_aware" else [sorted(page.blocks, key=_legacy_sort_key)]
        ordered_blocks = [block for group in groups for block in group]
        page.blocks = ordered_blocks
        for index, block in enumerate(page.blocks):
            block.reading_order = index
        page.metadata["reading_order_strategy"] = page.metadata.get("reading_order_strategy", strategy)
        if "ambiguous_reading_order" in page.metadata.get("reading_order_warnings", []):
            ambiguous_pages += 1

    model.metadata["reading_order_strategy"] = strategy
    model.metadata["ambiguous_reading_order_pages"] = ambiguous_pages
    return model


def _union_bbox(blocks: list[PDFBlockModel]) -> BBox:
    if not blocks:
        return (0.0, 0.0, 0.0, 0.0)
    x0 = min(block.bbox[0] for block in blocks)
    y0 = min(block.bbox[1] for block in blocks)
    x1 = max(block.bbox[2] for block in blocks)
    y1 = max(block.bbox[3] for block in blocks)
    return (x0, y0, x1, y1)


def _horizontal_overlap_ratio(first: fitz.Rect, second: fitz.Rect) -> float:
    overlap = max(0.0, min(first.x1, second.x1) - max(first.x0, second.x0))
    width = max(min(first.width, second.width), 1.0)
    return overlap / width


def _candidate_visual_blocks(page: PDFPageModel) -> list[PDFBlockModel]:
    return [
        block
        for block in page.blocks
        if block.kind in {"image", "drawing"} or "table_like" in block.flags
    ]


def _score_caption_relationship(text_block: PDFBlockModel, visual_block: PDFBlockModel) -> float:
    text_rect = fitz.Rect(text_block.bbox)
    visual_rect = fitz.Rect(visual_block.bbox)
    overlap_ratio = _horizontal_overlap_ratio(text_rect, visual_rect)
    below_gap = text_rect.y0 - visual_rect.y1
    above_gap = visual_rect.y0 - text_rect.y1
    distance_score = 0.0
    if -8.0 <= below_gap <= 72.0:
        distance_score = max(distance_score, 1.0 - max(below_gap, 0.0) / 72.0)
    if -8.0 <= above_gap <= 40.0:
        distance_score = max(distance_score, 0.8 - max(above_gap, 0.0) / 80.0)

    cue_bonus = 0.25 if CAPTION_CUE_PATTERN.search(text_block.text or "") else 0.0
    existing_flag_bonus = 0.15 if "caption_like" in text_block.flags else 0.0
    short_text_bonus = 0.1 if len(text_block.text or "") <= 140 else 0.0
    return overlap_ratio + distance_score + cue_bonus + existing_flag_bonus + short_text_bonus


def detect_caption_relationships(model: PDFDocumentModel) -> PDFDocumentModel:
    for page in model.pages:
        visual_blocks = _candidate_visual_blocks(page)
        for block in page.blocks:
            block.metadata.setdefault("related_block_ids", [])
            block.metadata.setdefault("caption_block_ids", [])
            if block.kind == "text":
                block.metadata.pop("caption_for_block_id", None)

        if not visual_blocks:
            continue

        for text_block in [block for block in page.blocks if block.kind == "text" and block.text]:
            if len(text_block.text) > 180:
                continue

            scored_candidates = [
                (visual_block, _score_caption_relationship(text_block, visual_block))
                for visual_block in visual_blocks
            ]
            if not scored_candidates:
                continue

            related_block, score = max(scored_candidates, key=lambda item: item[1])
            if score < 0.85:
                continue

            text_block.flags.add("caption_like")
            text_block.metadata["caption_for_block_id"] = related_block.block_id
            text_block.metadata["related_block_ids"] = [related_block.block_id]

            caption_block_ids = list(related_block.metadata.get("caption_block_ids", []))
            if text_block.block_id not in caption_block_ids:
                caption_block_ids.append(text_block.block_id)
            related_block.metadata["caption_block_ids"] = caption_block_ids

            related_ids = list(related_block.metadata.get("related_block_ids", []))
            if text_block.block_id not in related_ids:
                related_ids.append(text_block.block_id)
            related_block.metadata["related_block_ids"] = related_ids

    return model


def group_spans_into_text_runs(line: PDFLineModel) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for span in line.spans:
        if current is None:
            current = {
                "text": span.text,
                "bbox": span.bbox,
                "font": span.font,
                "size": float(span.size),
                "span_count": 1,
            }
            continue

        last_bbox = fitz.Rect(current["bbox"])
        current_font = str(current["font"])
        current_size = float(current["size"])
        span_bbox = fitz.Rect(span.bbox)
        gap = span_bbox.x0 - last_bbox.x1
        same_style = current_font == span.font and abs(current_size - float(span.size)) <= 0.5
        if same_style and gap <= max(8.0, current_size * 0.8):
            current["text"] = f"{current['text']} {span.text}".strip()
            current["bbox"] = (
                min(last_bbox.x0, span_bbox.x0),
                min(last_bbox.y0, span_bbox.y0),
                max(last_bbox.x1, span_bbox.x1),
                max(last_bbox.y1, span_bbox.y1),
            )
            current["span_count"] = int(current["span_count"]) + 1
        else:
            runs.append(current)
            current = {
                "text": span.text,
                "bbox": span.bbox,
                "font": span.font,
                "size": float(span.size),
                "span_count": 1,
            }

    if current is not None:
        runs.append(current)
    line.metadata["text_run_count"] = len(runs)
    return runs


def _is_paragraph_block_candidate(block: PDFBlockModel) -> bool:
    if block.kind != "text" or not block.text:
        return False
    if any(flag in block.flags for flag in PROTECTED_FLAGS):
        return False
    if "caption_like" in block.flags:
        return False
    return True


def _can_merge_blocks(previous: PDFBlockModel, current: PDFBlockModel) -> bool:
    if not _is_paragraph_block_candidate(previous) or not _is_paragraph_block_candidate(current):
        return False
    if previous.page_index != current.page_index:
        return False
    if previous.metadata.get("column_index", 0) != current.metadata.get("column_index", 0):
        return False

    prev_rect = fitz.Rect(previous.bbox)
    curr_rect = fitz.Rect(current.bbox)
    vertical_gap = curr_rect.y0 - prev_rect.y1
    if vertical_gap < -4.0:
        return False

    prev_font_size = _primary_font_size(previous)
    curr_font_size = _primary_font_size(current)
    if prev_font_size and curr_font_size and abs(prev_font_size - curr_font_size) > 2.5:
        return False

    x_alignment_delta = abs(prev_rect.x0 - curr_rect.x0)
    horizontal_overlap = _horizontal_overlap_ratio(prev_rect, curr_rect)
    max_gap = max(16.0, min(prev_font_size or 12.0, curr_font_size or 12.0) * 1.8)
    return vertical_gap <= max_gap and (x_alignment_delta <= 24.0 or horizontal_overlap >= 0.5)


def build_paragraph_candidates(model: PDFDocumentModel) -> list[PDFParagraphCandidate]:
    candidates: list[PDFParagraphCandidate] = []

    for page in model.pages:
        page_blocks = [block for block in page.blocks if block.kind == "text" and block.text]
        page_blocks.sort(key=lambda block: block.reading_order if block.reading_order is not None else 10**9)
        current_group: list[PDFBlockModel] = []

        def flush_group() -> None:
            if not current_group:
                return
            paragraph_index = len(candidates)
            candidate = PDFParagraphCandidate(
                paragraph_id=f"p{page.page_index}-para-{paragraph_index}",
                page_index=page.page_index,
                block_ids=[block.block_id for block in current_group],
                bbox=_union_bbox(current_group),
                text="\n".join(block.text for block in current_group if block.text),
                reading_order=min(
                    block.reading_order for block in current_group if block.reading_order is not None
                ),
                flags=set().union(*(block.flags for block in current_group)),
                confidence=0.9 if len(current_group) > 1 else 0.7,
            )
            candidates.append(candidate)
            for block in current_group:
                block.metadata["paragraph_candidate_id"] = candidate.paragraph_id
            current_group.clear()

        for block in page_blocks:
            for line in block.lines:
                group_spans_into_text_runs(line)

            if not _is_paragraph_block_candidate(block):
                flush_group()
                continue

            if not current_group:
                current_group.append(block)
                continue

            if _can_merge_blocks(current_group[-1], block):
                current_group.append(block)
            else:
                flush_group()
                current_group.append(block)

        flush_group()

    return candidates


def paragraph_candidates_to_public_summary(candidates: list[PDFParagraphCandidate]) -> dict[str, Any]:
    return {
        "paragraph_candidate_count": len(candidates),
        "pages": sorted({candidate.page_index for candidate in candidates}),
        "paragraphs": [
            {
                "paragraph_id": candidate.paragraph_id,
                "page_index": candidate.page_index,
                "block_count": len(candidate.block_ids),
                "reading_order": candidate.reading_order,
                "bbox": candidate.bbox,
                "confidence": round(candidate.confidence, 3),
                "flags": sorted(candidate.flags),
            }
            for candidate in candidates
        ],
    }


def model_to_reading_order_summary(model: PDFDocumentModel) -> dict[str, Any]:
    paragraph_candidates = model.metadata.get("paragraph_candidates", [])
    page_summaries: list[dict[str, Any]] = []
    ambiguous_page_count = 0
    caption_relationship_count = 0

    for page in model.pages:
        warnings = list(page.metadata.get("reading_order_warnings", []))
        if "ambiguous_reading_order" in warnings:
            ambiguous_page_count += 1
        caption_relationship_count += sum(
            1
            for block in page.blocks
            if block.kind == "text" and block.metadata.get("caption_for_block_id")
        )
        page_summaries.append(
            {
                "page_index": page.page_index,
                "column_count": int(page.metadata.get("column_count", 1) or 1),
                "reading_order_strategy": str(page.metadata.get("reading_order_strategy", "legacy")),
                "warning_count": len(warnings),
                "warnings": warnings,
            }
        )

    return {
        "page_count": model.page_count,
        "ambiguous_page_count": ambiguous_page_count,
        "caption_relationship_count": caption_relationship_count,
        "paragraph_candidate_count": len(paragraph_candidates) if isinstance(paragraph_candidates, list) else 0,
        "pages": page_summaries,
    }
