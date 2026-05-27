"""Deterministic text fitting heuristics for PDF bbox write-back."""

from __future__ import annotations

from dataclasses import dataclass, field
import re


BBox = tuple[float, float, float, float]
_CJK_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass
class PDFTextFitRequest:
    text: str
    bbox: BBox
    font_name: str | None
    font_size: float
    min_font_size: float = 6.0
    line_height_ratio: float = 1.2
    language_hint: str | None = None


@dataclass
class PDFTextFitResult:
    fitted_text: str
    lines: list[str]
    font_size: float
    line_height: float
    bbox: BBox
    overflow: bool
    overflow_reason: str | None
    warnings: list[str] = field(default_factory=list)
    scale_ratio: float = 1.0


def _bbox_size(bbox: BBox) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0), max(0.0, y1 - y0)


def _normalize_whitespace(text: str) -> str:
    return _WHITESPACE_PATTERN.sub(" ", text.strip())


def _is_cjk_text(text: str, language_hint: str | None = None) -> bool:
    hint = (language_hint or "").lower()
    if hint in {"ja", "jp", "jpn", "zh", "zh-cn", "zh-tw", "zho", "cn", "ko", "kor"}:
        return True
    return bool(_CJK_PATTERN.search(text))


def _char_width_factor(char: str, language_hint: str | None = None) -> float:
    if char.isspace():
        return 0.33
    if _CJK_PATTERN.match(char):
        return 1.0
    if char.isdigit():
        return 0.56
    if char in "ilIjtfr":
        return 0.34
    if char in "mwMW@#%&":
        return 0.92
    if char in ".,;:'`!|":
        return 0.24
    if char in "-_()/\\[]{}":
        return 0.32
    if char in "+*=<>^~":
        return 0.52
    if char.isupper():
        return 0.7
    return 0.58


def estimate_text_width(
    text: str,
    font_size: float,
    font_name: str | None = None,
    language_hint: str | None = None,
) -> float:
    del font_name
    if not text:
        return 0.0
    width_units = sum(_char_width_factor(char, language_hint) for char in text)
    return width_units * max(font_size, 0.0)


def _split_long_token(
    token: str,
    max_width: float,
    font_size: float,
    font_name: str | None = None,
    language_hint: str | None = None,
) -> list[str]:
    if not token:
        return []
    chunks: list[str] = []
    current = ""
    for char in token:
        candidate = current + char
        if current and estimate_text_width(candidate, font_size, font_name, language_hint) > max_width:
            chunks.append(current)
            current = char
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [token]


def _wrap_cjk_line(
    text: str,
    max_width: float,
    font_size: float,
    font_name: str | None = None,
    language_hint: str | None = None,
) -> list[str]:
    units = [char for char in text if char != "\n"]
    lines: list[str] = []
    current = ""
    for char in units:
        candidate = current + char
        if current and estimate_text_width(candidate, font_size, font_name, language_hint) > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def _wrap_latin_line(
    text: str,
    max_width: float,
    font_size: float,
    font_name: str | None = None,
    language_hint: str | None = None,
) -> list[str]:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return [""]

    words = normalized.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if current and estimate_text_width(candidate, font_size, font_name, language_hint) > max_width:
            lines.append(current)
            if estimate_text_width(word, font_size, font_name, language_hint) > max_width:
                chunks = _split_long_token(word, max_width, font_size, font_name, language_hint)
                lines.extend(chunks[:-1])
                current = chunks[-1]
            else:
                current = word
        elif not current and estimate_text_width(word, font_size, font_name, language_hint) > max_width:
            chunks = _split_long_token(word, max_width, font_size, font_name, language_hint)
            lines.extend(chunks[:-1])
            current = chunks[-1]
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def wrap_text_to_width(
    text: str,
    max_width: float,
    font_size: float,
    font_name: str | None = None,
    language_hint: str | None = None,
) -> list[str]:
    if text == "":
        return []
    if max_width <= 0 or font_size <= 0:
        return [line for line in text.splitlines() if line] or [text]

    wrapped_lines: list[str] = []
    for raw_line in text.splitlines() or [""]:
        if raw_line == "":
            wrapped_lines.append("")
            continue
        if _is_cjk_text(raw_line, language_hint) and " " not in raw_line:
            wrapped_lines.extend(_wrap_cjk_line(raw_line, max_width, font_size, font_name, language_hint))
        else:
            wrapped_lines.extend(_wrap_latin_line(raw_line, max_width, font_size, font_name, language_hint))
    return wrapped_lines


def fit_text_to_bbox(request: PDFTextFitRequest) -> PDFTextFitResult:
    width, height = _bbox_size(request.bbox)
    warnings: list[str] = []
    original_size = max(request.font_size, request.min_font_size)

    if request.text == "":
        return PDFTextFitResult(
            fitted_text="",
            lines=[],
            font_size=original_size,
            line_height=original_size * request.line_height_ratio,
            bbox=request.bbox,
            overflow=False,
            overflow_reason=None,
            warnings=[],
            scale_ratio=1.0,
        )

    if width <= 40 or height <= 12:
        warnings.append("bbox_too_small")

    font_size = original_size
    best_lines: list[str] = []
    best_font_size = font_size
    best_overflow_score: tuple[float, float] | None = None

    while font_size >= request.min_font_size - 1e-6:
        lines = wrap_text_to_width(
            request.text,
            width,
            font_size,
            request.font_name,
            request.language_hint,
        )
        line_height = font_size * request.line_height_ratio
        total_height = len(lines) * line_height
        widest_line = max((estimate_text_width(line, font_size, request.font_name, request.language_hint) for line in lines), default=0.0)
        overflow_height = max(0.0, total_height - height)
        overflow_width = max(0.0, widest_line - width)

        if best_overflow_score is None or (overflow_height, overflow_width) < best_overflow_score:
            best_overflow_score = (overflow_height, overflow_width)
            best_lines = lines
            best_font_size = font_size

        if overflow_height <= 0.0 and overflow_width <= 0.0:
            if font_size < original_size:
                warnings.append("font_shrunk")
            return PDFTextFitResult(
                fitted_text="\n".join(lines),
                lines=lines,
                font_size=font_size,
                line_height=line_height,
                bbox=request.bbox,
                overflow=False,
                overflow_reason=None,
                warnings=warnings,
                scale_ratio=font_size / original_size if original_size else 1.0,
            )

        font_size = round(font_size - 0.5, 2)

    overflow_warnings = warnings + ["text_overflow"]
    return PDFTextFitResult(
        fitted_text="\n".join(best_lines),
        lines=best_lines,
        font_size=max(best_font_size, request.min_font_size),
        line_height=max(best_font_size, request.min_font_size) * request.line_height_ratio,
        bbox=request.bbox,
        overflow=True,
        overflow_reason="text_overflow",
        warnings=overflow_warnings,
        scale_ratio=(max(best_font_size, request.min_font_size) / original_size) if original_size else 1.0,
    )


def summarize_fit_results(results: list[PDFTextFitResult]) -> dict[str, object]:
    warning_counts: dict[str, int] = {}
    overflow_count = 0
    shrunk_count = 0

    for result in results:
        if result.overflow:
            overflow_count += 1
        if result.scale_ratio < 0.999:
            shrunk_count += 1
        for warning in result.warnings:
            warning_counts[warning] = warning_counts.get(warning, 0) + 1

    return {
        "result_count": len(results),
        "overflow_count": overflow_count,
        "shrunk_count": shrunk_count,
        "warning_counts": warning_counts,
    }
