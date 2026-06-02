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

    def _normalize_folder_name(self, folder_name: str) -> str:
        """
        Normalize an Outlook folder name for tolerant matching.

        Args:
            folder_name: Folder display name or alias.

        Returns:
            Normalized folder name.
        """
        return " ".join(folder_name.strip().casefold().split())

    def _get_folder_by_name(self, parent_folder, folder_name: str):
        """
        Recursively find folder by name.

        Args:
            parent_folder: Parent folder to search in.
            folder_name: Name of folder to find.

        Returns:
            Folder object if found, None otherwise.
        """
        target_name = self._normalize_folder_name(folder_name)
        for folder in parent_folder.Folders:
            if self._normalize_folder_name(folder.Name) == target_name:
                return folder
            subfolder = self._get_folder_by_name(folder, folder_name)
            if subfolder:
                return subfolder
        return None

    def _resolve_folder(self, namespace, folder_name: str):
        """
        Resolve an Outlook folder from a user-facing name or common alias.

        Args:
            namespace: Outlook MAPI namespace.
            folder_name: Folder display name or alias.

        Returns:
            Outlook folder object if found, None otherwise.
        """
        normalized_name = self._normalize_folder_name(folder_name)
        inbox_aliases = {"inbox", "hop thu", "hộp thư"}
        if normalized_name in inbox_aliases:
            try:
                return namespace.GetDefaultFolder(6)  # olFolderInbox
            except Exception as e:
                logger.warning(f"Không thể mở Inbox mặc định của Outlook: {e}")

        root_folder = namespace.Folders.Item(1)
        return self._get_folder_by_name(root_folder, folder_name)

    def translate_latest_unread_emails(
        self,
        folder_name: str,
        src_lang: str,
        dest_lang: str,
        max_emails: Optional[int] = None,
        progress_callback = None
    ) -> tuple[int, list[str]]:
        """
        Translate latest unread emails from specified folder

        Args:
            folder_name: Name of Outlook folder
            src_lang: Source language code
            dest_lang: Destination language code
            max_emails: Maximum number of emails to translate (defaults to config.max_emails_to_translate)
            progress_callback: Optional callable for step status updates

        Returns:
            Tuple of (success_count, list of error messages)

        Raises:
            EmailError: If processing fails
        """
        if max_emails is None:
            max_emails = config.max_emails_to_translate

        import pythoncom
        pythoncom.CoInitialize()
        try:
            if progress_callback:
                progress_callback("Đang kết nối Outlook...")
            logger.info(f"Connecting to Outlook...")
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            namespace.Logon("", "", False, True)

            if not folder_name or not folder_name.strip():
                raise EmailError("Folder name cannot be empty")

            folder_name = folder_name.strip()
            folder = self._resolve_folder(namespace, folder_name)

            if not folder:
                raise EmailError(f"Folder not found: {folder_name}")

            # Get unread items
            if progress_callback:
                progress_callback("Đang đọc danh sách email...")
            unread_items = folder.Items.Restrict("[UnRead] = True")
            unread_items.Sort("[ReceivedTime]", True)

            # Retrieve items to process safely
            unread_list = []
            for item in unread_items:
                unread_list.append(item)
                if len(unread_list) >= max_emails:
                    break

            total_emails = len(unread_list)
            if total_emails == 0:
                logger.info("No unread emails found")
                return 0, []

            if progress_callback:
                progress_callback(f"Đang chuẩn bị dịch {total_emails} email...")

            success_count = 0
            errors = []
            for idx, message in enumerate(unread_list):
                try:
                    subject = message.Subject

                    if progress_callback:
                        progress_callback(f"Đang đọc email {idx + 1}/{total_emails}...")

                    body = message.Body if message.Body else ""

                    if progress_callback:
                        progress_callback(f"Đang dịch email {idx + 1}/{total_emails}: {subject[:30]}...")

                    # Translate subject and body
                    translated_subject = self.translation_service.translate_text(
                        subject, src_lang, dest_lang
                    )
                    translated_body = self.translation_service.translate_text(
                        body, src_lang, dest_lang
                    ) if body else ""

                    if progress_callback:
                        progress_callback(f"Đang gửi email đã dịch {idx + 1}/{total_emails}...")

                    # Create new message
                    new_message = outlook.CreateItem(0)
                    new_message.Subject = "Translated: " + translated_subject
                    new_message.Body = translated_body
                    new_message.To = namespace.CurrentUser.Address

                    # Send message
                    new_message.Send()
                    success_count += 1
                    logger.info(f"Translated and sent email {success_count}: {translated_subject[:50]}...")

                except Exception as e:
                    err_msg = f"Lỗi dịch email {idx + 1}: {str(e)}"
                    logger.warning(err_msg)
                    errors.append(err_msg)
                    continue

            logger.info(f"Successfully translated and sent {success_count} emails")
            return success_count, errors

        except Exception as e:
            error_msg = f"Error translating emails: {e}"
            logger.error(error_msg)
            raise EmailError(error_msg, original_error=e) from e
        finally:
            pythoncom.CoUninitialize()
