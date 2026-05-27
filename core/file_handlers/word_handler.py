"""
Word file handler for translation.
"""
import re
from typing import Any, Dict

from docx import Document

from translation_app.config import config
from translation_app.core.ocr_handler import get_ocr_handler
from translation_app.core.translator import TranslationService
from translation_app.utils.error_handler import FileProcessingError
from translation_app.utils.logger import logger


class WordHandler:
    """Handler for Word file translation."""

    _URL_RE = re.compile(r"^(https?://|www\.)", re.IGNORECASE)
    _EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    _FILE_PATH_RE = re.compile(r"^(?:[A-Za-z]:\\|\\\\|/)[^\r\n]+$")
    _FIELD_HINT_RE = re.compile(r"\b(?:HYPERLINK|MERGEFIELD|PAGE|NUMPAGES|TOC)\b", re.IGNORECASE)

    def __init__(self, translation_service: TranslationService):
        self.translation_service = translation_service
        self.ocr_handler = get_ocr_handler()
        self.progress_callback = None

    def translate(self, input_file: str, output_file: str, src_lang: str, dest_lang: str) -> Dict[str, Any]:
        """Translate a DOCX file while preserving core formatting."""
        try:
            logger.info(f"Starting Word translation: {input_file}")
            if self.progress_callback:
                self.progress_callback("Reading Word document...", 10)

            file_size_mb = self._get_file_size_mb(input_file)
            if file_size_mb > config.warning_file_size_mb:
                logger.warning(f"Large file detected: {file_size_mb:.1f}MB")

            doc = Document(input_file)
            stats = {"images_processed": 0, "images_skipped": 0, "api_requests": 0}

            logger.info("Skipping Word image OCR/write-back to preserve layout during hardening phase")

            if self.progress_callback:
                self.progress_callback("Translating paragraphs...", 35)
            stats["api_requests"] += self._translate_paragraph_collection(doc.paragraphs, src_lang, dest_lang)

            if self.progress_callback:
                self.progress_callback("Translating tables...", 60)
            for table in doc.tables:
                stats["api_requests"] += self._translate_table(table, src_lang, dest_lang)

            if self.progress_callback:
                self.progress_callback("Preserving shapes and images...", 85)
            self._translate_shapes(doc, src_lang, dest_lang)

            if self.progress_callback:
                self.progress_callback("Saving Word document...", 95)
            doc.save(output_file)

            logger.info(f"Word translation completed: {output_file}")
            if self.progress_callback:
                self.progress_callback("Done", 100)

            return stats
        except Exception as exc:
            error_msg = f"Error translating Word file: {exc}"
            logger.error(error_msg)
            raise FileProcessingError(error_msg, original_error=exc) from exc

    def _translate_table(self, table, src_lang: str, dest_lang: str) -> int:
        api_requests = 0
        for row in table.rows:
            for cell in row.cells:
                api_requests += self._translate_paragraph_collection(cell.paragraphs, src_lang, dest_lang)
                for nested_table in cell.tables:
                    api_requests += self._translate_table(nested_table, src_lang, dest_lang)
        return api_requests

    def _translate_paragraph_collection(self, paragraphs, src_lang: str, dest_lang: str) -> int:
        api_requests = 0
        for paragraph in paragraphs:
            api_requests += self._translate_paragraph_runs(paragraph, src_lang, dest_lang)
        return api_requests

    def _translate_paragraph_runs(self, paragraph, src_lang: str, dest_lang: str) -> int:
        api_requests = 0
        for run in paragraph.runs:
            original_text = run.text
            if self._should_skip_text(original_text):
                continue
            if self._run_has_field_markup(run):
                continue
            try:
                translated_text = self.translation_service.translate_long_text(
                    original_text,
                    src_lang,
                    dest_lang,
                )
            except Exception as exc:
                logger.warning(f"Error translating Word run: {exc}")
                continue
            if translated_text != original_text:
                run.text = translated_text
            api_requests += 1
        return api_requests

    def _should_skip_text(self, text: str) -> bool:
        stripped = (text or "").strip()
        if not stripped:
            return True
        if self._URL_RE.match(stripped):
            return True
        if self._EMAIL_RE.match(stripped):
            return True
        if self._FILE_PATH_RE.match(stripped):
            return True
        if self._FIELD_HINT_RE.search(stripped):
            return True
        return False

    def _run_has_field_markup(self, run) -> bool:
        try:
            xml = run._element.xml
        except Exception:
            return False
        return "w:fldChar" in xml or "w:instrText" in xml

    def _get_file_size_mb(self, file_path: str) -> float:
        import os

        return os.path.getsize(file_path) / (1024 * 1024)

    def _translate_shapes(self, doc: Document, src_lang: str, dest_lang: str) -> None:
        """Preserve Word shapes/textboxes as-is in this phase."""
        logger.info("Skipping Word textbox/shape translation to preserve layout during hardening phase")
