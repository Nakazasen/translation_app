"""
Text file handler for translation
"""
from translation_app.core.translator import TranslationService
from translation_app.utils.error_handler import FileProcessingError
from translation_app.utils.logger import logger
from translation_app.core.encoding_utils import safe_read_text, safe_write_text


class TextHandler:
    """Handler for text file translation"""
    
    def __init__(self, translation_service: TranslationService):
        """
        Initialize text handler
        
        Args:
            translation_service: Translation service instance
        """
        self.translation_service = translation_service
    
    def translate(self, input_file: str, output_file: str, src_lang: str, dest_lang: str) -> None:
        """
        Translate text file
        
        Args:
            input_file: Path to input text file
            output_file: Path to output text file
            src_lang: Source language code
            dest_lang: Destination language code
        
        Raises:
            FileProcessingError: If processing fails
        """
        try:
            logger.info(f"Starting text file translation: {input_file}")
            
            # Read input file safely
            input_text = safe_read_text(input_file)
            
            # Translate text
            translated_text = self.translation_service.translate_long_text(
                input_text, src_lang, dest_lang
            )
            
            # Write output file safely
            safe_write_text(output_file, translated_text)
            
            logger.info(f"Text file translation completed: {output_file}")
        
        except Exception as e:
            error_msg = f"Error translating text file: {e}"
            logger.error(error_msg)
            raise FileProcessingError(error_msg, original_error=e) from e


