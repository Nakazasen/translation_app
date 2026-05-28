"""Canonical internal PDF page/block/line/span model built from PyMuPDF."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz


BBox = tuple[float, float, float, float]

FORMULA_PATTERN = re.compile(
    r"(?:\bSUM\(|\bAVG\(|\b[A-Za-z]\d+:\w+\d+\b|mc\^2|x\^2|y\^2|=|\^|\u2211|\u221a|\u222b|\u00b1|\u2264|\u2265|\u2248)",
    re.IGNORECASE,
)
MULTI_COLUMN_SPACING_PATTERN = re.compile(r"\S\s{2,}\S")
DIGIT_PATTERN = re.compile(r"\d")


@dataclass
class PDFSpanModel:
    bbox: BBox
    text: str
    font: str
    size: float
    color: Any = None
    flags: set[str] = field(default_factory=set)


@dataclass
class PDFLineModel:
    bbox: BBox
    text: str
    spans: list[PDFSpanModel] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PDFBlockModel:
    block_id: str
    page_index: int
    bbox: BBox
    text: str
    lines: list[PDFLineModel] = field(default_factory=list)
    kind: str = "unknown"
    flags: set[str] = field(default_factory=set)
    reading_order: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PDFPageModel:
    page_index: int
    width: float
    height: float
    rotation: int
    blocks: list[PDFBlockModel] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PDFDocumentModel:
    source_path: str | None
    page_count: int
    pages: list[PDFPageModel] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _to_bbox(values: Any) -> BBox:
    if not values:
        return (0.0, 0.0, 0.0, 0.0)
    return tuple(float(v) for v in values[:4])


def _normalize_span_text(span: dict[str, Any]) -> str:
    return str(span.get("text", "") or "").strip()


def _normalize_line_text(spans: list[PDFSpanModel]) -> str:
    return " ".join(span.text for span in spans if span.text).strip()


def _normalize_block_text(lines: list[PDFLineModel]) -> str:
    return "\n".join(line.text for line in lines if line.text).strip()


def _is_noisy_text(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text or "", flags=re.UNICODE)
    if len(normalized) < 2:
        return True
    alnum_count = sum(ch.isalnum() for ch in normalized)
    return alnum_count == 0


def _flag_text_block(block: PDFBlockModel) -> None:
    bbox = fitz.Rect(block.bbox)
    if bbox.width < 20 or bbox.height < 8:
        block.flags.add("noisy")

    if _is_noisy_text(block.text):
        block.flags.add("noisy")
    else:
        block.flags.add("translatable")

    if FORMULA_PATTERN.search(block.text):
        block.flags.update({"formula_like", "protected"})

    line_count = len([line for line in block.lines if line.text])
    digit_lines = sum(1 for line in block.lines if DIGIT_PATTERN.search(line.text))
    if MULTI_COLUMN_SPACING_PATTERN.search(block.text) or (line_count >= 3 and digit_lines >= 2):
        block.flags.add("table_like")


def mark_formula_like_blocks(model: PDFDocumentModel) -> PDFDocumentModel:
    for page in model.pages:
        for block in page.blocks:
            if block.kind == "text" and FORMULA_PATTERN.search(block.text):
                block.flags.update({"formula_like", "protected"})
    return model


def mark_table_like_blocks(model: PDFDocumentModel) -> PDFDocumentModel:
    for page in model.pages:
        text_blocks = [block for block in page.blocks if block.kind == "text"]
        y_groups: dict[int, list[PDFBlockModel]] = {}
        for block in text_blocks:
            y_key = int(round(block.bbox[1] / 12.0))
            y_groups.setdefault(y_key, []).append(block)

        for blocks in y_groups.values():
            if len(blocks) >= 3 and sum(1 for block in blocks if DIGIT_PATTERN.search(block.text)) >= 2:
                for block in blocks:
                    block.flags.add("table_like")

        for block in text_blocks:
            if MULTI_COLUMN_SPACING_PATTERN.search(block.text):
                block.flags.add("table_like")
    return model


def mark_noisy_blocks(model: PDFDocumentModel) -> PDFDocumentModel:
    for page in model.pages:
        for block in page.blocks:
            bbox = fitz.Rect(block.bbox)
            if block.kind == "text":
                if bbox.width < 20 or bbox.height < 8 or _is_noisy_text(block.text):
                    block.flags.add("noisy")
                    block.flags.discard("translatable")
            elif block.kind in {"image", "drawing"}:
                block.flags.add("protected")
    return model


def sort_blocks_reading_order(model: PDFDocumentModel) -> PDFDocumentModel:
    from translation_app.core.file_handlers.pdf_reading_order import assign_reading_order

    return assign_reading_order(model, strategy="layout_aware")


def collect_text_blocks_from_model(model: PDFDocumentModel) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for page in model.pages:
        for block in page.blocks:
            if block.kind != "text" or not block.text:
                continue
            blocks.append(
                {
                    "page_index": block.page_index,
                    "text": block.text,
                    "text_preview": block.text[:80],
                    "bbox": block.bbox,
                    "length": len(block.text),
                    "flags": sorted(block.flags),
                    "reading_order": block.reading_order,
                    "column_index": block.metadata.get("column_index"),
                }
            )
    return blocks


def extract_text_joined_from_model(model: PDFDocumentModel) -> str:
    ordered_blocks = sorted(
        collect_text_blocks_from_model(model),
        key=lambda block: (block["page_index"], block.get("reading_order", 0)),
    )
    return "\n".join(block["text"] for block in ordered_blocks)


def model_to_public_metrics(model: PDFDocumentModel) -> dict[str, Any]:
    text_blocks = collect_text_blocks_from_model(model)
    image_blocks = 0
    drawing_blocks = 0
    protected_blocks = 0
    formula_blocks = 0
    table_blocks = 0
    noisy_blocks = 0
    translatable_blocks = 0
    caption_like_blocks = 0

    for page in model.pages:
        for block in page.blocks:
            if block.kind == "image":
                image_blocks += 1
            elif block.kind == "drawing":
                drawing_blocks += 1
            if "protected" in block.flags:
                protected_blocks += 1
            if "formula_like" in block.flags:
                formula_blocks += 1
            if "table_like" in block.flags:
                table_blocks += 1
            if "noisy" in block.flags:
                noisy_blocks += 1
            if "translatable" in block.flags:
                translatable_blocks += 1
            if "caption_like" in block.flags:
                caption_like_blocks += 1

    paragraph_candidates = model.metadata.get("paragraph_candidates", [])
    reading_order_summary = model.metadata.get("reading_order_summary", {})

    return {
        "page_count": model.page_count,
        "text_block_count": len(text_blocks),
        "image_block_count": image_blocks,
        "drawing_block_count": drawing_blocks,
        "protected_object_count": image_blocks + drawing_blocks,
        "protected_block_count": protected_blocks,
        "formula_like_block_count": formula_blocks,
        "table_like_block_count": table_blocks,
        "noisy_block_count": noisy_blocks,
        "translatable_block_count": translatable_blocks,
        "caption_like_block_count": caption_like_blocks,
        "paragraph_candidate_count": len(paragraph_candidates) if isinstance(paragraph_candidates, list) else 0,
        "ambiguous_reading_order_pages": int(reading_order_summary.get("ambiguous_page_count", 0) or 0),
    }


def build_pdf_document_model(path: str | Path) -> PDFDocumentModel:
    source_path = str(path)
    doc = fitz.open(path)
    try:
        pages: list[PDFPageModel] = []
        metadata = dict(doc.metadata or {})

        for page_index, page in enumerate(doc):
            page_model = PDFPageModel(
                page_index=page_index,
                width=float(page.rect.width),
                height=float(page.rect.height),
                rotation=int(page.rotation),
                blocks=[],
            )

            page_dict = page.get_text("dict")
            for block_index, raw_block in enumerate(page_dict.get("blocks", [])):
                block_type = raw_block.get("type")
                bbox = _to_bbox(raw_block.get("bbox"))

                if block_type == 0:
                    lines: list[PDFLineModel] = []
                    for raw_line in raw_block.get("lines", []):
                        spans: list[PDFSpanModel] = []
                        for raw_span in raw_line.get("spans", []):
                            text = _normalize_span_text(raw_span)
                            if not text:
                                continue
                            spans.append(
                                PDFSpanModel(
                                    bbox=_to_bbox(raw_span.get("bbox")),
                                    text=text,
                                    font=str(raw_span.get("font", "") or ""),
                                    size=float(raw_span.get("size", 0.0) or 0.0),
                                    color=raw_span.get("color"),
                                )
                            )
                        if spans:
                            lines.append(
                                PDFLineModel(
                                    bbox=_to_bbox(raw_line.get("bbox")),
                                    text=_normalize_line_text(spans),
                                    spans=spans,
                                )
                            )

                    block = PDFBlockModel(
                        block_id=f"p{page_index}-b{block_index}",
                        page_index=page_index,
                        bbox=bbox,
                        text=_normalize_block_text(lines),
                        lines=lines,
                        kind="text",
                    )
                    _flag_text_block(block)
                    page_model.blocks.append(block)
                elif block_type == 1:
                    page_model.blocks.append(
                        PDFBlockModel(
                            block_id=f"p{page_index}-b{block_index}",
                            page_index=page_index,
                            bbox=bbox,
                            text="",
                            kind="image",
                            flags={"image_like", "protected"},
                        )
                    )
                else:
                    page_model.blocks.append(
                        PDFBlockModel(
                            block_id=f"p{page_index}-b{block_index}",
                            page_index=page_index,
                            bbox=bbox,
                            text="",
                            kind="unknown",
                            flags={"protected"} if bbox != (0.0, 0.0, 0.0, 0.0) else set(),
                        )
                    )

            for drawing_index, drawing in enumerate(page.get_drawings()):
                drawing_rect = drawing.get("rect")
                drawing_bbox = _to_bbox(drawing_rect) if drawing_rect else (0.0, 0.0, 0.0, 0.0)
                page_model.blocks.append(
                    PDFBlockModel(
                        block_id=f"p{page_index}-d{drawing_index}",
                        page_index=page_index,
                        bbox=drawing_bbox,
                        text="",
                        kind="drawing",
                        flags={"image_like", "protected"},
                    )
                )

            pages.append(page_model)

        model = PDFDocumentModel(
            source_path=source_path,
            page_count=len(pages),
            pages=pages,
            metadata=metadata,
        )
    finally:
        doc.close()

    mark_formula_like_blocks(model)
    mark_table_like_blocks(model)
    mark_noisy_blocks(model)

    from translation_app.core.file_handlers.pdf_reading_order import (
        build_paragraph_candidates,
        detect_caption_relationships,
        model_to_reading_order_summary,
    )

    detect_caption_relationships(model)
    sort_blocks_reading_order(model)
    model.metadata["paragraph_candidates"] = build_paragraph_candidates(model)
    model.metadata["reading_order_summary"] = model_to_reading_order_summary(model)
    return model
