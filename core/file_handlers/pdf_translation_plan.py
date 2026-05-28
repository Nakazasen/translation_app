"""Paragraph-aware planning layer for future PDF translation write-back."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from translation_app.core.file_handlers.pdf_model import BBox, PDFBlockModel, PDFDocumentModel
from translation_app.core.file_handlers.pdf_protection import (
    PDFProtectedRegion,
    apply_protected_flags,
    detect_protected_regions,
)
from translation_app.core.file_handlers.pdf_reading_order import PDFParagraphCandidate


@dataclass
class PDFTranslationUnit:
    unit_id: str
    page_index: int
    source_block_ids: list[str]
    source_span_ids: list[str]
    bbox: BBox
    text: str
    reading_order: int
    unit_type: str
    flags: set[str] = field(default_factory=set)
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PDFTranslationPlan:
    document_id: str | None
    page_count: int
    units: list[PDFTranslationUnit] = field(default_factory=list)
    skipped_units: list[PDFTranslationUnit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def _safe_document_id(model: PDFDocumentModel) -> str | None:
    if not model.source_path:
        return None
    return Path(model.source_path).name


def _block_lookup(model: PDFDocumentModel) -> dict[str, PDFBlockModel]:
    return {
        block.block_id: block
        for page in model.pages
        for block in page.blocks
    }


def _region_kinds_by_block(regions: list[PDFProtectedRegion]) -> dict[str, set[str]]:
    region_map: dict[str, set[str]] = {}
    for region in regions:
        for block_id in region.source_block_ids:
            region_map.setdefault(block_id, set()).add(region.kind)
    return region_map


def _unit_bbox(blocks: list[PDFBlockModel]) -> BBox:
    if not blocks:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(block.bbox[0] for block in blocks),
        min(block.bbox[1] for block in blocks),
        max(block.bbox[2] for block in blocks),
        max(block.bbox[3] for block in blocks),
    )


def _source_span_ids(blocks: list[PDFBlockModel]) -> list[str]:
    span_ids: list[str] = []
    for block in blocks:
        for line_index, line in enumerate(block.lines):
            for span_index, span in enumerate(line.spans):
                if not span.text:
                    continue
                span_ids.append(f"{block.block_id}-l{line_index}-s{span_index}")
    return span_ids


def _reading_order_for_blocks(blocks: list[PDFBlockModel]) -> int:
    orders = [block.reading_order for block in blocks if block.reading_order is not None]
    return min(orders) if orders else 0


def _summary_counts(units: list[PDFTranslationUnit]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for unit in units:
        counts[unit.unit_type] = counts.get(unit.unit_type, 0) + 1
    return counts


def _flag_counts(units: list[PDFTranslationUnit]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for unit in units:
        for flag in unit.flags:
            counts[flag] = counts.get(flag, 0) + 1
    return counts


def _skipped_flags_for_block(block: PDFBlockModel, region_kinds: set[str]) -> set[str]:
    flags = {"protected_skipped"}
    if "formula" in region_kinds or "formula_like" in block.flags:
        flags.add("formula_skipped")
    if "table" in region_kinds or "table_like" in block.flags:
        flags.add("table_skipped")
    if "noisy" in region_kinds or "noisy" in block.flags:
        flags.add("noisy_skipped")
    if block.kind in {"image", "drawing"} or "image" in region_kinds or "drawing" in region_kinds or "chart" in region_kinds:
        flags.add("image_skipped")
    if "scanned_page" in region_kinds or "page_scanned" in block.flags:
        flags.add("scanned_skipped")
    return flags


def _make_unit(
    *,
    unit_id: str,
    blocks: list[PDFBlockModel],
    text: str,
    unit_type: str,
    flags: set[str],
    confidence: float,
    metadata: dict[str, Any] | None = None,
) -> PDFTranslationUnit:
    return PDFTranslationUnit(
        unit_id=unit_id,
        page_index=blocks[0].page_index if blocks else 0,
        source_block_ids=[block.block_id for block in blocks],
        source_span_ids=_source_span_ids(blocks),
        bbox=_unit_bbox(blocks),
        text=text,
        reading_order=_reading_order_for_blocks(blocks),
        unit_type=unit_type,
        flags=set(flags),
        confidence=float(confidence),
        metadata=dict(metadata or {}),
    )


def _candidate_is_safe_translatable(
    candidate: PDFParagraphCandidate,
    blocks: list[PDFBlockModel],
    region_map: dict[str, set[str]],
) -> bool:
    if not blocks:
        return False
    for block in blocks:
        region_kinds = region_map.get(block.block_id, set())
        if (
            block.kind != "text"
            or not block.text
            or "translatable" not in block.flags
            or {"formula", "table", "image", "drawing", "chart", "scanned_page", "noisy"} & region_kinds
            or "caption_like" in block.flags
        ):
            return False
    return bool(candidate.text.strip())


def _build_summary(plan: PDFTranslationPlan) -> dict[str, Any]:
    return {
        "document_id": plan.document_id,
        "page_count": plan.page_count,
        "unit_count": len(plan.units),
        "skipped_unit_count": len(plan.skipped_units),
        "translatable_unit_count": sum(1 for unit in plan.units if "translatable" in unit.flags),
        "caption_unit_count": sum(1 for unit in plan.units if "caption" in unit.flags),
        "unit_type_counts": _summary_counts(plan.units),
        "skipped_unit_type_counts": _summary_counts(plan.skipped_units),
        "skipped_flag_counts": _flag_counts(plan.skipped_units),
        "warning_count": len(plan.warnings),
    }


def build_pdf_translation_plan(
    model: PDFDocumentModel,
    regions: list[PDFProtectedRegion] | None = None,
    use_paragraph_candidates: bool = True,
) -> PDFTranslationPlan:
    resolved_regions = list(regions) if regions is not None else detect_protected_regions(model)
    apply_protected_flags(model, resolved_regions)
    region_map = _region_kinds_by_block(resolved_regions)
    block_map = _block_lookup(model)

    units: list[PDFTranslationUnit] = []
    skipped_units: list[PDFTranslationUnit] = []
    warnings: list[str] = []
    consumed_block_ids: set[str] = set()

    paragraph_candidates = model.metadata.get("paragraph_candidates", [])
    if use_paragraph_candidates and isinstance(paragraph_candidates, list):
        ordered_candidates = sorted(
            (
                candidate for candidate in paragraph_candidates if isinstance(candidate, PDFParagraphCandidate)
            ),
            key=lambda candidate: (candidate.page_index, candidate.reading_order, candidate.paragraph_id),
        )
        for candidate in ordered_candidates:
            blocks = [block_map[block_id] for block_id in candidate.block_ids if block_id in block_map]
            if not _candidate_is_safe_translatable(candidate, blocks, region_map):
                continue
            units.append(
                _make_unit(
                    unit_id=candidate.paragraph_id,
                    blocks=blocks,
                    text=candidate.text,
                    unit_type="paragraph" if len(blocks) > 1 else "single_block",
                    flags={"translatable"},
                    confidence=candidate.confidence,
                    metadata={
                        "block_count": len(blocks),
                        "paragraph_candidate_id": candidate.paragraph_id,
                        "column_indexes": sorted({block.metadata.get("column_index", 0) for block in blocks}),
                    },
                )
            )
            consumed_block_ids.update(candidate.block_ids)

    for page in model.pages:
        ordered_blocks = sorted(
            page.blocks,
            key=lambda block: (block.reading_order if block.reading_order is not None else 10**9, block.block_id),
        )
        for block in ordered_blocks:
            if block.block_id in consumed_block_ids:
                continue

            region_kinds = region_map.get(block.block_id, set())
            base_metadata = {
                "column_index": block.metadata.get("column_index"),
                "related_block_ids": list(block.metadata.get("related_block_ids", [])),
                "caption_for_block_id": block.metadata.get("caption_for_block_id"),
            }

            if block.kind == "text" and block.text and "caption_like" in block.flags:
                units.append(
                    _make_unit(
                        unit_id=f"{block.block_id}-caption",
                        blocks=[block],
                        text=block.text,
                        unit_type="caption",
                        flags={"translatable", "caption"},
                        confidence=0.75,
                        metadata=base_metadata,
                    )
                )
                consumed_block_ids.add(block.block_id)
                continue

            if (
                block.kind == "text"
                and block.text
                and "translatable" in block.flags
                and not {"formula", "table", "image", "drawing", "chart", "scanned_page", "noisy"} & region_kinds
            ):
                units.append(
                    _make_unit(
                        unit_id=f"{block.block_id}-single",
                        blocks=[block],
                        text=block.text,
                        unit_type="single_block",
                        flags={"translatable"},
                        confidence=0.7,
                        metadata=base_metadata,
                    )
                )
                consumed_block_ids.add(block.block_id)
                continue

            skipped_units.append(
                _make_unit(
                    unit_id=f"{block.block_id}-skipped",
                    blocks=[block],
                    text=block.text if block.kind == "text" else "",
                    unit_type="single_block",
                    flags=_skipped_flags_for_block(block, region_kinds),
                    confidence=0.95 if block.kind != "text" else 0.8,
                    metadata=base_metadata | {"region_kinds": sorted(region_kinds)},
                )
            )
            consumed_block_ids.add(block.block_id)

    units.sort(key=lambda unit: (unit.page_index, unit.reading_order, unit.unit_id))
    skipped_units.sort(key=lambda unit: (unit.page_index, unit.reading_order, unit.unit_id))

    if model.metadata.get("ambiguous_reading_order_pages", 0):
        warnings.append("ambiguous_reading_order")
    if not units:
        if any(region.kind == "scanned_page" for region in resolved_regions):
            warnings.append("scanned_or_image_only_pdf")
        else:
            warnings.append("no_translatable_units")

    plan = PDFTranslationPlan(
        document_id=_safe_document_id(model),
        page_count=model.page_count,
        units=units,
        skipped_units=skipped_units,
        warnings=warnings,
    )
    validation_errors = validate_translation_plan(plan)
    if validation_errors:
        plan.warnings.extend(validation_errors)
    plan.summary = _build_summary(plan)
    return plan


def get_translatable_units(plan: PDFTranslationPlan) -> list[PDFTranslationUnit]:
    return [unit for unit in plan.units if "translatable" in unit.flags]


def get_skipped_units(plan: PDFTranslationPlan) -> list[PDFTranslationUnit]:
    return list(plan.skipped_units)


def plan_to_public_summary(plan: PDFTranslationPlan) -> dict[str, Any]:
    return {
        "document_id": plan.document_id,
        "page_count": plan.page_count,
        "unit_count": len(plan.units),
        "skipped_unit_count": len(plan.skipped_units),
        "translatable_unit_count": sum(1 for unit in plan.units if "translatable" in unit.flags),
        "caption_unit_count": sum(1 for unit in plan.units if "caption" in unit.flags),
        "unit_type_counts": _summary_counts(plan.units),
        "skipped_unit_type_counts": _summary_counts(plan.skipped_units),
        "skipped_flag_counts": _flag_counts(plan.skipped_units),
        "warnings": list(plan.warnings),
        "warning_count": len(plan.warnings),
    }


def validate_translation_plan(plan: PDFTranslationPlan) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()

    for unit in [*plan.units, *plan.skipped_units]:
        if unit.unit_id in seen_ids:
            errors.append(f"duplicate_unit_id:{unit.unit_id}")
        seen_ids.add(unit.unit_id)

        x0, y0, x1, y1 = unit.bbox
        if x1 <= x0 or y1 <= y0:
            errors.append(f"missing_or_invalid_bbox:{unit.unit_id}")
        if not unit.source_block_ids:
            errors.append(f"missing_source_blocks:{unit.unit_id}")

    return errors

