"""
Word file handler for translation
"""
import re
import io
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Pt
from PIL import Image
from typing import List, Dict, Any

from translation_app.core.translator import TranslationService
from translation_app.core.ocr_handler import get_ocr_handler
from translation_app.utils.error_handler import FileProcessingError
from translation_app.utils.logger import logger
from translation_app.config import config


class WordHandler:
    """Handler for Word file translation"""
    
    def __init__(self, translation_service: TranslationService):
        """
        Initialize Word handler
        
        Args:
            translation_service: Translation service instance
        """
        self.translation_service = translation_service
        self.ocr_handler = get_ocr_handler()
        self.font_name = 'Times New Roman'
        self.progress_callback = None # Function(text, percentage)

    
    def translate(self, input_file: str, output_file: str, src_lang: str, dest_lang: str) -> Dict[str, Any]:
        """
        Translate Word file using SUPER BATCH strategy (minimal API requests)
        
        Args:
            input_file: Path to input Word file
            output_file: Path to output Word file
            src_lang: Source language code
            dest_lang: Destination language code
        
        Returns:
            Dictionary with processing statistics
        
        Raises:
            FileProcessingError: If processing fails
        """
        try:
            logger.info(f"Starting Word translation (SUPER BATCH mode): {input_file}")
            if self.progress_callback:
                self.progress_callback("Đang đọc nội dung file Word...", 10)
            
            # Check file size
            file_size_mb = self._get_file_size_mb(input_file)
            if file_size_mb > config.warning_file_size_mb:
                logger.warning(f"Large file detected: {file_size_mb:.1f}MB")
            
            doc = Document(input_file)
            stats = {'images_processed': 0, 'images_skipped': 0, 'api_requests': 0}
            
            # OCR and translate images (this still needs individual processing)
            if self.ocr_handler.is_installed():
                if self.progress_callback:
                    self.progress_callback("Đang xử lý hình ảnh trong văn bản...", 20)
                stats.update(self._process_images_in_document(doc, src_lang, dest_lang))
            else:
                logger.info("Skipping image OCR: Tesseract OCR not installed")
            
            # ========================================================
            # SUPER BATCH TRANSLATION - Minimize API requests
            # ========================================================
            # Step 1: Collect ALL texts (paragraphs + table cells)
            if self.progress_callback:
                self.progress_callback("Đang tổng hợp nội dung văn bản...", 30)
            all_texts = []
            text_locations = []  # Track where each text came from
            
            # Collect from paragraphs
            for idx, paragraph in enumerate(doc.paragraphs):
                text = paragraph.text
                if text and text.strip():
                    all_texts.append(text.strip())
                    text_locations.append(('paragraph', idx))
            
            # Collect from tables
            for table_idx, table in enumerate(doc.tables):
                for row_idx, row in enumerate(table.rows):
                    for cell_idx, cell in enumerate(row.cells):
                        for para_idx, para in enumerate(cell.paragraphs):
                            text = para.text
                            if text and text.strip():
                                all_texts.append(text.strip())
                                text_locations.append(('table', table_idx, row_idx, cell_idx, para_idx))
            
            logger.info(f"Collected {len(all_texts)} text blocks for translation")
            
            # Step 2: Translate ALL at once using delimiter strategy
            if all_texts:
                if self.progress_callback:
                    self.progress_callback(f"Đang dịch {len(all_texts)} khối văn bản...", 50)
                translated_texts = self._super_batch_translate(all_texts, src_lang, dest_lang)
                stats['api_requests'] = 1 + (len(all_texts) // 5000)  # Estimate
                
                # Step 3: Map translated texts back to their locations
                if self.progress_callback:
                    self.progress_callback("Đang ghi nội dung đã dịch vào file...", 80)
                for i, (location, translated_text) in enumerate(zip(text_locations, translated_texts)):
                    try:
                        if location[0] == 'paragraph':
                            idx = location[1]
                            para = doc.paragraphs[idx]
                            para.text = translated_text
                            for run in para.runs:
                                run.font.name = self.font_name
                                run._element.rPr.rFonts.set(qn('w:eastAsia'), self.font_name)
                        elif location[0] == 'table':
                            _, table_idx, row_idx, cell_idx, para_idx = location
                            cell = doc.tables[table_idx].rows[row_idx].cells[cell_idx]
                            if para_idx < len(cell.paragraphs):
                                cell.paragraphs[para_idx].text = translated_text
                                for run in cell.paragraphs[para_idx].runs:
                                    run.font.name = self.font_name
                                    run._element.rPr.rFonts.set(qn('w:eastAsia'), self.font_name)
                    except Exception as e:
                        logger.warning(f"Error applying translation at location {location}: {e}")
            
            # Translate shapes/textboxes (usually small, keep separate)
            if self.progress_callback:
                self.progress_callback("Đang dịch các textbox và hình vẽ...", 90)
            self._translate_shapes(doc, src_lang, dest_lang)
            
            # Save document
            if self.progress_callback:
                self.progress_callback("Đang lưu file kết quả...", 95)
            doc.save(output_file)
            logger.info(f"Word translation completed: {output_file} (API requests: ~{stats['api_requests']})")
            
            if self.progress_callback:
                self.progress_callback("Hoàn tất!", 100)
            
            return stats
        
        except Exception as e:
            error_msg = f"Error translating Word file: {e}"
            logger.error(error_msg)
            raise FileProcessingError(error_msg, original_error=e) from e

    
    def _super_batch_translate(self, texts: List[str], src_lang: str, dest_lang: str) -> List[str]:
        """
        Translate all texts using SUPER BATCH strategy
        Joins all texts with a delimiter, translates as one, then splits back
        
        This minimizes API requests from N to 1-2
        
        Args:
            texts: List of texts to translate
            src_lang: Source language
            dest_lang: Destination language
            
        Returns:
            List of translated texts (same order as input)
        """
        if not texts:
            return []
        
        # Sử dụng UUID làm delimiter để đảm bảo không bị dịch và không xuất hiện trong text thông thường
        import uuid
        DELIMITER = f"|||{uuid.uuid4().hex}|||"
        
        # Join all texts
        combined_text = DELIMITER.join(texts)
        
        # Translate the combined text
        # Split into chunks if too large (Google Translate has limits)
        MAX_CHARS = 4500  # Safe limit for translation API
        
        if len(combined_text) <= MAX_CHARS:
            # Single request for everything
            logger.info(f"SUPER BATCH: Translating {len(texts)} texts in 1 request ({len(combined_text)} chars)")
            try:
                translated_combined = self.translation_service.translate_text(combined_text, src_lang, dest_lang)
                # Split back
                translated_texts = translated_combined.split(DELIMITER)
                
                # Handle mismatch (delimiter got modified by translation)
                if len(translated_texts) != len(texts):
                    logger.warning(f"Delimiter mismatch: expected {len(texts)}, got {len(translated_texts)}. Falling back to batch.")
                    return self.translation_service.translate_batch(texts, src_lang, dest_lang)
                
                return translated_texts
            except Exception as e:
                logger.warning(f"Super batch failed: {e}. Falling back to regular batch.")
                return self.translation_service.translate_batch(texts, src_lang, dest_lang)
        else:
            # Split into mega-chunks (each chunk contains multiple texts)
            logger.info(f"SUPER BATCH: Text too large ({len(combined_text)} chars), splitting into mega-chunks")
            translated_results = []
            current_chunk = []
            current_size = 0
            
            for text in texts:
                text_with_delim = text + DELIMITER
                if current_size + len(text_with_delim) > MAX_CHARS and current_chunk:
                    # Translate current chunk
                    chunk_combined = DELIMITER.join(current_chunk)
                    try:
                        translated_chunk = self.translation_service.translate_text(chunk_combined, src_lang, dest_lang)
                        translated_results.extend(translated_chunk.split(DELIMITER))
                    except Exception as e:
                        logger.warning(f"Chunk translation failed: {e}. Keeping original.")
                        translated_results.extend(current_chunk)
                    
                    current_chunk = [text]
                    current_size = len(text)
                else:
                    current_chunk.append(text)
                    current_size += len(text_with_delim)
            
            # Translate remaining chunk
            if current_chunk:
                chunk_combined = DELIMITER.join(current_chunk)
                try:
                    translated_chunk = self.translation_service.translate_text(chunk_combined, src_lang, dest_lang)
                    translated_results.extend(translated_chunk.split(DELIMITER))
                except Exception as e:
                    logger.warning(f"Final chunk translation failed: {e}. Keeping original.")
                    translated_results.extend(current_chunk)
            
            # Ensure result length matches input
            while len(translated_results) < len(texts):
                translated_results.append(texts[len(translated_results)])
            
            logger.info(f"SUPER BATCH: Translated {len(texts)} texts in {1 + len(combined_text) // MAX_CHARS} requests")
            return translated_results[:len(texts)]
    
    def _get_file_size_mb(self, file_path: str) -> float:
        """Get file size in MB"""
        import os
        return os.path.getsize(file_path) / (1024 * 1024)
    
    def _extract_all_images_from_word(self, doc: Document) -> List[Dict[str, Any]]:
        """Extract all images from Word document"""
        images = []
        processed_rIds = set()
        
        # Method 1: Use inline_shapes
        try:
            for shape_idx, shape in enumerate(doc.inline_shapes):
                try:
                    if shape.type == 3:  # 3 = picture
                        try:
                            img_bytes = shape._inline.graphic.graphicData.pic.blipFill.blip.embed
                            if img_bytes and img_bytes not in processed_rIds and img_bytes in doc.part.related_parts:
                                rel = doc.part.related_parts[img_bytes]
                                if 'image' in rel.content_type:
                                    para_idx = 0
                                    for idx, para in enumerate(doc.paragraphs):
                                        if img_bytes in para._element.xml:
                                            para_idx = idx
                                            break
                                    images.append({
                                        'type': 'inline',
                                        'para_idx': para_idx,
                                        'rId': img_bytes,
                                        'blob': rel.blob,
                                        'element': doc.paragraphs[para_idx] if para_idx < len(doc.paragraphs) else None
                                    })
                                    processed_rIds.add(img_bytes)
                        except AttributeError:
                            try:
                                xml_str = shape._inline.xml
                                match = re.search(r'r:embed="([^"]+)"', xml_str)
                                if match:
                                    rId = match.group(1)
                                    if rId not in processed_rIds and rId in doc.part.related_parts:
                                        rel = doc.part.related_parts[rId]
                                        if 'image' in rel.content_type:
                                            para_idx = 0
                                            for idx, para in enumerate(doc.paragraphs):
                                                if rId in para._element.xml:
                                                    para_idx = idx
                                                    break
                                            images.append({
                                                'type': 'inline',
                                                'para_idx': para_idx,
                                                'rId': rId,
                                                'blob': rel.blob,
                                                'element': doc.paragraphs[para_idx] if para_idx < len(doc.paragraphs) else None
                                            })
                                            processed_rIds.add(rId)
                            except Exception as e2:
                                logger.debug(f"Error extracting inline shape {shape_idx}: {e2}")
                except Exception as e:
                    logger.debug(f"Error processing inline shape {shape_idx}: {e}")
        except Exception as e:
            logger.debug(f"Error iterating inline_shapes: {e}")
        
        # Method 2: Search XML for all images (including in tables)
        try:
            for para_idx, para in enumerate(doc.paragraphs):
                try:
                    xml_str = para._element.xml
                    matches = re.findall(r'r:embed="([^"]+)"', xml_str)
                    for rId in matches:
                        if rId not in processed_rIds and rId in doc.part.related_parts:
                            rel = doc.part.related_parts[rId]
                            if 'image' in rel.content_type:
                                images.append({
                                    'type': 'inline',
                                    'para_idx': para_idx,
                                    'rId': rId,
                                    'blob': rel.blob,
                                    'element': para
                                })
                                processed_rIds.add(rId)
                except Exception as e:
                    logger.debug(f"Error extracting image from paragraph {para_idx}: {e}")
            
            for table_idx, table in enumerate(doc.tables):
                for row_idx, row in enumerate(table.rows):
                    for cell_idx, cell in enumerate(row.cells):
                        for para_idx, para in enumerate(cell.paragraphs):
                            try:
                                xml_str = para._element.xml
                                matches = re.findall(r'r:embed="([^"]+)"', xml_str)
                                for rId in matches:
                                    if rId not in processed_rIds and rId in doc.part.related_parts:
                                        rel = doc.part.related_parts[rId]
                                        if 'image' in rel.content_type:
                                            images.append({
                                                'type': 'table',
                                                'table_idx': table_idx,
                                                'row_idx': row_idx,
                                                'cell_idx': cell_idx,
                                                'para_idx': para_idx,
                                                'rId': rId,
                                                'blob': rel.blob,
                                                'element': para
                                            })
                                            processed_rIds.add(rId)
                            except Exception as e:
                                logger.debug(f"Error extracting image from table [{table_idx}][{row_idx}][{cell_idx}]: {e}")
        except Exception as e:
            logger.debug(f"Error searching XML: {e}")
        
        # Method 3: Find remaining images from related_parts
        for rel_id, rel in doc.part.related_parts.items():
            if 'image' in rel.content_type and rel_id not in processed_rIds:
                try:
                    found = False
                    for para_idx, para in enumerate(doc.paragraphs):
                        if rel_id in para._element.xml:
                            images.append({
                                'type': 'floating',
                                'para_idx': para_idx,
                                'rId': rel_id,
                                'blob': rel.blob,
                                'element': para
                            })
                            processed_rIds.add(rel_id)
                            found = True
                            break
                    
                    if not found and doc.paragraphs:
                        images.append({
                            'type': 'floating',
                            'para_idx': 0,
                            'rId': rel_id,
                            'blob': rel.blob,
                            'element': doc.paragraphs[0]
                        })
                        processed_rIds.add(rel_id)
                except Exception as e:
                    logger.debug(f"Error extracting floating image {rel_id}: {e}")
        
        return images
    
    def _process_images_in_document(self, doc: Document, src_lang: str, dest_lang: str) -> Dict[str, int]:
        """Process images in document with OCR and translation"""
        logger.info("Processing images in document...")
        all_images = self._extract_all_images_from_word(doc)
        logger.info(f"Found {len(all_images)} images in document")
        
        ocr_lang = self.ocr_handler.get_ocr_language(src_lang)
        images_processed = 0
        images_skipped = 0
        
        # Sort by para_idx descending to avoid index errors when inserting
        sorted_images = sorted(all_images, key=lambda x: x.get('para_idx', 0), reverse=True)
        
        for img_idx, img_info in enumerate(sorted_images):
            try:
                img = Image.open(io.BytesIO(img_info['blob']))
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # OCR với logging đầy đủ cho việc debug
                text = ""
                try:
                    text = self.ocr_handler.extract_text_from_image(img, lang=ocr_lang)
                except Exception as ocr_error:
                    logger.warning(f"OCR failed with lang '{ocr_lang}' for image {img_idx + 1}: {ocr_error}. Trying 'eng'...")
                    try:
                        text = self.ocr_handler.extract_text_from_image(img, lang='eng')
                    except Exception as eng_ocr_error:
                        logger.error(f"OCR failed completely for image {img_idx + 1} with both '{ocr_lang}' and 'eng': {eng_ocr_error}")
                        text = ""
                
                # Only translate if text is clear
                if self.ocr_handler.is_text_clear(text):
                    translated = self.translation_service.translate_long_text(text, src_lang, dest_lang)
                    self._insert_translated_image_text(doc, img_info, translated)
                    images_processed += 1
                else:
                    images_skipped += 1
                    logger.debug(f"Skipping image {img_idx + 1}: text not clear")
            except Exception as exc:
                logger.warning(f"Error OCR/translating image {img_idx + 1}: {exc}")
                images_skipped += 1
        
        if images_processed > 0:
            logger.info(f"Processed {images_processed} images with clear text")
        if images_skipped > 0:
            logger.info(f"Skipped {images_skipped} images without clear text")
        
        return {'images_processed': images_processed, 'images_skipped': images_skipped}
    
    def _insert_translated_image_text(self, doc: Document, img_info: Dict[str, Any], translated: str) -> None:
        """Insert translated image text into document"""
        if img_info['type'] in ('inline', 'floating'):
            para_idx = img_info['para_idx']
            if para_idx < len(doc.paragraphs):
                para = doc.paragraphs[para_idx]
                if img_info['rId'] in para._element.xml:
                    try:
                        body = doc._body._body
                        para_elem = para._element
                        para_index = list(body).index(para_elem)
                        
                        p_xml = f'<w:p {nsdecls("w")}><w:r><w:t>[Dịch ảnh]: {translated}</w:t></w:r></w:p>'
                        new_para_elem = parse_xml(p_xml)
                        body.insert(para_index + 1, new_para_elem)
                        
                        if para_idx + 1 < len(doc.paragraphs):
                            new_para = doc.paragraphs[para_idx + 1]
                            for run in new_para.runs:
                                run.font.name = self.font_name
                                run._element.rPr.rFonts.set(qn('w:eastAsia'), self.font_name)
                                run.font.size = Pt(10)
                    except Exception:
                        # Fallback: add to end of document
                        p_insert = doc.add_paragraph(f"[Dịch ảnh]: {translated}")
                        for run in p_insert.runs:
                            run.font.name = self.font_name
                            run._element.rPr.rFonts.set(qn('w:eastAsia'), self.font_name)
                            run.font.size = Pt(10)
        elif img_info['type'] == 'table':
            table = doc.tables[img_info['table_idx']]
            cell = table.rows[img_info['row_idx']].cells[img_info['cell_idx']]
            p_insert = cell.add_paragraph(f"[Dịch ảnh]: {translated}")
            for run in p_insert.runs:
                run.font.name = self.font_name
                run._element.rPr.rFonts.set(qn('w:eastAsia'), self.font_name)
                run.font.size = Pt(10)
    
    # NOTE: _translate_paragraphs and _translate_tables methods REMOVED
    # They are now integrated into the main translate() method using SUPER BATCH strategy
    # This reduces API requests from N to 1-2
    
    def _translate_shapes(self, doc: Document, src_lang: str, dest_lang: str) -> None:
        """Translate text in shapes/textboxes"""
        logger.info("Translating text in shapes/textboxes...")
        try:
            for shape in doc.inline_shapes:
                if hasattr(shape, 'text') and shape.text:
                    try:
                        translated_text = self.translation_service.translate_long_text(shape.text, src_lang, dest_lang)
                        shape.text = translated_text
                    except Exception as exc:
                        logger.warning(f"Error translating shape: {exc}")
        except Exception as exc:
            logger.warning(f"Error iterating shapes: {exc}")

