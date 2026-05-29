"""
Text file handler for translation
"""
from translation_app.config import config
from translation_app.core.file_translation_control import FileTranslationInterrupted, FileTranslationStopRequested
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

            translated_parts = []
            max_length = config.max_text_length
            start = 0
            while start < len(input_text):
                getattr(self.translation_service, "raise_if_file_translation_stopped", lambda: None)()
                chunk = input_text[start:start + max_length]
                if not chunk.strip() or len(chunk.strip()) < 2:
                    translated_parts.append(chunk)
                else:
                    translated_parts.append(
                        self.translation_service.translate_text(chunk, src_lang, dest_lang)
                    )
                start += max_length

            # Write output file safely
            safe_write_text(output_file, "".join(translated_parts))
            
            logger.info(f"Text file translation completed: {output_file}")
        except FileTranslationStopRequested as exc:
            partial_text = "".join(locals().get("translated_parts", []))
            partial_saved = False
            save_error = None
            if partial_text:
                try:
                    safe_write_text(output_file, partial_text)
                    partial_saved = True
                    logger.info(f"Saved partial text output after file translation was {exc.status}: {output_file}")
                except Exception as partial_exc:
                    save_error = partial_exc
                    logger.error(f"Failed to save partial text output after {exc.status}: {partial_exc}")
            raise FileTranslationInterrupted(
                exc.status,
                output_file=output_file,
                partial_saved=partial_saved,
                save_error=save_error,
            ) from exc
        except Exception as e:
            error_msg = f"Error translating text file: {e}"
            logger.error(error_msg)
            raise FileProcessingError(error_msg, original_error=e) from e


