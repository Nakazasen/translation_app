"""
PowerPoint file handler for translation
"""
import io
from pptx import Presentation
from PIL import Image
from typing import Dict, Any

from translation_app.core.translator import TranslationService
from translation_app.core.ocr_handler import get_ocr_handler
from translation_app.utils.error_handler import FileProcessingError
from translation_app.utils.logger import logger


class PowerPointHandler:
    """Handler for PowerPoint file translation"""
    
    def __init__(self, translation_service: TranslationService):
        """
        Initialize PowerPoint handler
        
        Args:
            translation_service: Translation service instance
        """
        self.translation_service = translation_service
        self.ocr_handler = get_ocr_handler()
        self.font_name = 'Times New Roman'
    
    def translate(self, input_file: str, output_file: str, src_lang: str, dest_lang: str) -> Dict[str, Any]:
        """
        Translate PowerPoint file
        
        Args:
            input_file: Path to input PowerPoint file
            output_file: Path to output PowerPoint file
            src_lang: Source language code
            dest_lang: Destination language code
        
        Returns:
            Dictionary with processing statistics
        
        Raises:
            FileProcessingError: If processing fails
        """
        try:
            logger.info(f"Starting PowerPoint translation: {input_file}")
            prs = Presentation(input_file)
            
            total_images_processed = 0
            total_images_skipped = 0
            
            for slide in prs.slides:
                # Translate text in shapes
                self._translate_shapes_in_slide(slide, src_lang, dest_lang)
                
                # Translate notes
                self._translate_notes(slide, src_lang, dest_lang)
                
                # OCR and translate images
                if self.ocr_handler.is_installed():
                    stats = self._process_images_in_slide(slide, src_lang, dest_lang)
                    total_images_processed += stats['processed']
                    total_images_skipped += stats['skipped']
                else:
                    logger.info(f"Skipping image OCR in slide {slide.slide_id}: Tesseract OCR not installed")
            
            # Save presentation
            prs.save(output_file)
            logger.info(f"PowerPoint saved (standard shapes translated): {output_file}")
            
            # SPECIAL: Translate Diagram Data (stored in separate XML files)
            # python-pptx doesn't support editing diagram text, so we do it manually
            diagram_count = self._translate_diagram_data(output_file, src_lang, dest_lang)
            if diagram_count > 0:
                logger.info(f"Translated text in {diagram_count} diagram data files")
            
            logger.info(f"PowerPoint translation completed: {output_file}")
            
            return {
                'images_processed': total_images_processed,
                'images_skipped': total_images_skipped,
                'diagrams_translated': diagram_count
            }
        
        except Exception as e:
            error_msg = f"Error translating PowerPoint file: {e}"
            logger.error(error_msg)
            raise FileProcessingError(error_msg, original_error=e) from e

    
    def _translate_shapes_in_slide(self, slide, src_lang: str, dest_lang: str) -> None:
        """Translate text in all shapes of a slide"""
        for shape in slide.shapes:
            self._translate_single_shape(shape, src_lang, dest_lang)
    
    def _translate_single_shape(self, shape, src_lang: str, dest_lang: str) -> None:
        """Translate text in a single shape (handles recursion for groups)"""
        try:
            shape_type = shape.shape_type
            
            # 1. Handle Group Shapes (Recursion)
            if shape_type == 6:  # MSO_SHAPE_TYPE.GROUP
                logger.info(f"Processing group shape with {len(shape.shapes)} sub-shapes...")
                for sub_shape in shape.shapes:
                    self._translate_single_shape(sub_shape, src_lang, dest_lang)
                return

            # 2. Handle Tables
            if hasattr(shape, "has_table") and shape.has_table:
                logger.info("Processing table in slide...")
                for row in shape.table.rows:
                    for cell in row.cells:
                        if cell.text_frame:
                            self._translate_text_frame(cell.text_frame, src_lang, dest_lang)
                return

            # 3. Handle Charts
            if hasattr(shape, "has_chart") and shape.has_chart:
                logger.info("Processing chart in slide...")
                chart = shape.chart
                
                # 3.1. Chart Title
                if chart.has_title:
                    try:
                        if hasattr(chart.chart_title, "text_frame"):
                            self._translate_text_frame(chart.chart_title.text_frame, src_lang, dest_lang)
                    except Exception as e:
                        logger.warning(f"Could not translate chart title: {e}")
                
                # 3.2. Axis Titles (X and Y)
                try:
                    if hasattr(chart, "category_axis") and chart.category_axis.has_title:
                        self._translate_text_frame(chart.category_axis.axis_title.text_frame, src_lang, dest_lang)
                except Exception:
                    pass
                    
                try:
                    if hasattr(chart, "value_axis") and chart.value_axis.has_title:
                        self._translate_text_frame(chart.value_axis.axis_title.text_frame, src_lang, dest_lang)
                except Exception:
                    pass
                return

            # 4. Handle SmartArt / GraphicFrame via XML traversal
            if shape_type == 14:  # MSO_SHAPE_TYPE.GRAPHIC_FRAME (SmartArt, Diagrams)
                try:
                    self._translate_smartart_xml(shape, src_lang, dest_lang)
                except Exception as e:
                    logger.warning(f"Could not translate SmartArt: {e}")
                # Don't return - SmartArt might also have text_frame

            # 5. Handle Standard Shapes with Text Frames (AutoShapes, Textboxes, Callouts, etc.)
            if hasattr(shape, "text_frame"):
                try:
                    tf = shape.text_frame
                    if tf is not None and hasattr(tf, "paragraphs"):
                        # Check if there's any text to translate
                        has_text = any(p.text.strip() for p in tf.paragraphs if p.text)
                        if has_text:
                            self._translate_text_frame(tf, src_lang, dest_lang)
                except Exception as e:
                    logger.debug(f"Could not access text_frame for shape type {shape_type}: {e}")

        except Exception as e:
            logger.warning(f"Error processing shape: {e}")

    
    def _translate_smartart_xml(self, shape, src_lang: str, dest_lang: str) -> None:
        """
        Translate text within SmartArt/Diagrams by directly parsing the XML.
        SmartArt text is stored in <a:t> elements.
        """
        from lxml import etree
        
        # Get the XML element of the shape
        element = shape._element
        
        # Define namespace for DrawingML
        nsmap = {
            'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
            'dgm': 'http://schemas.openxmlformats.org/drawingml/2006/diagram'
        }
        
        # Find all <a:t> text elements within this shape
        text_elements = element.findall('.//a:t', namespaces=nsmap)
        
        for t_elem in text_elements:
            original_text = t_elem.text
            if original_text and original_text.strip() and len(original_text.strip()) > 1:
                try:
                    translated_text = self.translation_service.translate_long_text(
                        original_text, src_lang, dest_lang
                    )
                    t_elem.text = translated_text
                    logger.debug(f"SmartArt text translated: '{original_text[:30]}...' -> '{translated_text[:30]}...'")
                except Exception as e:
                    logger.warning(f"Error translating SmartArt text: {e}")
    
    def _translate_diagram_data(self, pptx_path: str, src_lang: str, dest_lang: str) -> int:
        """
        Translate text in Diagram Data XML files inside the PPTX package.
        
        PowerPoint stores SmartArt/Diagram text in separate XML files:
        ppt/diagrams/data1.xml, ppt/diagrams/data2.xml, etc.
        
        python-pptx doesn't support editing these, so we do it by:
        1. Opening the PPTX as a ZIP archive
        2. Finding and parsing diagram data XML files
        3. Translating <a:t> text elements
        4. Saving back to the archive
        
        Returns:
            Number of diagram files that were translated
        """
        import zipfile
        import tempfile
        import shutil
        import os
        from lxml import etree
        
        diagram_count = 0
        
        try:
            # Create a temp copy to work with
            temp_dir = tempfile.mkdtemp()
            temp_pptx = os.path.join(temp_dir, "temp.pptx")
            shutil.copy2(pptx_path, temp_pptx)
            
            # Track which files need updating
            files_to_update = {}
            
            with zipfile.ZipFile(temp_pptx, 'r') as z:
                for name in z.namelist():
                    # Look for diagram data files
                    if name.startswith('ppt/diagrams/data') and name.endswith('.xml'):
                        content = z.read(name)
                        
                        # Parse XML
                        try:
                            root = etree.fromstring(content)
                            
                            # Find all <a:t> text elements
                            nsmap = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
                            text_elements = root.findall('.//a:t', namespaces=nsmap)
                            
                            text_changed = False
                            for t_elem in text_elements:
                                original_text = t_elem.text
                                if original_text and original_text.strip() and len(original_text.strip()) > 1:
                                    try:
                                        translated_text = self.translation_service.translate_long_text(
                                            original_text, src_lang, dest_lang
                                        )
                                        if translated_text != original_text:
                                            t_elem.text = translated_text
                                            text_changed = True
                                            logger.debug(f"Diagram text: '{original_text[:30]}' -> '{translated_text[:30]}'")
                                    except Exception as e:
                                        logger.warning(f"Error translating diagram text: {e}")
                            
                            if text_changed:
                                # Save modified XML
                                new_content = etree.tostring(root, xml_declaration=True, encoding='UTF-8')
                                files_to_update[name] = new_content
                                diagram_count += 1
                                logger.info(f"Translated diagram: {name}")
                                
                        except Exception as e:
                            logger.warning(f"Error parsing diagram XML {name}: {e}")
            
            # If we have files to update, recreate the PPTX
            if files_to_update:
                # Create new PPTX with updated files
                new_temp_pptx = os.path.join(temp_dir, "new.pptx")
                
                with zipfile.ZipFile(temp_pptx, 'r') as z_in:
                    with zipfile.ZipFile(new_temp_pptx, 'w', zipfile.ZIP_DEFLATED) as z_out:
                        for name in z_in.namelist():
                            if name in files_to_update:
                                z_out.writestr(name, files_to_update[name])
                            else:
                                z_out.writestr(name, z_in.read(name))
                
                # Replace original file
                shutil.copy2(new_temp_pptx, pptx_path)
                logger.info(f"Updated PPTX with translated diagrams: {pptx_path}")
            
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)
            
        except Exception as e:
            logger.error(f"Error translating diagram data: {e}")
        
        return diagram_count


    def _translate_text_frame(self, text_frame, src_lang: str, dest_lang: str) -> None:
        """Helper to translate all paragraphs in a text frame"""
        for paragraph in text_frame.paragraphs:
            original_text = paragraph.text
            if original_text.strip() and len(original_text.strip()) > 1:
                try:
                    translated_text = self.translation_service.translate_long_text(
                        original_text, src_lang, dest_lang
                    )
                    
                    # If has runs, only change first run text, keep formatting
                    if paragraph.runs:
                        paragraph.runs[0].text = translated_text
                        for run in paragraph.runs[1:]:
                            run.text = ""
                        # Set font for all runs (especially the one with text)
                        for run in paragraph.runs:
                            run.font.name = self.font_name
                    else:
                        # If no runs, assign paragraph.text directly
                        paragraph.text = translated_text
                except Exception as exc:
                    logger.warning(f"Error translating text frame content: {exc}")
    
    def _translate_notes(self, slide, src_lang: str, dest_lang: str) -> None:
        """Translate notes (comments) of slide"""
        try:
            notes_slide = slide.notes_slide
            if notes_slide is not None and notes_slide.notes_text_frame is not None:
                for paragraph in notes_slide.notes_text_frame.paragraphs:
                    original_text = paragraph.text
                    if original_text.strip():
                        try:
                            translated_text = self.translation_service.translate_long_text(
                                original_text, src_lang, dest_lang
                            )
                            # If has runs, only change first run text, keep formatting
                            if paragraph.runs:
                                paragraph.runs[0].text = translated_text
                                for run in paragraph.runs[1:]:
                                    run.text = ""
                                # Set font Times New Roman for all runs
                                for run in paragraph.runs:
                                    run.font.name = self.font_name
                            else:
                                paragraph.text = translated_text
                        except Exception as exc:
                            logger.warning(f"Error translating notes in slide {slide.slide_id}: {exc}")
        except AttributeError:
            # Slide doesn't have notes_slide, skip
            pass
        except Exception as exc:
            logger.warning(f"Error processing notes slide {slide.slide_id}: {exc}")
    
    def _process_images_in_slide(self, slide, src_lang: str, dest_lang: str) -> Dict[str, int]:
        """Process images in slide with OCR and translation"""
        logger.info(f"Processing images in slide {slide.slide_id}...")
        ocr_lang = self.ocr_handler.get_ocr_language(src_lang)
        images_processed = 0
        images_skipped = 0
        
        for shape in slide.shapes:
            if shape.shape_type == 13:  # PICTURE
                try:
                    image = shape.image
                    img_bytes = image.blob
                    img_pil = Image.open(io.BytesIO(img_bytes))
                    if img_pil.mode != 'RGB':
                        img_pil = img_pil.convert('RGB')
                    
                    try:
                        text = self.ocr_handler.extract_text_from_image(img_pil, lang=ocr_lang)
                    except Exception:
                        try:
                            text = self.ocr_handler.extract_text_from_image(img_pil, lang='eng')
                        except Exception:
                            text = ""
                    
                    # Only translate if text is clear
                    if self.ocr_handler.is_text_clear(text):
                        translated = self.translation_service.translate_long_text(text, src_lang, dest_lang)
                        # Add textbox containing translated text below image
                        left = shape.left
                        top = shape.top + shape.height + 10000
                        width = shape.width
                        height = 30000
                        txBox = slide.shapes.add_textbox(left, top, width, height)
                        tf = txBox.text_frame
                        tf.text = f"[Dịch ảnh]: {translated}"
                        for paragraph in tf.paragraphs:
                            for run in paragraph.runs:
                                run.font.name = self.font_name
                        images_processed += 1
                    else:
                        images_skipped += 1
                        logger.debug(f"Skipping image in slide: text not clear")
                except Exception as exc:
                    logger.warning(f"Error OCR/translating image PowerPoint: {exc}")
                    images_skipped += 1
        
        if images_processed > 0:
            logger.info(f"Processed {images_processed} images with clear text in slide")
        if images_skipped > 0:
            logger.info(f"Skipped {images_skipped} images without clear text")
        
        return {'processed': images_processed, 'skipped': images_skipped}

