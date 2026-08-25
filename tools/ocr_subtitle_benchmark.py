"""Benchmark Tesseract strategies for Japanese subtitle screenshots.

This script is intentionally separate from the production OCR flow. It helps
compare preprocessing, crop, language, and PSM combinations against a local
subtitle image without saving image artifacts or logging sensitive content.
"""

from __future__ import annotations

import argparse
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")
TESSERACT_CANDIDATES = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
)


def _configure_tesseract_cmd() -> None:
    """Configure pytesseract on Windows when tesseract is not on PATH."""
    if shutil.which("tesseract"):
        return
    for candidate in TESSERACT_CANDIDATES:
        if candidate.exists():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            return


@dataclass(frozen=True)
class OCRStrategy:
    """A single OCR benchmark strategy."""

    name: str
    lang: str
    psm: int
    image: Image.Image


@dataclass(frozen=True)
class OCRScore:
    """Simple heuristic score for OCR output."""

    has_japanese: bool
    text_length: int
    japanese_count: int
    latin_count: int
    symbol_ratio: float
    score: float


def _contains_japanese(text: str) -> bool:
    """Return whether text contains Japanese kana or CJK characters."""
    return bool(JAPANESE_RE.search(text))


def _score_text(text: str) -> OCRScore:
    """Score OCR text with lightweight Japanese-subtitle heuristics."""
    stripped = text.strip()
    compact_chars = [char for char in stripped if not char.isspace()]
    japanese_count = len(JAPANESE_RE.findall(stripped))
    latin_count = len(LATIN_RE.findall(stripped))
    symbol_count = sum(1 for char in compact_chars if not char.isalnum())
    symbol_ratio = symbol_count / len(compact_chars) if compact_chars else 1.0
    score = japanese_count * 3.0 + len(stripped) * 0.15 - latin_count * 0.8 - symbol_ratio * 8.0
    if japanese_count == 0:
        score -= 12.0
    return OCRScore(
        has_japanese=japanese_count > 0,
        text_length=len(stripped),
        japanese_count=japanese_count,
        latin_count=latin_count,
        symbol_ratio=symbol_ratio,
        score=score,
    )


def _resize(image: Image.Image, factor: int) -> Image.Image:
    """Resize an image by a positive integer factor."""
    if factor <= 1:
        return image.copy()
    width, height = image.size
    return image.resize((max(1, width * factor), max(1, height * factor)), Image.Resampling.LANCZOS)


def _bottom_crop(image: Image.Image, ratio: float) -> Image.Image:
    """Return a bottom crop by ratio."""
    width, height = image.size
    safe_ratio = min(max(ratio, 0.1), 0.9)
    top = max(0, int(height * (1 - safe_ratio)))
    return image.crop((0, top, width, height))


def _preprocess_variants(image: Image.Image, prefix: str, factor: int) -> list[tuple[str, Image.Image]]:
    """Build preprocessing variants for one crop/upscale combination."""
    gray = _resize(image.convert("L"), factor)
    contrast = ImageEnhance.Contrast(gray).enhance(1.8)
    sharpen = contrast.filter(ImageFilter.SHARPEN)
    threshold = sharpen.point(lambda pixel: 255 if pixel > 150 else 0)
    low_threshold = sharpen.point(lambda pixel: 255 if pixel > 110 else 0)
    inverted = ImageOps.invert(threshold)
    inverted_low = ImageOps.invert(low_threshold)
    return [
        (f"{prefix}_gray_{factor}x", gray),
        (f"{prefix}_contrast_sharpen_{factor}x", sharpen),
        (f"{prefix}_binary150_{factor}x", threshold),
        (f"{prefix}_binary110_{factor}x", low_threshold),
        (f"{prefix}_invert_binary150_{factor}x", inverted),
        (f"{prefix}_invert_binary110_{factor}x", inverted_low),
    ]


def _build_base_variants(image: Image.Image) -> list[tuple[str, Image.Image]]:
    """Build full-image and subtitle-crop variants before language/PSM expansion."""
    variants: list[tuple[str, Image.Image]] = []
    for factor in (2, 3, 4):
        variants.extend(_preprocess_variants(image, "full", factor))

    for ratio in (0.25, 0.30, 0.35, 0.40, 0.45):
        crop_label = int(ratio * 100)
        crop = _bottom_crop(image, ratio)
        for factor in (3, 4):
            variants.extend(_preprocess_variants(crop, f"bottom{crop_label}", factor))
    return variants


def _build_strategies(image: Image.Image, quick: bool = False) -> Iterable[OCRStrategy]:
    """Expand image variants across Tesseract languages and page segmentation modes."""
    base_variants = _build_base_variants(image)
    if quick:
        preferred_names = (
            "full_contrast_sharpen_3x",
            "full_binary150_3x",
            "full_invert_binary150_3x",
            "bottom30_contrast_sharpen_4x",
            "bottom30_binary150_4x",
            "bottom35_contrast_sharpen_4x",
            "bottom35_binary150_4x",
            "bottom40_contrast_sharpen_4x",
            "bottom40_binary150_4x",
            "bottom40_invert_binary150_4x",
        )
        preferred = {name for name in preferred_names}
        base_variants = [(name, candidate) for name, candidate in base_variants if name in preferred]

    psms = (7, 6) if quick else (6, 7, 11, 13)
    languages = ("jpn", "jpn+eng")
    for name, candidate in base_variants:
        for lang in languages:
            for psm in psms:
                yield OCRStrategy(name=name, lang=lang, psm=psm, image=candidate)


def _preview(text: str, max_len: int = 120) -> str:
    """Return a compact single-line preview of OCR text."""
    compact = " ".join(text.split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 1] + "…"


def run_benchmark(image_path: Path, top_n: int, quick: bool = False) -> int:
    """Run the benchmark and print ranked results."""
    _configure_tesseract_cmd()

    if not image_path.exists():
        print(f"ERROR: Image not found: {image_path}")
        return 2

    image = Image.open(image_path).convert("RGB")
    results: list[tuple[OCRScore, OCRStrategy, str]] = []

    print(f"Input: {image_path}")
    print(f"Image size: {image.size[0]}x{image.size[1]}")
    mode_label = "quick" if quick else "full"
    print(f"Running OCR strategies ({mode_label} mode)...\n")

    for strategy in _build_strategies(image, quick=quick):
        config = f"--psm {strategy.psm}"
        try:
            text = pytesseract.image_to_string(strategy.image, lang=strategy.lang, config=config)
        except pytesseract.TesseractError as exc:
            text = f"[TESSERACT_ERROR] {exc}"
        score = _score_text(text)
        results.append((score, strategy, text))

    results.sort(key=lambda item: item[0].score, reverse=True)
    print(f"Top {min(top_n, len(results))} strategies:")
    print("=" * 100)
    for index, (score, strategy, text) in enumerate(results[:top_n], start=1):
        print(f"#{index:02d} score={score.score:.2f} lang={strategy.lang} psm={strategy.psm} strategy={strategy.name}")
        print(
            "    "
            f"has_jp={score.has_japanese} len={score.text_length} "
            f"jp={score.japanese_count} latin={score.latin_count} symbols={score.symbol_ratio:.1%}"
        )
        print(f"    text: {_preview(text)}")
        print("-" * 100)

    return 0


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Benchmark Tesseract Japanese subtitle OCR strategies.")
    parser.add_argument("image_path", help="Path to a local subtitle screenshot/crop image.")
    parser.add_argument("--top", type=int, default=20, help="Number of ranked results to print.")
    parser.add_argument("--quick", action="store_true", help="Run a smaller strategy set for fast feedback.")
    args = parser.parse_args()
    return run_benchmark(Path(args.image_path), args.top, quick=args.quick)


if __name__ == "__main__":
    raise SystemExit(main())
