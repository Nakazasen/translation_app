"""
Excel COM automation handler for translation with image preservation
Uses win32com to interact with Excel directly, preserving all drawings and images
"""
import os
import sys
import tempfile
import time
from typing import Optional
import platform

from translation_app.core.translator import TranslationService
from translation_app.core.ocr_handler import get_ocr_handler
from translation_app.core.translation_memory import get_segment_hash
from translation_app.utils.error_handler import FileProcessingError
from translation_app.utils.logger import logger

# Check if running on Windows
if platform.system() == 'Windows':
    try:
        import win32com.client
        import pythoncom
        COM_AVAILABLE = True
    except ImportError:
        COM_AVAILABLE = False
        logger.warning("win32com not available. Excel COM handler will not work.")
else:
    COM_AVAILABLE = False


class ExcelComHandler:
    """Handler for Excel file translation using COM automation"""
    
    def __init__(self, translation_service: TranslationService, job_manager=None, job_id: Optional[str] = None):
        """
        Initialize Excel COM handler
        
        Args:
            translation_service: Translation service instance
        """
        self.translation_service = translation_service
        self.ocr_handler = get_ocr_handler()
        self.job_manager = job_manager
        self.job_id = job_id
        self._job_total_segments = 0
        
        if not COM_AVAILABLE:
            raise FileProcessingError(
                "Excel COM automation is not available. "
                "This handler requires Windows and pywin32 package."
            )

    def _make_segment_id(self, sheet_name: str, row: int, col: int) -> str:
        return f"{sheet_name}!R{row}C{col}"
    
    def translate(self, input_file: str, output_file: str, src_lang: str, dest_lang: str) -> None:
        """
        Translate Excel file using COM automation while preserving images
        
        Args:
            input_file: Path to input Excel file
            output_file: Path to output Excel file
            src_lang: Source language code
            dest_lang: Destination language code
        
        Raises:
            FileProcessingError: If processing fails
        """
        if not COM_AVAILABLE:
            raise FileProcessingError(
                "Excel COM automation is not available. "
                "This requires Windows and pywin32 package. "
                "Falling back to openpyxl handler is recommended."
            )
        
        excel_app = None
        workbook = None
        self._current_input_file = input_file
        
        try:
            logger.info(f"Starting Excel COM translation: {input_file}")
            
            # Create Excel application with message filter to handle "application is busy" errors
            try:
                # Use CoInitializeEx to set apartment threading
                pythoncom.CoInitialize()
                
                # Create Excel application with retry logic
                excel_app = None
                max_retries = 3
                for retry in range(max_retries):
                    try:
                        excel_app = win32com.client.Dispatch("Excel.Application")
                        break
                    except pythoncom.com_error as e:
                        if retry < max_retries - 1:
                            logger.warning(f"Failed to create Excel application (attempt {retry + 1}/{max_retries}): {e}. Retrying...")
                            time.sleep(1)
                        else:
                            raise
                
                if excel_app is None:
                    raise Exception("Failed to create Excel application after retries")
                    
            except Exception as e:
                error_msg = (
                    f"Failed to create Excel application: {e}\n\n"
                    "Please ensure Microsoft Excel is installed and accessible."
                )
                logger.error(error_msg)
                raise FileProcessingError(error_msg, original_error=e) from e
            
            # Configure Excel application
            try:
                excel_app.Visible = False
                excel_app.DisplayAlerts = False
                excel_app.ScreenUpdating = False
                excel_app.EnableEvents = False
                excel_app.Calculation = -4105  # xlCalculationManual - disable auto calculation for speed
                excel_app.Interactive = False  # Prevent user interaction
            except Exception as e:
                logger.warning(f"Error configuring Excel application: {e}")
            
            # Open workbook
            logger.info("Opening workbook with Excel COM...")
            try:
                workbook = excel_app.Workbooks.Open(
                    os.path.abspath(input_file),
                    ReadOnly=False,
                    UpdateLinks=0,  # Don't update external links
                    Format=None,
                    Password="",  # No password by default
                    WriteResPassword=""  # No write password by default
                )
            except Exception as e:
                error_str = str(e).lower()
                if "password" in error_str or "protected" in error_str:
                    error_msg = (
                        f"Excel file is password protected: {e}\n\n"
                        "COM handler cannot process password-protected files. "
                        "Please remove password protection or use openpyxl handler."
                    )
                    logger.error(error_msg)
                    raise FileProcessingError(error_msg, original_error=e) from e
                elif "locked" in error_str or "in use" in error_str:
                    error_msg = (
                        f"Excel file is locked or in use: {e}\n\n"
                        "Please close the file in Excel and try again."
                    )
                    logger.error(error_msg)
                    raise FileProcessingError(error_msg, original_error=e) from e
                else:
                    raise
            
            # Process all worksheets
            # Note: Excel COM preserves all shapes, images, and textboxes automatically
            # We only need to translate cell text - Excel handles the rest
            for sheet_idx in range(1, workbook.Worksheets.Count + 1):
                try:
                    # Get sheet with retry for "busy" errors
                    sheet = None
                    max_retries = 3
                    for retry in range(max_retries):
                        try:
                            sheet = workbook.Worksheets.Item(sheet_idx)
                            sheet_name = str(sheet.Name)
                            break
                        except pythoncom.com_error as e:
                            if e.args[0] == -2147417846:  # Application is busy
                                if retry < max_retries - 1:
                                    time.sleep(2)
                                    continue
                            raise
                    
                    if sheet is None:
                        continue
                    
                    logger.info(f"Processing sheet: {sheet_name}")
                    
                    # Translate cells (batch translation for performance)
                    self._translate_sheet(sheet, src_lang, dest_lang)
                    
                    # Translate textboxes and shapes with text
                    self._translate_textboxes_in_sheet(sheet, src_lang, dest_lang)
                    
                    # Process images if OCR is available
                    # Note: Images and textboxes are automatically preserved by Excel COM
                    # We only OCR to add translated text below images
                    if self.ocr_handler.is_installed():
                        self._process_images_in_sheet_com(sheet, src_lang, dest_lang)
                    else:
                        logger.info("Skipping image OCR: Tesseract OCR not installed")
                    
                    # Small delay to let Excel process
                    time.sleep(0.1)
                    
                except Exception as sheet_error:
                    sheet_name_str = f"sheet {sheet_idx}"
                    try:
                        if sheet:
                            sheet_name_str = str(sheet.Name)
                    except:
                        pass
                    logger.warning(f"Error processing {sheet_name_str}: {sheet_error}. Continuing with other sheets...")
                    continue
            
            # Save workbook
            logger.info(f"Saving translated workbook to: {output_file}")
            try:
                # Ensure output directory exists
                output_dir = os.path.dirname(os.path.abspath(output_file))
                if output_dir and not os.path.exists(output_dir):
                    os.makedirs(output_dir, exist_ok=True)
                
                workbook.SaveAs(os.path.abspath(output_file), FileFormat=51)  # xlOpenXMLWorkbook (.xlsx)
                logger.info(f"Excel COM translation completed: {output_file}")
                if self.job_manager and self.job_id:
                    self.job_manager.mark_completed(self.job_id)
            except Exception as save_error:
                error_msg = f"Failed to save translated workbook: {save_error}"
                logger.error(error_msg)
                if self.job_manager and self.job_id:
                    self.job_manager.mark_failed(self.job_id, error_msg)
                raise FileProcessingError(error_msg, original_error=save_error) from save_error
        
        except FileProcessingError:
            # Re-raise FileProcessingError as-is
            raise
        except Exception as e:
            error_msg = f"Error translating Excel file with COM: {e}"
            logger.error(error_msg, exc_info=True)
            if self.job_manager and self.job_id:
                self.job_manager.mark_failed(self.job_id, error_msg)
            raise FileProcessingError(error_msg, original_error=e) from e
        
        finally:
            # Cleanup: Close workbook and quit Excel
            # This is critical to prevent Excel processes from hanging
            try:
                if workbook:
                    try:
                        workbook.Close(SaveChanges=False)
                    except Exception:
                        pass  # Ignore errors when closing
                
                if excel_app:
                    try:
                        excel_app.Quit()
                    except Exception:
                        pass  # Ignore errors when quitting
                    
                    # Release COM objects to free memory
                    try:
                        del workbook
                        del excel_app
                    except Exception:
                        pass
            except Exception as cleanup_error:
                logger.warning(f"Error during Excel cleanup: {cleanup_error}")
                # Try to kill Excel process if it's hanging
                try:
                    import subprocess
                    subprocess.run(['taskkill', '/F', '/IM', 'EXCEL.EXE'], 
                                 capture_output=True, timeout=5)
                except Exception:
                    pass
    
    def _translate_sheet(self, sheet, src_lang: str, dest_lang: str) -> None:
        """
        Translate text in all cells of a worksheet using batch translation for performance
        
        Args:
            sheet: Excel worksheet COM object
            src_lang: Source language code
            dest_lang: Destination language code
        """
        sheet_name = None
        try:
            # Get sheet name first (before any operations that might fail)
            sheet_name = str(sheet.Name)
            
            # Get used range with retry logic for "application is busy" errors
            used_range = None
            max_retries = 3
            for retry in range(max_retries):
                try:
                    used_range = sheet.UsedRange
                    break
                except pythoncom.com_error as e:
                    if e.args[0] == -2147417846:  # Application is busy
                        if retry < max_retries - 1:
                            logger.debug(f"Excel busy, waiting... (attempt {retry + 1}/{max_retries})")
                            time.sleep(1)
                            continue
                    raise
            
            if used_range is None:
                logger.debug(f"Sheet '{sheet_name}' has no used range")
                return
            
            # Collect all cells with text - optimized batch collection
            cells_data = []  # List of (row, col, original_text)
            try:
                # Get values as array for faster access (single COM call)
                # Excel COM returns 2D array: [[row1_col1, row1_col2, ...], [row2_col1, ...], ...]
                try:
                    values_array = used_range.Value
                    start_row = used_range.Row
                    start_col = used_range.Column
                    
                    # Handle different array formats from Excel COM
                    if values_array is None:
                        raise ValueError("Empty range")
                    
                    # Excel COM can return:
                    # - 2D array (list of lists) for multi-cell range
                    # - Single value for single cell
                    # - 1D array (list) for single row/column
                    
                    if isinstance(values_array, (list, tuple)):
                        # Multi-dimensional array
                        if len(values_array) > 0 and isinstance(values_array[0], (list, tuple)):
                            # 2D array: process row by row
                            max_rows = min(len(values_array), 10000)
                            for row_idx in range(max_rows):
                                row_data = values_array[row_idx]
                                if not isinstance(row_data, (list, tuple)):
                                    row_data = [row_data]  # Single value row
                                
                                max_cols = min(len(row_data), 500)
                                for col_idx in range(max_cols):
                                    cell_value = row_data[col_idx]
                                    if cell_value is not None:
                                        cell_str = str(cell_value).strip()
                                        if cell_str:
                                            excel_row = start_row + row_idx
                                            excel_col = start_col + col_idx
                                            cells_data.append((excel_row, excel_col, cell_str))
                        else:
                            # 1D array (single row or column)
                            max_items = min(len(values_array), 10000)
                            for idx in range(max_items):
                                cell_value = values_array[idx]
                                if cell_value is not None:
                                    cell_str = str(cell_value).strip()
                                    if cell_str:
                                        # Assume single row if used_range has 1 row
                                        if used_range.Rows.Count == 1:
                                            excel_row = start_row
                                            excel_col = start_col + idx
                                        else:
                                            excel_row = start_row + idx
                                            excel_col = start_col
                                        cells_data.append((excel_row, excel_col, cell_str))
                    else:
                        # Single value
                        cell_str = str(values_array).strip()
                        if cell_str:
                            cells_data.append((start_row, start_col, cell_str))
                
                except Exception as array_error:
                    # Fallback: iterate cells one by one (slower but more reliable)
                    logger.debug(f"Array access failed for sheet '{sheet_name}': {array_error}. Using cell-by-cell method")
                    row_count = min(used_range.Rows.Count, 10000)
                    col_count = min(used_range.Columns.Count, 500)
                    
                    # Process in smaller chunks to avoid "busy" errors
                    chunk_size = 50
                    for row_chunk_start in range(1, row_count + 1, chunk_size):
                        row_chunk_end = min(row_chunk_start + chunk_size, row_count + 1)
                        
                        for row in range(row_chunk_start, row_chunk_end):
                            for col in range(1, col_count + 1):
                                try:
                                    cell = used_range.Cells(row, col)
                                    cell_value = cell.Value
                                    
                                    if cell_value is not None:
                                        cell_str = str(cell_value).strip()
                                        if cell_str:
                                            cells_data.append((row, col, cell_str))
                                except pythoncom.com_error as e:
                                    if e.args[0] == -2147417846:  # Application is busy
                                        time.sleep(0.1)
                                        continue
                                    continue
                                except Exception:
                                    continue
                        
                        # Small delay between chunks
                        if row_chunk_end < row_count + 1:
                            time.sleep(0.05)
                                
            except Exception as e:
                logger.warning(f"Error collecting cells in sheet '{sheet_name}': {e}")
            
            if not cells_data:
                logger.debug(f"No cells to translate in sheet '{sheet_name}'")
                return
            
            logger.info(f"Found {len(cells_data)} cells to translate in sheet '{sheet_name}'")
            
            if self.job_manager and self.job_id:
                self._job_total_segments += len(cells_data)
                self.job_manager.update_progress(
                    self.job_id,
                    total_segments=self._job_total_segments,
                    current_file=self._current_input_file,
                    current_sheet=sheet_name,
                )

            translation_tasks = []
            for row, col, original_text in cells_data:
                segment_id = self._make_segment_id(sheet_name, row, col)
                if self.job_manager and self.job_id:
                    self.job_manager.record_checkpoint(
                        self.job_id,
                        "segment_started",
                        file=self._current_input_file,
                        sheet=sheet_name,
                        cell=f"R{row}C{col}",
                        segment_id=segment_id,
                        status="running",
                    )
                    self.job_manager.update_progress(
                        self.job_id,
                        current_file=self._current_input_file,
                        current_sheet=sheet_name,
                        current_segment_id=segment_id,
                    )

                future = self.translation_service.executor.submit(
                    self.translation_service.translate_long_text,
                    original_text,
                    src_lang,
                    dest_lang,
                )
                translation_tasks.append((row, col, original_text, segment_id, future))

            # Update cells in batch (minimize COM calls)
            translated_count = 0
            batch_size = 100  # Update cells in batches to avoid overwhelming Excel
            
            for batch_start in range(0, len(translation_tasks), batch_size):
                batch_end = min(batch_start + batch_size, len(translation_tasks))
                batch = translation_tasks[batch_start:batch_end]
                
                for row, col, original_text, segment_id, future in batch:
                    try:
                        translated_text = future.result(timeout=self.translation_service.timeout)
                        
                        # Get cell and update (minimal COM calls)
                        cell = used_range.Cells(row, col)
                        cell.Value = translated_text
                        cell.Font.Name = "Times New Roman"
                        
                        translated_count += 1
                        if self.job_manager and self.job_id:
                            self.job_manager.record_checkpoint(
                                self.job_id,
                                "segment_completed",
                                file=self._current_input_file,
                                sheet=sheet_name,
                                cell=f"R{row}C{col}",
                                segment_id=segment_id,
                                status="completed",
                            )
                            self.job_manager.update_progress(self.job_id, completed_delta=1)
                        
                    except pythoncom.com_error as e:
                        if e.args[0] == -2147417846:  # Application is busy
                            # Wait and retry once
                            time.sleep(0.5)
                            try:
                                translated_text = future.result(timeout=self.translation_service.timeout)
                                cell = used_range.Cells(row, col)
                                cell.Value = translated_text
                                cell.Font.Name = "Times New Roman"
                                translated_count += 1
                                if self.job_manager and self.job_id:
                                    self.job_manager.record_checkpoint(
                                        self.job_id,
                                        "segment_completed",
                                        file=self._current_input_file,
                                        sheet=sheet_name,
                                        cell=f"R{row}C{col}",
                                        segment_id=segment_id,
                                        status="completed",
                                    )
                                    self.job_manager.update_progress(self.job_id, completed_delta=1)
                            except Exception:
                                logger.debug(f"Failed to update cell ({row}, {col}) after retry")
                                if self.job_manager and self.job_id:
                                    self.job_manager.record_failed_item(
                                        self.job_id,
                                        file=self._current_input_file,
                                        sheet=sheet_name,
                                        cell=f"R{row}C{col}",
                                        segment_id=segment_id,
                                        source_lang=src_lang,
                                        target_lang=dest_lang,
                                        error_type=type(e).__name__,
                                        error_message=str(e),
                                        retry_count=0,
                                        source_hash=get_segment_hash(src_lang, dest_lang, original_text),
                                        source_length=len(original_text),
                                    )
                                    self.job_manager.record_checkpoint(
                                        self.job_id,
                                        "segment_failed",
                                        file=self._current_input_file,
                                        sheet=sheet_name,
                                        cell=f"R{row}C{col}",
                                        segment_id=segment_id,
                                        status="failed",
                                    )
                                    self.job_manager.update_progress(self.job_id, failed_delta=1)
                        else:
                            logger.debug(f"Error updating cell ({row}, {col}): {e}")
                            if self.job_manager and self.job_id:
                                self.job_manager.record_failed_item(
                                    self.job_id,
                                    file=self._current_input_file,
                                    sheet=sheet_name,
                                    cell=f"R{row}C{col}",
                                    segment_id=segment_id,
                                    source_lang=src_lang,
                                    target_lang=dest_lang,
                                    error_type=type(e).__name__,
                                    error_message=str(e),
                                    retry_count=0,
                                    source_hash=get_segment_hash(src_lang, dest_lang, original_text),
                                    source_length=len(original_text),
                                )
                                self.job_manager.record_checkpoint(
                                    self.job_id,
                                    "segment_failed",
                                    file=self._current_input_file,
                                    sheet=sheet_name,
                                    cell=f"R{row}C{col}",
                                    segment_id=segment_id,
                                    status="failed",
                                )
                                self.job_manager.update_progress(self.job_id, failed_delta=1)
                    except Exception as e:
                        logger.debug(f"Error updating cell ({row}, {col}): {e}")
                        if self.job_manager and self.job_id:
                            self.job_manager.record_failed_item(
                                self.job_id,
                                file=self._current_input_file,
                                sheet=sheet_name,
                                cell=f"R{row}C{col}",
                                segment_id=segment_id,
                                source_lang=src_lang,
                                target_lang=dest_lang,
                                error_type=type(e).__name__,
                                error_message=str(e),
                                retry_count=0,
                                source_hash=get_segment_hash(src_lang, dest_lang, original_text),
                                source_length=len(original_text),
                            )
                            self.job_manager.record_checkpoint(
                                self.job_id,
                                "segment_failed",
                                file=self._current_input_file,
                                sheet=sheet_name,
                                cell=f"R{row}C{col}",
                                segment_id=segment_id,
                                status="failed",
                            )
                            self.job_manager.update_progress(self.job_id, failed_delta=1)
                
                # Small delay between batches to let Excel process
                if batch_end < len(cells_data):
                    time.sleep(0.05)
            
            logger.info(f"Translated {translated_count}/{len(cells_data)} cells in sheet '{sheet_name}'")
        
        except Exception as e:
            error_msg = f"Error translating sheet"
            if sheet_name:
                error_msg += f" '{sheet_name}'"
            error_msg += f": {e}"
            logger.error(error_msg, exc_info=True)
            # Continue with other sheets even if one fails
    
    def _process_images_in_sheet_com(self, sheet, src_lang: str, dest_lang: str) -> None:
        """
        Process images in Excel sheet with OCR and translation using COM
        
        Args:
            sheet: Excel worksheet COM object
            src_lang: Source language code
            dest_lang: Destination language code
        """
        try:
            logger.info(f"Processing images in sheet '{sheet.Name}' with COM...")
            
            # Get all shapes (images, charts, etc.)
            shapes = sheet.Shapes
            if shapes.Count == 0:
                logger.debug(f"No shapes found in sheet '{sheet.Name}'")
                return
            
            ocr_lang = self.ocr_handler.get_ocr_language(src_lang)
            images_processed = 0
            images_skipped = 0
            
            for i in range(1, shapes.Count + 1):
                temp_image_path = None
                try:
                    shape = shapes.Item(i)
                    
                    # Check if shape is a picture
                    # msoPicture = 11, msoLinkedPicture = 12, msoPlaceholder = 13
                    if shape.Type not in [11, 12]:  # Only process pictures
                        continue
                    
                    # Get shape position to find cell below for translation text
                    top = shape.Top
                    left = shape.Left
                    
                    # Convert points to row/column
                    # Excel uses points (1 point = 1/72 inch)
                    # Approximate: row height ~15 points, column width ~64 points (default)
                    row = int(top / 15) + 1
                    col = int(left / 64) + 1
                    
                    # Export shape to temporary image file
                    try:
                        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
                            temp_image_path = tmp_file.name
                        
                        # Export shape as PNG
                        # Format: 18 = xlPicture (PNG format)
                        shape.Copy()
                        
                        # Get image from clipboard using PIL
                        try:
                            from PIL import ImageGrab, Image
                            clipboard_img = ImageGrab.grabclipboard()
                            
                            if clipboard_img and isinstance(clipboard_img, Image.Image):
                                # Save to temp file
                                clipboard_img.save(temp_image_path, 'PNG')
                                
                                # OCR the image
                                text = self.ocr_handler.extract_text_from_image(
                                    clipboard_img, lang=ocr_lang
                                )
                                
                                # Only translate if text is clear
                                if self.ocr_handler.is_text_clear(text):
                                    translated = self.translation_service.translate_long_text(
                                        text, src_lang, dest_lang
                                    )
                                    
                                    # Insert translated text in cell below image
                                    # Find the cell that contains the bottom of the image
                                    bottom_row = row + int(shape.Height / 15) + 1
                                    target_cell = sheet.Cells(bottom_row, col)
                                    target_cell.Value = f"[Dịch ảnh]: {translated}"
                                    target_cell.Font.Name = "Times New Roman"
                                    
                                    images_processed += 1
                                    logger.debug(f"OCR and translated image at ({row}, {col}) in sheet '{sheet.Name}'")
                                else:
                                    images_skipped += 1
                                    logger.debug(f"Image at ({row}, {col}) - text not clear, skipped")
                            else:
                                images_skipped += 1
                                logger.debug(f"Could not get image from clipboard for shape at ({row}, {col})")
                        
                        except ImportError:
                            logger.warning("PIL ImageGrab not available. Skipping OCR for images.")
                            images_skipped += 1
                        except Exception as ocr_error:
                            logger.warning(f"OCR failed for image at ({row}, {col}): {ocr_error}")
                            images_skipped += 1
                        
                    except Exception as export_error:
                        logger.debug(f"Could not export shape at ({row}, {col}): {export_error}")
                        images_skipped += 1
                    
                    finally:
                        # Cleanup temp file if created
                        if temp_image_path and os.path.exists(temp_image_path):
                            try:
                                os.remove(temp_image_path)
                            except Exception:
                                pass
                
                except Exception as exc:
                    logger.warning(f"Error processing shape {i} in sheet '{sheet.Name}': {exc}")
                    images_skipped += 1
                    # Cleanup temp file if exists
                    if temp_image_path and os.path.exists(temp_image_path):
                        try:
                            os.remove(temp_image_path)
                        except Exception:
                            pass
            
            if images_processed > 0:
                logger.info(f"Processed {images_processed} images with clear text in sheet '{sheet.Name}'")
            if images_skipped > 0:
                logger.info(f"Skipped {images_skipped} images in sheet '{sheet.Name}'")
        
        except Exception as exc:
            logger.error(f"Error processing images in sheet '{sheet.Name}': {exc}", exc_info=True)
    
    def _is_text_in_source_language(self, text: str, src_lang: str) -> bool:
        """
        Simple language detection based on character patterns
        
        Args:
            text: Text to check
            src_lang: Source language code
            
        Returns:
            True if text appears to be in source language
        """
        if not text or len(text.strip()) < 2:
            return False
        
        text_lower = text.lower()
        
        # Vietnamese detection: has Vietnamese diacritics
        if src_lang.lower() in ['vi', 'vietnamese']:
            vietnamese_chars = 'àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ'
            if any(char in text for char in vietnamese_chars):
                return True
            # Also check for common Vietnamese words
            vietnamese_words = ['của', 'và', 'là', 'được', 'cho', 'với', 'trong', 'này', 'đó', 'có', 'không']
            words = text_lower.split()
            if any(word in vietnamese_words for word in words):
                return True
        
        # Japanese detection: has hiragana, katakana, or kanji
        elif src_lang.lower() in ['ja', 'japanese']:
            # Check for Japanese characters
            has_hiragana = any('\u3040' <= char <= '\u309F' for char in text)
            has_katakana = any('\u30A0' <= char <= '\u30FF' for char in text)
            has_kanji = any('\u4E00' <= char <= '\u9FAF' for char in text)
            if has_hiragana or has_katakana or has_kanji:
                return True
        
        # Chinese detection: has Chinese characters
        elif src_lang.lower() in ['zh', 'zh-cn', 'zh-cn', 'chinese']:
            has_chinese = any('\u4E00' <= char <= '\u9FFF' for char in text)
            if has_chinese:
                return True
        
        # English detection: mostly ASCII letters
        elif src_lang.lower() in ['en', 'english']:
            # If text is mostly ASCII and has English-like words
            ascii_ratio = sum(1 for c in text if c.isascii() and (c.isalpha() or c.isspace())) / len(text) if text else 0
            if ascii_ratio > 0.8:
                return True
        
        # Default: if we can't detect, assume it needs translation
        # (safer to translate than skip)
        return True
    
    def _get_text_from_shape(self, shape) -> Optional[str]:
        """
        Extract text from Excel shape using multiple methods
        
        Args:
            shape: Excel shape COM object
            
        Returns:
            Text content or None if no text found
        """
        text_content = None
        
        # Method 1: TextFrame.TextRange.Text (most common)
        try:
            if hasattr(shape, 'TextFrame'):
                text_frame = shape.TextFrame
                if text_frame is not None:
                    # Check if TextFrame has text
                    if hasattr(text_frame, 'HasText') and text_frame.HasText:
                        text_range = text_frame.TextRange
                        if text_range is not None:
                            text_content = str(text_range.Text).strip()
                            if text_content:
                                return text_content
                    # Try direct access without HasText check
                    try:
                        text_range = text_frame.TextRange
                        if text_range is not None:
                            text_content = str(text_range.Text).strip()
                            if text_content:
                                return text_content
                    except Exception:
                        pass
        except Exception:
            pass
        
        # Method 2: Direct Text property (for TextBox)
        try:
            if hasattr(shape, 'Text'):
                text_content = str(shape.Text).strip()
                if text_content:
                    return text_content
        except Exception:
            pass
        
        # Method 3: Check TextFrame.Characters (for complex text)
        try:
            if hasattr(shape, 'TextFrame') and shape.TextFrame is not None:
                if hasattr(shape.TextFrame, 'Characters'):
                    chars = shape.TextFrame.Characters()
                    if chars is not None and hasattr(chars, 'Text'):
                        text_content = str(chars.Text).strip()
                        if text_content:
                            return text_content
        except Exception:
            pass
        
        return None
    
    def _set_text_to_shape(self, shape, text: str) -> bool:
        """
        Set text to Excel shape using multiple methods with improved error handling
        
        Args:
            shape: Excel shape COM object
            text: Text to set
            
        Returns:
            True if successful
        """
        # Method 1: Set text via TextFrame.TextRange.Text (most common method)
        try:
            if hasattr(shape, 'TextFrame'):
                text_frame = shape.TextFrame
                if text_frame is not None:
                    text_range = text_frame.TextRange
                    if text_range is not None:
                        # Direct assignment (works for most cases)
                        text_range.Text = text
                        return True
        except Exception as e:
            logger.debug(f"Method 1 (TextFrame.TextRange direct) failed: {e}")
        
        # Method 1b: Clear first, then set (for shapes with existing text)
        try:
            if hasattr(shape, 'TextFrame'):
                text_frame = shape.TextFrame
                if text_frame is not None:
                    # Check if TextFrame has text
                    if hasattr(text_frame, 'HasText') and text_frame.HasText:
                        text_range = text_frame.TextRange
                        if text_range is not None:
                            # Get current text to determine length
                            try:
                                current_text = str(text_range.Text)
                                if current_text:
                                    # Delete existing text
                                    text_range.Delete()
                            except Exception:
                                pass  # Ignore if delete fails
                            
                            # Set new text
                            text_range.Text = text
                            return True
        except Exception as e:
            logger.debug(f"Method 1b (TextFrame.TextRange with clear) failed: {e}")
        
        # Method 2: Use Characters collection to replace text
        try:
            if hasattr(shape, 'TextFrame') and shape.TextFrame is not None:
                text_frame = shape.TextFrame
                if hasattr(text_frame, 'Characters'):
                    chars = text_frame.Characters()
                    if chars is not None:
                        # Get current text length
                        try:
                            current_text = str(chars.Text) if hasattr(chars, 'Text') else ""
                            if current_text:
                                # Delete existing characters
                                chars.Delete()
                        except Exception:
                            pass
                        
                        # Insert new text
                        try:
                            if hasattr(text_frame, 'InsertAfter'):
                                text_frame.InsertAfter(text)
                                return True
                        except Exception:
                            pass
        except Exception as e:
            logger.debug(f"Method 2 (Characters) failed: {e}")
        
        # Method 3: Direct Text property (for TextBox type=17)
        try:
            if hasattr(shape, 'Text'):
                # For TextBox, try to clear and set
                try:
                    # Try to get current text length to clear
                    current_text = str(shape.Text) if hasattr(shape, 'Text') else ""
                    if current_text:
                        # Clear by setting empty string first
                        shape.Text = ""
                except Exception:
                    pass
                
                # Set new text
                shape.Text = text
                return True
        except Exception as e:
            logger.debug(f"Method 3 (Direct Text) failed: {e}")
        
        # Method 4: Use TextFrame.Characters().Text (alternative)
        try:
            if hasattr(shape, 'TextFrame') and shape.TextFrame is not None:
                text_frame = shape.TextFrame
                if hasattr(text_frame, 'Characters'):
                    chars = text_frame.Characters(1, 1)  # Get first character
                    if chars is not None:
                        # Get full text range
                        full_range = text_frame.Characters()
                        if full_range is not None:
                            # Delete all and insert new
                            try:
                                full_range.Delete()
                            except Exception:
                                pass
                            
                            # Insert new text
                            try:
                                if hasattr(text_frame, 'InsertAfter'):
                                    text_frame.InsertAfter(text)
                                    return True
                                elif hasattr(full_range, 'InsertAfter'):
                                    full_range.InsertAfter(text)
                                    return True
                            except Exception:
                                pass
        except Exception as e:
            logger.debug(f"Method 4 (Characters alternative) failed: {e}")
        
        # Method 5: Try setting via TextFrame2 (if available in newer Excel versions)
        try:
            if hasattr(shape, 'TextFrame2'):
                text_frame2 = shape.TextFrame2
                if text_frame2 is not None:
                    text_range2 = text_frame2.TextRange
                    if text_range2 is not None:
                        text_range2.Text = text
                        return True
        except Exception as e:
            logger.debug(f"Method 5 (TextFrame2) failed: {e}")
        
        return False
    
    def _translate_textboxes_in_sheet(self, sheet, src_lang: str, dest_lang: str) -> None:
        """
        Translate text in textboxes and shapes with text in Excel sheet
        Improved version with better shape detection and language filtering
        
        Args:
            sheet: Excel worksheet COM object
            src_lang: Source language code
            dest_lang: Destination language code
        """
        try:
            sheet_name = str(sheet.Name)
            logger.info(f"Processing textboxes and shapes with text in sheet '{sheet_name}'...")
            
            # Get all shapes
            shapes = sheet.Shapes
            if shapes.Count == 0:
                logger.debug(f"No shapes found in sheet '{sheet_name}'")
                return
            
            logger.info(f"Found {shapes.Count} total shapes in sheet '{sheet_name}'")
            
            # Collect textboxes and shapes with text
            textboxes_data = []  # List of (shape_index, shape_name, original_text, shape_object, shape_type)
            
            for i in range(1, shapes.Count + 1):
                try:
                    shape = shapes.Item(i)
                    shape_name = ""
                    shape_type = 0
                    
                    try:
                        shape_name = str(shape.Name) if hasattr(shape, 'Name') else f"Shape_{i}"
                        shape_type = int(shape.Type) if hasattr(shape, 'Type') else 0
                    except Exception:
                        pass
                    
                    # Get text from shape using multiple methods
                    text_content = self._get_text_from_shape(shape)
                    
                    if text_content and len(text_content.strip()) > 0:
                        # Check if text is in source language (to avoid translating already translated text)
                        if self._is_text_in_source_language(text_content, src_lang):
                            textboxes_data.append((i, shape_name, text_content, shape, shape_type))
                            logger.debug(f"Found textbox/shape {i} ({shape_name}, type={shape_type}): '{text_content[:50]}...'")
                        else:
                            logger.debug(f"Skipping shape {i} - text doesn't appear to be in source language '{src_lang}': '{text_content[:50]}...'")
                
                except pythoncom.com_error as e:
                    if e.args[0] == -2147417846:  # Application is busy
                        time.sleep(0.5)
                        continue
                    logger.debug(f"Error processing shape {i} for text: {e}")
                    continue
                except Exception as e:
                    logger.debug(f"Error processing shape {i} for text: {e}")
                    continue
            
            if not textboxes_data:
                logger.info(f"No textboxes or shapes with text found in sheet '{sheet_name}' (or all text is already in target language)")
                return
            
            logger.info(f"Found {len(textboxes_data)} textboxes/shapes with text in source language '{src_lang}' in sheet '{sheet_name}'")
            
            # Batch translate all texts
            original_texts = [text for _, _, text, _, _ in textboxes_data]
            try:
                translated_texts = self.translation_service.translate_batch(original_texts, src_lang, dest_lang)
                logger.info(f"Batch translated {len(translated_texts)} textbox texts")
            except Exception as e:
                logger.warning(f"Batch translation failed for textboxes in sheet '{sheet_name}': {e}")
                translated_texts = original_texts  # Keep original on error
            
            # Update textboxes with translated text
            translated_count = 0
            failed_count = 0
            
            for idx, (shape_idx, shape_name, original_text, shape, shape_type) in enumerate(textboxes_data):
                try:
                    translated_text = translated_texts[idx]
                    
                    # Skip if translation is same as original (no change)
                    if translated_text.strip() == original_text.strip():
                        logger.debug(f"Shape {shape_idx} - translation same as original, skipping update")
                        continue
                    
                    # Set text using multiple methods with detailed error logging
                    success = False
                    max_retries = 3
                    last_error = None
                    
                    for retry in range(max_retries):
                        try:
                            success = self._set_text_to_shape(shape, translated_text)
                            if success:
                                # Verify the text was actually set
                                try:
                                    verify_text = self._get_text_from_shape(shape)
                                    if verify_text and translated_text.strip() in verify_text.strip():
                                        translated_count += 1
                                        logger.debug(f"Translated textbox/shape {shape_idx} ({shape_name}, type={shape_type}): '{original_text[:30]}...' -> '{translated_text[:30]}...'")
                                        break
                                    else:
                                        logger.debug(f"Shape {shape_idx} - text set but verification failed. Expected: '{translated_text[:30]}...', Got: '{verify_text[:30] if verify_text else None}...'")
                                        success = False
                                except Exception as verify_error:
                                    logger.debug(f"Shape {shape_idx} - verification failed: {verify_error}")
                                    # Still count as success if set_text returned True
                                    translated_count += 1
                                    logger.debug(f"Translated textbox/shape {shape_idx} ({shape_name}, type={shape_type}) - verified via set_text return")
                                    break
                        except pythoncom.com_error as e:
                            last_error = e
                            if e.args[0] == -2147417846:  # Application is busy
                                if retry < max_retries - 1:
                                    time.sleep(0.5)
                                    continue
                            logger.debug(f"COM error updating shape {shape_idx} (retry {retry + 1}): {e}")
                        except Exception as e:
                            last_error = e
                            logger.debug(f"Error updating shape {shape_idx} (retry {retry + 1}): {e}")
                    
                    if not success:
                        failed_count += 1
                        error_msg = f"Failed to update text in shape {shape_idx} ({shape_name}, type={shape_type})"
                        if last_error:
                            error_msg += f": {last_error}"
                        logger.warning(error_msg)
                
                except Exception as e:
                    failed_count += 1
                    logger.warning(f"Error translating textbox {shape_idx}: {e}", exc_info=True)
            
            if translated_count > 0:
                logger.info(f"Successfully translated {translated_count}/{len(textboxes_data)} textboxes/shapes in sheet '{sheet_name}'")
            if failed_count > 0:
                logger.warning(f"Failed to translate {failed_count} textboxes/shapes in sheet '{sheet_name}'")
        
        except Exception as exc:
            sheet_name_str = "unknown sheet"
            try:
                sheet_name_str = str(sheet.Name)
            except:
                pass
            logger.error(f"Error processing textboxes in sheet '{sheet_name_str}': {exc}", exc_info=True)

