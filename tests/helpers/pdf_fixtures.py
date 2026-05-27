"""Runtime PDF fixtures for baseline PDF tests."""

from __future__ import annotations

import concurrent.futures
import io
from pathlib import Path
from typing import Iterable

import fitz
from PIL import Image, ImageDraw


class FakeTranslationService:
    def __init__(self, translations: dict[str, str] | None = None):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.timeout = 5
        self.strategy = "ai"
        self.observer = None
        self.calls: list[str] = []
        self.translations = translations or {}

    def set_runtime_observer(self, observer):
        self.observer = observer

    def clear_runtime_observer(self):
        self.observer = None

    def translate_long_text(self, text, src_lang, dest_lang, max_length=None):
        self.calls.append(text)
        if self.observer:
            self.observer("provider_call", {"provider": "fake"})
        return self.translations.get(text, f"{text}-{dest_lang}")

    def translate_text(self, text, src_lang, dest_lang):
        return self.translate_long_text(text, src_lang, dest_lang)

    def translate_batch(self, texts, src_lang, dest_lang):
        return [self.translate_long_text(text, src_lang, dest_lang) for text in texts]


def _save_document(doc: fitz.Document, path: str | Path) -> None:
    doc.save(path)
    doc.close()


def create_simple_text_pdf(path: str | Path, text: str = "Hello world") -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(72, 72, 320, 180), text, fontsize=14, fontname="helv")
    _save_document(doc, path)
    return Path(path)


def create_two_page_pdf(path: str | Path, page_texts: Iterable[str]) -> Path:
    doc = fitz.open()
    for page_text in page_texts:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 320, 180), str(page_text), fontsize=14, fontname="helv")
    _save_document(doc, path)
    return Path(path)


def create_two_column_pdf(path: str | Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(50, 60, 220, 220),
        "LEFT ONE\nLEFT TWO",
        fontsize=12,
        fontname="helv",
    )
    page.insert_textbox(
        fitz.Rect(320, 60, 520, 220),
        "RIGHT ONE\nRIGHT TWO",
        fontsize=12,
        fontname="helv",
    )
    _save_document(doc, path)
    return Path(path)


def create_table_like_pdf(path: str | Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    headers = ["Item", "Qty", "Price"]
    rows = [
        ["Apple", "2", "10"],
        ["Banana", "5", "8"],
        ["Cherry", "9", "12"],
    ]
    x_positions = [72, 220, 340]
    y = 72
    for col, header in enumerate(headers):
        page.insert_text((x_positions[col], y), header, fontsize=12, fontname="helv")
    y += 36
    for row in rows:
        for col, value in enumerate(row):
            page.insert_text((x_positions[col], y), value, fontsize=12, fontname="helv")
        y += 28
    _save_document(doc, path)
    return Path(path)


def create_image_caption_pdf(path: str | Path) -> Path:
    image = Image.new("RGB", (120, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 108, 108), outline="black", width=3)
    draw.line((12, 12, 108, 108), fill="navy", width=3)
    draw.line((108, 12, 12, 108), fill="darkred", width=3)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(72, 72, 220, 220), stream=buffer.getvalue())
    page.insert_textbox(
        fitz.Rect(72, 236, 320, 280),
        "Caption: Sample image block",
        fontsize=12,
        fontname="helv",
    )
    _save_document(doc, path)
    return Path(path)


def create_formula_like_pdf(path: str | Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    text = "E = mc^2\nSUM(A1:A3)\nx^2 + y^2"
    page.insert_textbox(fitz.Rect(72, 72, 360, 220), text, fontsize=14, fontname="cour")
    _save_document(doc, path)
    return Path(path)


def find_multilingual_font_paths() -> tuple[Path | None, Path | None]:
    latin_candidates = [
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
    ]
    cjk_candidates = [
        Path(r"C:\Windows\Fonts\YuGothM.ttc"),
        Path(r"C:\Windows\Fonts\msgothic.ttc"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
    ]

    latin = next((path for path in latin_candidates if path.exists()), None)
    cjk = next((path for path in cjk_candidates if path.exists()), None)
    return latin, cjk


def create_cjk_vietnamese_pdf(path: str | Path) -> Path | None:
    latin_font, cjk_font = find_multilingual_font_paths()
    if latin_font is None or cjk_font is None:
        return None

    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="latin_font", fontfile=str(latin_font))
    page.insert_font(fontname="cjk_font", fontfile=str(cjk_font))
    page.insert_textbox(
        fitz.Rect(72, 72, 360, 130),
        "Tiếng Việt",
        fontsize=16,
        fontname="latin_font",
    )
    page.insert_textbox(
        fitz.Rect(72, 152, 360, 220),
        "日本語 中文",
        fontsize=16,
        fontname="cjk_font",
    )
    _save_document(doc, path)
    return Path(path)


def create_scanned_image_pdf(path: str | Path, text: str = "Scanned text only") -> Path:
    image = Image.new("RGB", (900, 1200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 70, 830, 1130), outline="black", width=2)
    draw.text((120, 180), text, fill="black")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(20, 20, 575, 822), stream=buffer.getvalue())
    _save_document(doc, path)
    return Path(path)
