"""
Email handler for Outlook email translation
"""
import win32com.client
from typing import Optional

from translation_app.core.translator import TranslationService
from translation_app.utils.error_handler import EmailError
from translation_app.utils.logger import logger
from translation_app.config import config


class EmailHandler:
    """Handler for Outlook email translation"""
    
    def __init__(self, translation_service: TranslationService):
        """
        Initialize email handler
        
        Args:
            translation_service: Translation service instance
        """
        self.translation_service = translation_service
    
    def _get_folder_by_name(self, parent_folder, folder_name: str):
        """
        Recursively find folder by name
        
        Args:
            parent_folder: Parent folder to search in
            folder_name: Name of folder to find
        
        Returns:
            Folder object if found, None otherwise
        """
        for folder in parent_folder.Folders:
            if folder.Name == folder_name:
                return folder
            subfolder = self._get_folder_by_name(folder, folder_name)
            if subfolder:
                return subfolder
        return None
    
    def translate_latest_unread_emails(
        self,
        folder_name: str,
        src_lang: str,
        dest_lang: str,
        max_emails: Optional[int] = None
    ) -> int:
        """
        Translate latest unread emails from specified folder
        
        Args:
            folder_name: Name of Outlook folder
            src_lang: Source language code
            dest_lang: Destination language code
            max_emails: Maximum number of emails to translate (defaults to config.max_emails_to_translate)
        
        Returns:
            Number of emails translated
        
        Raises:
            EmailError: If processing fails
        """
        if max_emails is None:
            max_emails = config.max_emails_to_translate
        
        try:
            logger.info(f"Connecting to Outlook...")
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            namespace.Logon("", "", False, True)
            
            if not folder_name or not folder_name.strip():
                raise EmailError("Folder name cannot be empty")
            
            folder_name = folder_name.strip()
            
            root_folder = namespace.Folders.Item(1)
            folder = self._get_folder_by_name(root_folder, folder_name)
            
            if not folder:
                raise EmailError(f"Folder not found: {folder_name}")
            
            # Get unread items
            unread_items = folder.Items.Restrict("[UnRead] = True")
            unread_items.Sort("[ReceivedTime]", True)
            
            count = 0
            for message in unread_items:
                if count >= max_emails:
                    break
                
                try:
                    # Translate subject and body
                    translated_subject = self.translation_service.translate_text(
                        message.Subject, src_lang, dest_lang
                    )
                    translated_body = self.translation_service.translate_text(
                        message.Body, src_lang, dest_lang
                    ) if message.Body else ""
                    
                    # Create new message
                    new_message = outlook.CreateItem(0)
                    new_message.Subject = "Translated: " + translated_subject
                    new_message.Body = translated_body
                    new_message.To = namespace.CurrentUser.Address
                    
                    # Send message
                    new_message.Send()
                    count += 1
                    logger.info(f"Translated and sent email {count}: {translated_subject[:50]}...")
                
                except Exception as e:
                    logger.warning(f"Error translating email {count + 1}: {e}")
                    continue
            
            logger.info(f"Successfully translated and sent {count} emails")
            return count
        
        except Exception as e:
            error_msg = f"Error translating emails: {e}"
            logger.error(error_msg)
            raise EmailError(error_msg, original_error=e) from e

