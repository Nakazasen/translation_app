import pytest
from unittest.mock import MagicMock
from translation_app.core.email_handler import EmailHandler
from translation_app.utils.error_handler import EmailError


class FakeTranslationService:
    def translate_text(self, text, src_lang, dest_lang):
        return f"[{text}]"


def test_email_handler_coinitialize_called(monkeypatch):
    import pythoncom
    import win32com.client

    coinit_called = 0
    couninit_called = 0

    def fake_coinitialize():
        nonlocal coinit_called
        coinit_called += 1

    def fake_couninitialize():
        nonlocal couninit_called
        couninit_called += 1

    monkeypatch.setattr(pythoncom, "CoInitialize", fake_coinitialize)
    monkeypatch.setattr(pythoncom, "CoUninitialize", fake_couninitialize)

    # Mock win32com client dispatch to raise an error to check the finally block
    def raise_dispatch_error(name):
        raise RuntimeError("dispatch error")

    monkeypatch.setattr(win32com.client, "Dispatch", raise_dispatch_error)

    service = FakeTranslationService()
    handler = EmailHandler(service)

    with pytest.raises(EmailError):
        handler.translate_latest_unread_emails("Inbox", "auto", "vi")

    assert coinit_called == 1
    assert couninit_called == 1


def test_email_handler_com_error_wrapped(monkeypatch):
    import pythoncom
    import win32com.client

    monkeypatch.setattr(pythoncom, "CoInitialize", lambda: None)
    monkeypatch.setattr(pythoncom, "CoUninitialize", lambda: None)

    # Simulate a win32com.client.Dispatch COM error
    def raise_com_error(name):
        raise pythoncom.com_error(-2147221008, "CoInitialize has not been called.", None, None)

    monkeypatch.setattr(win32com.client, "Dispatch", raise_com_error)

    service = FakeTranslationService()
    handler = EmailHandler(service)

    with pytest.raises(EmailError) as excinfo:
        handler.translate_latest_unread_emails("Inbox", "auto", "vi")

    assert "Error translating emails" in str(excinfo.value)
    assert "CoInitialize has not been called" in str(excinfo.value)


def test_email_handler_inbox_alias_uses_default_folder():
    service = FakeTranslationService()
    handler = EmailHandler(service)
    default_inbox = MagicMock()
    namespace = MagicMock()
    namespace.GetDefaultFolder.return_value = default_inbox

    assert handler._resolve_folder(namespace, "Inbox") is default_inbox
    assert handler._resolve_folder(namespace, "Hộp thư") is default_inbox
    assert namespace.GetDefaultFolder.call_count == 2
    namespace.GetDefaultFolder.assert_called_with(6)


def test_email_handler_custom_folder_lookup_is_normalized():
    service = FakeTranslationService()
    handler = EmailHandler(service)
    target_folder = MagicMock()
    target_folder.Name = "  Khách Hàng  "
    target_folder.Folders = []

    root_folder = MagicMock()
    root_folder.Folders = [target_folder]
    namespace = MagicMock()
    namespace.Folders.Item.return_value = root_folder

    assert handler._resolve_folder(namespace, "khách   hàng") is target_folder
    namespace.GetDefaultFolder.assert_not_called()


def test_email_status_updates_batch_progress(monkeypatch):
    import pythoncom
    import win32com.client

    monkeypatch.setattr(pythoncom, "CoInitialize", lambda: None)
    monkeypatch.setattr(pythoncom, "CoUninitialize", lambda: None)

    # Mock Outlook objects
    outlook_mock = MagicMock()
    namespace_mock = MagicMock()
    folder_mock = MagicMock()
    item_mock = MagicMock()

    item_mock.Subject = "Test Unread Email"
    item_mock.Body = "Hello world"

    # Mock items list behavior
    items_mock = MagicMock()
    items_mock.__iter__.return_value = [item_mock]
    folder_mock.Items.Restrict.return_value = items_mock

    namespace_mock.GetDefaultFolder.return_value = folder_mock
    namespace_mock.CurrentUser.Address = "test@domain.com"
    outlook_mock.GetNamespace.return_value = namespace_mock

    # Mock CreateItem for sending
    new_msg_mock = MagicMock()
    outlook_mock.CreateItem.return_value = new_msg_mock

    monkeypatch.setattr(win32com.client, "Dispatch", lambda name: outlook_mock)

    service = FakeTranslationService()
    handler = EmailHandler(service)

    progress_states = []
    def callback(text):
        progress_states.append(text)

    success_count, errors = handler.translate_latest_unread_emails(
        "Inbox", "en", "vi", progress_callback=callback
    )

    assert success_count == 1
    assert len(errors) == 0
    assert any("Đang kết nối Outlook" in s for s in progress_states)
    assert any("Đang đọc email 1/1" in s for s in progress_states)
    assert any("Đang dịch email 1/1" in s for s in progress_states)
    assert new_msg_mock.Send.call_count == 1


def test_email_batch_errors_are_summarized(monkeypatch):
    import pythoncom
    import win32com.client

    monkeypatch.setattr(pythoncom, "CoInitialize", lambda: None)
    monkeypatch.setattr(pythoncom, "CoUninitialize", lambda: None)

    # Mock Outlook objects
    outlook_mock = MagicMock()
    namespace_mock = MagicMock()
    folder_mock = MagicMock()

    item_fail = MagicMock()
    item_fail.Subject = "Fail Subject"
    item_fail.Body = "Fail Body"

    # Force translate to raise exception for this specific item
    class ErroringTranslationService:
        def translate_text(self, text, src_lang, dest_lang):
            if "Fail" in text:
                raise RuntimeError("AI translation service error")
            return f"[{text}]"

    items_mock = MagicMock()
    items_mock.__iter__.return_value = [item_fail]
    folder_mock.Items.Restrict.return_value = items_mock

    namespace_mock.GetDefaultFolder.return_value = folder_mock
    namespace_mock.CurrentUser.Address = "test@domain.com"
    outlook_mock.GetNamespace.return_value = namespace_mock

    monkeypatch.setattr(win32com.client, "Dispatch", lambda name: outlook_mock)

    service = ErroringTranslationService()
    handler = EmailHandler(service)

    success_count, errors = handler.translate_latest_unread_emails(
        "Inbox", "en", "vi"
    )

    assert success_count == 0
    assert len(errors) == 1
    assert "Lỗi dịch email 1" in errors[0]
    assert "AI translation service error" in errors[0]
