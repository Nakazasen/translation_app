import os
import gc
import json
import pytest
import tempfile
import time
from pathlib import Path

import translation_app.core.translation_memory
from translation_app.core.translation_memory import get_tm_manager
from translation_app.core.translation_job import TranslationJobManager
from translation_app.core.ai_service import get_ai_service
from translation_app.core.file_translation_control import FileTranslationInterrupted
from translation_app.core.provider_router import ProviderRouter
from translation_app.core.providers import OpenAICompatibleProvider


class _ParagraphWorkPromptHarness:
    """Minimal harness for paragraph work communication prompt helpers."""

    from translation_app.ui.main_window import MainWindow

    paragraph_style_options = [
        "Mặc định",
        "Thân mật / xuồng xã",
        "Tự nhiên / lịch sự nhẹ",
        "Chuyên nghiệp",
        "Trang trọng với cấp trên",
        "Rất trang trọng / executive",
        "Email công việc",
    ]
    paragraph_situation_options = [
        "Không chỉ định",
        "Chat với bạn bè/đồng nghiệp thân",
        "Chat với đồng nghiệp",
        "Chat với sếp trực tiếp",
        "Chat với sếp lớn/giám đốc",
        "Gửi nhiều phòng ban",
        "Gửi khách hàng/đối tác",
        "Báo cáo tiến độ",
        "Nhờ hỗ trợ/phối hợp",
        "Xin lỗi/giải trình",
        "Từ chối khéo",
    ]
    paragraph_goal_options = [
        "Dịch đúng nghĩa",
        "Dịch + viết tự nhiên",
        "Viết lại lịch sự hơn",
        "Viết ngắn gọn hơn",
        "Viết trang trọng hơn",
        "Làm mềm câu",
        "Tạo 3 phiên bản: ngắn gọn / lịch sự / trang trọng",
    ]
    _apply_paragraph_work_preset = MainWindow._apply_paragraph_work_preset
    _get_paragraph_work_options = MainWindow._get_paragraph_work_options
    _has_paragraph_work_options = MainWindow._has_paragraph_work_options
    _build_paragraph_work_prompt = MainWindow._build_paragraph_work_prompt

    def __init__(self, style=None, situation=None, goal=None, context=""):
        import tkinter as tk

        self._tk_root = tk.Tcl()
        self.paragraph_output_style = tk.StringVar(
            master=self._tk_root,
            value=style or self.paragraph_style_options[0],
        )
        self.paragraph_communication_situation = tk.StringVar(
            master=self._tk_root,
            value=situation or self.paragraph_situation_options[0],
        )
        self.paragraph_processing_goal = tk.StringVar(
            master=self._tk_root,
            value=goal or self.paragraph_goal_options[0],
        )
        self.entry_paragraph_context = self._ContextEntry(context)

    class _ContextEntry:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value


def test_text_tab_work_style_controls_exist():
    """Phase 5M work style control option lists should be available."""
    harness = _ParagraphWorkPromptHarness()

    assert "Mặc định" in harness.paragraph_style_options
    assert "Email công việc" in harness.paragraph_style_options
    assert "Không chỉ định" in harness.paragraph_situation_options
    assert "Chat với sếp trực tiếp" in harness.paragraph_situation_options
    assert "Dịch đúng nghĩa" in harness.paragraph_goal_options
    assert "Tạo 3 phiên bản: ngắn gọn / lịch sự / trang trọng" in harness.paragraph_goal_options


def test_text_tab_default_prompt_preserves_legacy_behavior():
    """Default style options must not alter translation input."""
    harness = _ParagraphWorkPromptHarness()

    assert harness._build_paragraph_work_prompt("Please review this.") == "Please review this."


def test_paragraph_work_prompt_keeps_legacy_default_input():
    """Backward-compatible alias for default prompt behavior."""
    test_text_tab_default_prompt_preserves_legacy_behavior()


def test_text_tab_formal_boss_style_prompt():
    """Formal boss chat choices should add humility and no-command guidance."""
    harness = _ParagraphWorkPromptHarness(
        style="Trang trọng với cấp trên",
        situation="Chat với sếp trực tiếp",
        goal="Viết lại lịch sự hơn",
        context="báo tiến độ cho quản lý",
    )

    prompt = harness._build_paragraph_work_prompt("I need more time.")

    assert "Trang trọng với cấp trên" in prompt
    assert "Chat với sếp trực tiếp" in prompt
    assert "Viết lại lịch sự hơn" in prompt
    assert "khiêm tốn" in prompt
    assert "tránh ra lệnh" in prompt


def test_text_tab_business_email_style_prompt():
    """Business email prompt must allow email format but forbid invented recipients."""
    harness = _ParagraphWorkPromptHarness(style="Email công việc")

    prompt = harness._build_paragraph_work_prompt("Please send the file.")

    assert "Email công việc" in prompt
    assert "format email" in prompt
    assert "không bịa tên người nhận" in prompt


def test_text_tab_three_versions_prompt():
    """Three-version goal should request exactly the required labels."""
    harness = _ParagraphWorkPromptHarness(
        goal="Tạo 3 phiên bản: ngắn gọn / lịch sự / trang trọng",
    )

    prompt = harness._build_paragraph_work_prompt("Can you help me?")

    assert "Tạo 3 phiên bản" in prompt
    assert "1. Ngắn gọn" in prompt
    assert "2. Lịch sự" in prompt
    assert "3. Trang trọng" in prompt


def test_text_tab_quick_preset_buttons_update_controls():
    """Quick preset command should update the three work communication controls."""
    harness = _ParagraphWorkPromptHarness()

    harness._apply_paragraph_work_preset(
        "Chuyên nghiệp",
        "Từ chối khéo",
        "Làm mềm câu",
    )

    assert harness.paragraph_output_style.get() == "Chuyên nghiệp"
    assert harness.paragraph_communication_situation.get() == "Từ chối khéo"
    assert harness.paragraph_processing_goal.get() == "Làm mềm câu"


def test_paragraph_work_prompt_adds_safe_work_rewrite_instructions():
    """Non-default style options should add work rewrite instructions safely."""
    harness = _ParagraphWorkPromptHarness(
        style="Email công việc",
        situation="Gửi nhiều phòng ban",
        goal="Dịch + viết tự nhiên",
        context="gửi cho quản lý",
    )

    prompt = harness._build_paragraph_work_prompt("Need the report today.")

    assert "trợ lý biên tập văn bản công việc" in prompt
    assert "Không tự thêm thông tin" in prompt
    assert "Email công việc" in prompt
    assert "Gửi nhiều phòng ban" in prompt
    assert "Dịch + viết tự nhiên" in prompt
    assert "gửi cho quản lý" in prompt
    assert "Need the report today." in prompt


def test_text_tab_work_prompt_security_regression():
    """Prompt template must not contain credential headers or token labels."""
    harness = _ParagraphWorkPromptHarness(style="Email công việc")

    prompt = harness._build_paragraph_work_prompt("Short user text")

    assert "API key" not in prompt
    assert "Authorization" not in prompt
    assert "Bearer" not in prompt


class _ImageUxHarness:
    """Minimal harness for Phase 5N-A image UX helpers."""

    from translation_app.ui.main_window import MainWindow

    IMAGE_EMPTY_OCR_TEXT = MainWindow.IMAGE_EMPTY_OCR_TEXT
    _get_editable_image_ocr_text = MainWindow._get_editable_image_ocr_text
    _set_image_ocr_text = MainWindow._set_image_ocr_text
    _copy_text_to_clipboard = MainWindow._copy_text_to_clipboard
    _save_text_with_dialog = MainWindow._save_text_with_dialog
    copy_image_ocr_text = MainWindow.copy_image_ocr_text
    copy_translated_image_text = MainWindow.copy_translated_image_text
    save_image_ocr_text = MainWindow.save_image_ocr_text
    save_translated_image_text = MainWindow.save_translated_image_text
    _get_translated_image_output_text = MainWindow._get_translated_image_output_text
    _set_image_status = MainWindow._set_image_status

    def __init__(self, ocr_text="", translated_text=""):
        self.last_ocr_text = ""
        self.clipboard_image = None
        self.entry_image_path = self._Entry("")
        self.text_image_ocr = self._Textbox(ocr_text or self.IMAGE_EMPTY_OCR_TEXT)
        self.text_output = self._Textbox(translated_text)
        self.label_image_status = self._Label()
        self.clipboard = ""
        self.updated = False

    class _Textbox:
        def __init__(self, value=""):
            self.value = value

        def get(self, *_args):
            return self.value

        def delete(self, *_args):
            self.value = ""

        def insert(self, _index, text):
            self.value += text

    class _Entry:
        def __init__(self, value=""):
            self.value = value

        def get(self):
            return self.value

    class _Label:
        def __init__(self):
            self.text = ""

        def configure(self, **kwargs):
            if "text" in kwargs:
                self.text = kwargs["text"]

    def clipboard_clear(self):
        self.clipboard = ""

    def clipboard_append(self, text):
        self.clipboard = text

    def update(self):
        self.updated = True


def test_email_image_ux_constants_are_safe_and_helpful():
    """Phase 5N-A UI copy should guide users without exposing secrets."""
    from translation_app.ui.main_window import MainWindow

    combined = "\n".join([
        MainWindow.EMAIL_UX_GUIDE_TEXT,
        MainWindow.EMAIL_SAFETY_TEXT,
        MainWindow.EMAIL_READY_STATUS,
        MainWindow.IMAGE_UX_GUIDE_TEXT,
        MainWindow.IMAGE_READY_STATUS,
        MainWindow.IMAGE_EMPTY_OCR_TEXT,
    ])

    assert "Outlook" in MainWindow.EMAIL_UX_GUIDE_TEXT
    assert "không tự sửa email gốc" in MainWindow.EMAIL_SAFETY_TEXT
    assert "clipboard" in MainWindow.IMAGE_UX_GUIDE_TEXT
    assert "chỉnh" in MainWindow.IMAGE_EMPTY_OCR_TEXT
    assert "API key" not in combined
    assert "Authorization" not in combined
    assert "Bearer" not in combined


def test_image_ocr_textbox_prefers_user_edited_text():
    """Editable OCR text should be used before fallback OCR cache."""
    harness = _ImageUxHarness("OCR đã chỉnh")
    harness.last_ocr_text = "OCR cũ"

    assert harness._get_editable_image_ocr_text() == "OCR đã chỉnh"

    harness._set_image_ocr_text("OCR mới")
    assert harness.text_image_ocr.get("1.0", "end") == "OCR mới"


def test_image_ocr_textbox_falls_back_to_last_ocr_when_placeholder():
    """Placeholder text must not be treated as real OCR content."""
    harness = _ImageUxHarness()
    harness.last_ocr_text = "OCR fallback"

    assert harness._get_editable_image_ocr_text() == "OCR fallback"


def test_image_copy_helpers_copy_ocr_and_translation(monkeypatch):
    """Copy buttons should copy OCR/translation and update friendly status."""
    harness = _ImageUxHarness("OCR text", "Translated text")
    monkeypatch.setattr("translation_app.ui.main_window.messagebox.showwarning", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected warning")))

    harness.copy_image_ocr_text()
    assert harness.clipboard == "OCR text"
    assert "Đã copy nội dung OCR" in harness.label_image_status.text

    harness.copy_translated_image_text()
    assert harness.clipboard == "Translated text"
    assert "Đã copy bản dịch" in harness.label_image_status.text


def test_image_copy_empty_text_warns(monkeypatch):
    """Empty copy action should warn instead of copying blank text."""
    harness = _ImageUxHarness("", "")
    warnings = []
    monkeypatch.setattr("translation_app.ui.main_window.messagebox.showwarning", lambda title, message: warnings.append((title, message)))

    assert harness._copy_text_to_clipboard("", "Không có nội dung OCR để copy.") is False

    assert warnings == [("Cảnh báo", "Không có nội dung OCR để copy.")]
    assert harness.clipboard == ""


def test_save_image_ocr_text_uses_dialog_and_status(monkeypatch, tmp_path):
    """OCR save helper should write UTF-8 text through a save dialog."""
    harness = _ImageUxHarness("OCR lưu")
    output_path = tmp_path / "ocr.txt"
    infos = []
    monkeypatch.setattr("translation_app.ui.main_window.filedialog.asksaveasfilename", lambda **kwargs: str(output_path))
    monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda title, message: infos.append((title, message)))
    monkeypatch.setattr("translation_app.ui.main_window.messagebox.showwarning", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected warning")))
    monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

    harness.save_image_ocr_text()

    assert output_path.read_text(encoding="utf-8") == "OCR lưu"
    assert "Đã lưu nội dung" in harness.label_image_status.text
    assert infos


def test_save_translated_image_text_uses_translated_filename(monkeypatch, tmp_path):
    """Translated image save should create a sibling _translated text file for file input."""
    harness = _ImageUxHarness(translated_text="Bản dịch")
    image_path = tmp_path / "image.png"
    image_path.write_text("not-used", encoding="utf-8")
    harness.entry_image_path = harness._Entry(str(image_path))
    monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda *args, **kwargs: None)
    monkeypatch.setattr("translation_app.ui.main_window.messagebox.showwarning", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected warning")))
    monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

    harness.save_translated_image_text()

    outputs = list(tmp_path.glob("image_translated_*.txt"))
    assert len(outputs) == 1
    assert outputs[0].read_text(encoding="utf-8") == "Bản dịch"
    assert "Đã lưu bản dịch" in harness.label_image_status.text


def test_ui_imports_without_error():
    """Verify that UI modules import without throwing any SyntaxError."""
    try:
        from translation_app.ui.main_window import MainWindow
        from translation_app.ui.ai_settings_dialog import AISettingsDialog
        assert True
    except Exception as e:
        pytest.fail(f"UI imports failed: {e}")


def test_tm_search_api_returns_preview():
    """Verify new search/list/delete TM segments APIs in core."""
    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    
    try:
        tm = get_tm_manager(db_path)
        
        # Save a segment
        tm.save_segment("en", "vi", "Hello World", "Xin chào thế giới", provider="test", model="model-a")
        
        # Search segment
        results = tm.search_segments(query="Hello", source_lang="en", target_lang="vi")
        assert len(results) == 1
        assert results[0]["source_text"] == "Hello World"
        assert results[0]["translated_text"] == "Xin chào thế giới"
        
        # Delete segment
        seg_id = results[0]["id"]
        assert tm.delete_segment(seg_id) is True
        
        # Search again
        results_after = tm.search_segments(query="Hello", source_lang="en", target_lang="vi")
        assert len(results_after) == 0
        
    finally:
        # Clean up global reference to release file locks on Windows
        translation_app.core.translation_memory._tm_manager = None
        gc.collect()
        
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_job_list_api_returns_summary():
    """Verify jobs listing and checkpoints retrieval."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        job_manager = TranslationJobManager(Path(tmp_dir))
        
        # Create a job
        job_data = job_manager.create_job(
            input_files=["test.xlsx"],
            output_dir=tmp_dir,
            source_lang="en",
            target_lang="vi",
            strategy="waterfall",
            job_type="excel"
        )
        job_id = job_data["job_id"]
        
        # List jobs
        jobs = job_manager.list_jobs()
        assert len(jobs) >= 1
        assert jobs[0]["job_id"] == job_id
        
        # Get summary
        summary = job_manager.get_job_summary(job_id)
        assert summary["job"]["job_id"] == job_id
        assert summary["progress"]["percent"] == 0.0


def test_glossary_validation_rejects_empty_terms():
    """Verify that glossary core logic validates and rejects empty terms."""
    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    
    try:
        tm = get_tm_manager(db_path)
        
        # Reject empty terms
        assert tm.add_glossary_term("", "Táo", "en", "vi") is None
        assert tm.add_glossary_term("Apple", "", "en", "vi") is None
        
    finally:
        # Clean up global reference to release file locks on Windows
        translation_app.core.translation_memory._tm_manager = None
        gc.collect()
        
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_provider_router_health_snapshot_ui_redacts_keys():
    """Verify that health snapshot never contains raw api keys."""
    router = ProviderRouter(cooldown_seconds=60, max_retries=1)
    secret_key = "FAKE_OPENAI_API_KEY_FOR_TEST_8"
    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:9090/v1",
        api_key=secret_key,
        model="gpt-test",
        provider_name="openai_compatible",
    )
    router.register_provider(provider)
    
    # Trigger a failure to get state
    router.mark_failure("openai_compatible", "gpt-test", "429 quota")
    
    snapshot = router.get_health_snapshot()
    snapshot_str = str(snapshot)
    
    assert secret_key not in snapshot_str
    assert "api_key" not in snapshot_str


def test_router_error_text_is_sanitized_and_truncated():
    """Verify UI helper redacts sensitive router error text before rendering."""
    from translation_app.ui.main_window import MainWindow

    raw_error = (
        "Authorization: Bearer sk-secret-123456789 "
        "FAKE_GOOGLE_API_KEY_FOR_TEST_5 "
        "prompt source_text " + ("x" * 120)
    )

    sanitized = MainWindow._sanitize_router_error_text(None, raw_error)

    assert sanitized == "[REDACTED_SENSITIVE_ERROR]"


def test_top_level_tabs_are_vietnamese():
    """Verify that notebook tabs are only standard Vietnamese and do not contain English terms."""
    from translation_app.ui.main_window import MainWindow
    root = MainWindow()
    root.withdraw()
    try:
        tabs = [root.notebook.tab(i, "text") for i in range(root.notebook.index("end"))]
        
        # Verify Vietnamese tabs
        assert "Dịch file" in tabs
        assert "Dịch văn bản" in tabs
        assert "Dịch email" in tabs
        assert "Dịch ảnh" in tabs
        assert "Cấu hình AI" in tabs
        assert "Công việc" in tabs
        assert "Thuật ngữ" in tabs
        assert "Bộ nhớ dịch" in tabs
        
        # Verify banned/English top-level tabs are absent
        for banned in ("Jobs", "Glossary", "Translation Memory", "Provider Router"):
            assert banned not in tabs
    finally:
        root.destroy()


def test_ai_settings_contains_provider_profiles_without_raw_keys():
    """Verify UI public views redact raw keys."""
    ai_service = get_ai_service()
    config_mgr = ai_service.config_manager
    
    # Set a fake key in deepseek
    providers = config_mgr.providers_config
    secret_key = "FAKE_OPENAI_API_KEY_FOR_TEST_9"
    providers["deepseek"]["api_keys"] = [secret_key]
    providers["deepseek"]["enabled"] = True
    config_mgr.providers_config = providers
    
    # Fetch public profiles
    pub_data = config_mgr.get_provider_profiles_public()
    deepseek_pub = pub_data.get("deepseek", {})
    
    # Redacted values should not contain secret_key
    assert secret_key not in str(deepseek_pub)
    assert len(deepseek_pub.get("api_keys", [])) == 1
    assert deepseek_pub["api_keys"][0] == "[REDACTED_API_KEY]"


def test_provider_api_key_add_remove_does_not_log_or_display_raw_key():
    """Verify adding/removing provider keys operates without raw key exposure."""
    ai_service = get_ai_service()
    config_mgr = ai_service.config_manager
    
    secret_key = "FAKE_OPENAI_API_KEY_FOR_TEST_10"
    provider_name = "chatanywhere"
    
    # Add key
    success = config_mgr.add_provider_api_key(provider_name, secret_key)
    assert success is True
    
    pub_data = config_mgr.get_provider_profiles_public()
    assert secret_key not in str(pub_data)
    
    # Remove key
    keys_pool = config_mgr.providers_config[provider_name].get("api_keys", [])
    try:
        key_idx = keys_pool.index(secret_key)
        assert config_mgr.remove_provider_api_key(provider_name, key_idx) is True
    except ValueError:
        pass


def test_gemini_legacy_key_is_preserved_in_provider_settings():
    """Verify that Gemini legacy API key and api_keys pool sync correctly."""
    ai_service = get_ai_service()
    config_mgr = ai_service.config_manager
    
    legacy_key = config_mgr.api_key
    if legacy_key:
        pub_data = config_mgr.get_provider_profiles_public()
        gemini_pub = pub_data.get("gemini", {})
        assert gemini_pub["enabled"] is True


def test_non_tech_safe_labels_present():
    """Verify non-tech-friendly UI elements are built in Cấu hình AI tab."""
    from translation_app.ui.main_window import MainWindow
    root = MainWindow()
    root.withdraw()
    try:
        # Traverse the widgets inside the AI configuration tab to look for Vietnamese safe labels
        widgets_text = []
        def traverse(widget):
            for child in widget.winfo_children():
                # Extract text if available
                if hasattr(child, "cget"):
                    try:
                        text = child.cget("text")
                        if text:
                            widgets_text.append(text)
                    except:
                        pass
                traverse(child)
                
        traverse(root.tab_ai)
        full_text = " ".join(widgets_text)
        
        assert "Cấu hình nhanh" in full_text
        assert "Các nhà cung cấp AI" in full_text or "nhà cung cấp" in full_text
        assert "Bật bộ định tuyến AI" in full_text or "Smart Router" in full_text
    finally:
        root.destroy()


def test_format_support_does_not_overclaim_pdf():
    """Verify PDF support info label warns about layout audit requirement."""
    from translation_app.ui.main_window import MainWindow
    root = MainWindow()
    root.withdraw()
    try:
        widgets_text = []
        def traverse(widget):
            for child in widget.winfo_children():
                if hasattr(child, "cget"):
                    try:
                        text = child.cget("text")
                        if text:
                            widgets_text.append(text)
                    except:
                        pass
                traverse(child)
                
        traverse(root.tab_file)
        full_text = " ".join(widgets_text)
        
        # Search for layout audit warning
        assert "audit layout" in full_text or "Cần audit layout" in full_text
        # Banned claims
        assert "giữ nguyên layout PDF" not in full_text
    finally:
        root.destroy()


def test_no_mojibake_in_ui_after_ux_refactor():
    """Scan code files for Shift_JIS Mojibake patterns."""
    from translation_app.core.encoding_utils import detect_mojibake, MOJIBAKE_PATTERNS
    from translation_app.ui.main_window import MainWindow
    
    # We can inspect static string literals in ui/main_window.py
    main_window_path = Path(__file__).parent.parent / "ui" / "main_window.py"
    with open(main_window_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Check for known Mojibake patterns
    has_mojibake = detect_mojibake(content)
    matched = []
    if has_mojibake:
        for pattern in MOJIBAKE_PATTERNS:
            if pattern in content:
                matched.append(pattern)
    assert not has_mojibake, f"Found Mojibake pattern(s): {matched}"


class _ImmediateThread:
    def __init__(self, target=None, daemon=None, *args, **kwargs):
        self._target = target

    def start(self):
        if self._target:
            self._target()


class _DormantThread:
    def __init__(self, target=None, daemon=None, *args, **kwargs):
        self._target = target

    def start(self):
        return None


def _prepare_translate_file_ui(monkeypatch, tmp_path, suffix):
    from translation_app.ui.main_window import MainWindow

    input_path = tmp_path / f"sample{suffix}"
    input_path.write_bytes(b"stub")

    monkeypatch.setattr("translation_app.ui.main_window.FileValidator.validate_file", lambda *_: None)
    monkeypatch.setattr("translation_app.ui.main_window.LanguageValidator.validate_language_pair", lambda *_: None)
    monkeypatch.setattr("translation_app.ui.main_window.threading.Thread", _ImmediateThread)

    root = MainWindow()
    root.withdraw()
    root.after = lambda delay, callback=None, *args: callback(*args) if callback else None
    root._show_pdf_ai_guide_and_wait = lambda: False
    root.entry_file_path.delete(0, "end")
    root.entry_file_path.insert(0, str(input_path))
    return root, input_path


def _set_fake_pdf_report(root, input_name="input.pdf", output_name="output.pdf"):
    root.pdf_handler.last_pdf_qa_report = {
        "mode": "experimental_pdf",
        "page_count": 1,
        "translated_units": 1,
        "translated_blocks": 2,
        "skipped_units": 0,
        "overflow_units": 0,
        "warning_count": 1,
        "warnings_by_type": {"font_shrunk": 1, "html_preview": "<script>alert(1)</script>"},
        "protected_regions_by_kind": {"formula": 1},
        "rejected": False,
        "input_file": input_name,
        "output_file": output_name,
    }
    root.last_pdf_report_input_file = str(Path("C:/sensitive") / input_name)
    root.last_pdf_report_output_file = str(Path("C:/sensitive") / output_name)
    root._update_pdf_report_export_state()


def test_pdf_experimental_ui_default_off(monkeypatch, tmp_path):
    root, input_path = _prepare_translate_file_ui(monkeypatch, tmp_path, ".pdf")
    calls = []
    infos = []
    try:
        assert root.use_experimental_pdf_output.get() is False

        monkeypatch.setattr(
            root.pdf_handler,
            "translate",
            lambda file_path, output_file, src_lang, dest_lang: calls.append(("stable", output_file)),
        )
        monkeypatch.setattr(
            root.pdf_handler,
            "translate_to_pdf_experimental",
            lambda *args, **kwargs: calls.append(("experimental", args[1])),
        )
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda *args, **kwargs: infos.append(args))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

        root.translate_file()

        assert calls == [("stable", str(input_path.with_name(f"sample_translated_{time.strftime('%Y%m%d')}.docx")))]
        assert infos
    finally:
        root.destroy()


def test_translate_file_prevents_duplicate_submission(monkeypatch, tmp_path):
    root, _ = _prepare_translate_file_ui(monkeypatch, tmp_path, ".docx")
    try:
        monkeypatch.setattr("translation_app.ui.main_window.threading.Thread", _DormantThread)
        root.translate_file()

        assert root._file_translation_in_progress is True
        assert root.button_translate_file.cget("state") == "disabled"

        calls = []
        monkeypatch.setattr(root.word_handler, "translate", lambda *args, **kwargs: calls.append(args))
        root.translate_file()

        assert calls == []
    finally:
        root.destroy()


def test_translate_file_reenables_controls_after_success(monkeypatch, tmp_path):
    root, _ = _prepare_translate_file_ui(monkeypatch, tmp_path, ".docx")
    infos = []
    try:
        monkeypatch.setattr(root.word_handler, "translate", lambda *args, **kwargs: None)
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda *args, **kwargs: infos.append(args))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

        root.translate_file()

        assert infos
        assert root._file_translation_in_progress is False
        assert root.button_translate_file.cget("state") == "normal"
        assert root.button_pause_file.cget("state") == "disabled"
        assert root.button_cancel_file.cget("state") == "disabled"
        assert root.button_browse_file.cget("state") == "normal"
        assert root.entry_file_path.cget("state") == "normal"
        assert str(root.combobox_src_lang_file.cget("state")) == "readonly"
        assert str(root.combobox_dest_lang_file.cget("state")) == "readonly"
    finally:
        root.destroy()


def test_translate_file_supports_multiple_selected_files(monkeypatch, tmp_path):
    root, input_path = _prepare_translate_file_ui(monkeypatch, tmp_path, ".docx")
    second_input = tmp_path / "sample_two.docx"
    second_input.write_bytes(b"stub")
    calls = []
    infos = []
    try:
        root._set_selected_file_paths([str(input_path), str(second_input)])
        monkeypatch.setattr(
            root.word_handler,
            "translate",
            lambda file_path, output_file, src_lang, dest_lang: calls.append((file_path, output_file)),
        )
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda *args, **kwargs: infos.append(args))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

        root.translate_file()

        assert [Path(item[0]).name for item in calls] == ["sample.docx", "sample_two.docx"]
        assert all("_translated_" in item[1] for item in calls)
        assert infos
    finally:
        root.destroy()


def test_translate_file_cancel_keeps_partial_output_notice(monkeypatch, tmp_path):
    root, input_path = _prepare_translate_file_ui(monkeypatch, tmp_path, ".docx")
    warnings = []
    try:
        monkeypatch.setattr(
            root.word_handler,
            "translate",
            lambda file_path, output_file, src_lang, dest_lang: (_ for _ in ()).throw(
                FileTranslationInterrupted("cancelled", output_file=output_file, partial_saved=True)
            ),
        )
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showwarning", lambda *args, **kwargs: warnings.append(args))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda *args, **kwargs: None)
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

        root.translate_file()

        assert warnings
        assert str(input_path.with_name(f"sample_translated_{time.strftime('%Y%m%d')}.docx")) in warnings[0][1]
        assert "0/1 file" in warnings[0][1]
        assert root._file_translation_in_progress is False
    finally:
        root.destroy()


def test_translate_file_creates_visible_job_for_docx(monkeypatch, tmp_path):
    root, input_path = _prepare_translate_file_ui(monkeypatch, tmp_path, ".docx")
    manager = TranslationJobManager(tmp_path / "jobs")
    infos = []
    try:
        root.job_manager = manager
        monkeypatch.setattr(root.word_handler, "translate", lambda *args, **kwargs: None)
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda *args, **kwargs: infos.append(args))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

        root.translate_file()

        jobs = manager.list_jobs(limit=10)
        assert len(jobs) == 1
        assert jobs[0]["job_type"] == "word_docx"
        assert jobs[0]["status"] == "completed"
        assert root.jobs_tree.exists(jobs[0]["job_id"])
        assert root.jobs_tree.selection() == (jobs[0]["job_id"],)
        assert "Đã tải 1 job" in root.jobs_empty_label.cget("text")
        assert str(input_path) in root.job_detail_text.get("1.0", "end")
        assert infos
    finally:
        root.destroy()

def test_resume_selected_job_reloads_file_and_runs_translation(monkeypatch, tmp_path):
    root, input_path = _prepare_translate_file_ui(monkeypatch, tmp_path, ".docx")
    manager = TranslationJobManager(tmp_path / "jobs")
    calls = []
    try:
        root.job_manager = manager
        job = manager.create_job([str(input_path)], tmp_path, "en", "vi", "waterfall", job_type="word")
        manager.update_job_status(job["job_id"], "paused")
        root._refresh_jobs_list()
        root.jobs_tree.selection_set(job["job_id"])

        monkeypatch.setattr(
            root.word_handler,
            "translate",
            lambda file_path, output_file, src_lang, dest_lang: calls.append((file_path, output_file, src_lang, dest_lang)),
        )
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda *args, **kwargs: None)
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showwarning", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected warning")))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

        root._resume_selected_job()

        assert calls
        assert calls[0][0] == str(input_path)
        assert calls[0][2:] == ("en", "vi")
        checkpoints = (tmp_path / "jobs" / job["job_id"] / "checkpoints.jsonl").read_text(encoding="utf-8")
        assert "job_resumed" in checkpoints
        assert manager.load_job(job["job_id"])["status"] == "paused"
    finally:
        root.destroy()


def test_jobs_tab_shows_resumable_state_and_safe_cache_summary(monkeypatch, tmp_path):
    root, input_path = _prepare_translate_file_ui(monkeypatch, tmp_path, ".docx")
    manager = TranslationJobManager(tmp_path / "jobs")
    cache_payload = {
        "handler": "word_docx",
        "updated_at": "2026-05-31T10:00:00",
        "segments": {
            "unit-1": {"source_text": "secret source", "translated_text": "secret translation"},
            "unit-2": {"source_text": "hidden source", "translated_text": "hidden translation"},
        },
    }
    try:
        root.job_manager = manager
        job = manager.create_job([str(input_path)], tmp_path, "en", "vi", "waterfall", job_type="word")
        manager.update_job_status(job["job_id"], "paused")
        cache_path = tmp_path / "resume-cache.json"
        cache_path.write_text(json.dumps(cache_payload), encoding="utf-8")
        monkeypatch.setattr("translation_app.ui.main_window.get_cache_path", lambda *args: cache_path)

        root._refresh_jobs_list()
        root.jobs_tree.selection_set(job["job_id"])
        root._on_job_selected()

        detail = root.job_detail_text.get("1.0", "end")
        assert root.resume_job_button.cget("state") == "normal"
        assert "Trạng thái tiếp tục: Có thể tiếp tục" in detail
        assert "Cache đã lưu: 2 phân đoạn" in detail
        assert "word_docx" in detail
        assert "secret source" not in detail
        assert "secret translation" not in detail
    finally:
        root.destroy()


def test_translate_file_error_callback_does_not_raise_nameerror(monkeypatch, tmp_path):
    root, _ = _prepare_translate_file_ui(monkeypatch, tmp_path, ".docx")
    errors = []
    try:
        monkeypatch.setattr(
            root.word_handler,
            "translate",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda *args, **kwargs: None)
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda title, message: errors.append((title, message)))

        root.translate_file()

        assert errors
        assert "Dịch file" in errors[0][1]
        assert "NameError" not in errors[0][1]
        assert root._file_translation_in_progress is False
        assert root.button_translate_file.cget("state") == "normal"
    finally:
        root.destroy()


def test_pdf_experimental_ui_changes_output_extension_to_pdf(monkeypatch, tmp_path):
    root, input_path = _prepare_translate_file_ui(monkeypatch, tmp_path, ".pdf")
    calls = []
    try:
        root.use_experimental_pdf_output.set(True)
        monkeypatch.setattr(
            root.pdf_handler,
            "translate_to_pdf_experimental",
            lambda file_path, output_file, src_lang, dest_lang: calls.append(output_file),
        )
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda *args, **kwargs: None)
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

        root.translate_file()

        assert len(calls) == 1
        assert calls[0].endswith(".pdf")
        assert "_translated_" in calls[0]
    finally:
        root.destroy()


def test_pdf_experimental_ui_calls_experimental_method(monkeypatch, tmp_path):
    root, _ = _prepare_translate_file_ui(monkeypatch, tmp_path, ".pdf")
    calls = []
    try:
        root.use_experimental_pdf_output.set(True)
        monkeypatch.setattr(
            root.pdf_handler,
            "translate_to_pdf_experimental",
            lambda file_path, output_file, src_lang, dest_lang: calls.append((file_path, output_file, src_lang, dest_lang)),
        )
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda *args, **kwargs: None)
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

        root.translate_file()

        assert len(calls) == 1
        assert calls[0][1].endswith(".pdf")
    finally:
        root.destroy()


def test_pdf_experimental_ui_does_not_affect_non_pdf(monkeypatch, tmp_path):
    root, input_path = _prepare_translate_file_ui(monkeypatch, tmp_path, ".xlsx")
    calls = []
    try:
        root.use_experimental_pdf_output.set(True)
        monkeypatch.setattr(
            root.excel_handler,
            "translate",
            lambda file_path, output_file, src_lang, dest_lang: calls.append(output_file),
        )
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda *args, **kwargs: None)
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

        root.translate_file()

        assert calls == [str(input_path.with_name(f"sample_translated_{time.strftime('%Y%m%d')}.xlsx"))]
    finally:
        root.destroy()


def test_pdf_report_export_buttons_exist_or_helpers_present():
    from translation_app.ui.main_window import MainWindow

    root = MainWindow()
    root.withdraw()
    try:
        assert root.btn_export_pdf_report_json.cget("text") == "Xuất báo cáo JSON"
        assert root.btn_export_pdf_report_html.cget("text") == "Xuất báo cáo HTML"
        assert root.label_pdf_report_notice.cget("text") == root._get_pdf_report_export_notice()
        assert root.btn_export_pdf_report_json.cget("state") == "disabled"
        assert root.btn_export_pdf_report_html.cget("state") == "disabled"
    finally:
        root.destroy()


def test_export_pdf_report_json_requires_existing_report(monkeypatch):
    from translation_app.ui.main_window import MainWindow

    root = MainWindow()
    root.withdraw()
    warnings = []
    try:
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showwarning", lambda title, message: warnings.append((title, message)))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected info")))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

        result = root.export_pdf_report_json()

        assert result is None
        assert warnings == [("Cảnh báo", "Chưa có báo cáo PDF thử nghiệm. Hãy chạy dịch PDF thử nghiệm trước.")]
    finally:
        root.destroy()


def test_export_pdf_report_json_success(monkeypatch, tmp_path):
    from translation_app.ui.main_window import MainWindow

    root = MainWindow()
    root.withdraw()
    infos = []
    try:
        _set_fake_pdf_report(root)
        output_path = tmp_path / "pdf_regression_report.json"
        monkeypatch.setattr("translation_app.ui.main_window.filedialog.asksaveasfilename", lambda **kwargs: str(output_path))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda title, message: infos.append((title, message)))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showwarning", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected warning")))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

        result = root.export_pdf_report_json()

        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert result == str(output_path)
        assert output_path.exists()
        assert payload["qa_report"]["translated_units"] == 1
        assert payload["metadata"]["input_file"] == "input.pdf"
        assert "prompt" not in repr(payload)
        assert infos and "Đã xuất báo cáo PDF thử nghiệm dạng JSON" in infos[0][1]
    finally:
        root.destroy()


def test_export_pdf_report_html_success(monkeypatch, tmp_path):
    from translation_app.ui.main_window import MainWindow

    root = MainWindow()
    root.withdraw()
    infos = []
    try:
        _set_fake_pdf_report(root)
        output_path = tmp_path / "pdf_regression_report.html"
        monkeypatch.setattr("translation_app.ui.main_window.filedialog.asksaveasfilename", lambda **kwargs: str(output_path))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda title, message: infos.append((title, message)))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showwarning", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected warning")))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

        result = root.export_pdf_report_html()

        html = output_path.read_text(encoding="utf-8")
        assert result == str(output_path)
        assert output_path.exists()
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "<script>alert(1)</script>" not in html
        assert infos and "Đã xuất báo cáo PDF thử nghiệm dạng HTML" in infos[0][1]
    finally:
        root.destroy()


def test_export_pdf_report_cancel_is_safe(monkeypatch):
    from translation_app.ui.main_window import MainWindow

    root = MainWindow()
    root.withdraw()
    try:
        _set_fake_pdf_report(root)
        monkeypatch.setattr("translation_app.ui.main_window.filedialog.asksaveasfilename", lambda **kwargs: "")
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected info")))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showwarning", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected warning")))
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error")))

        result = root.export_pdf_report_html()

        assert result is None
    finally:
        root.destroy()


def test_pdf_report_ui_wording_safe():
    from translation_app.ui.main_window import MainWindow

    root = MainWindow()
    root.withdraw()
    try:
        widgets_text = []

        def traverse(widget):
            for child in widget.winfo_children():
                if hasattr(child, "cget"):
                    try:
                        text = child.cget("text")
                        if text:
                            widgets_text.append(text)
                    except Exception:
                        pass
                traverse(child)

        traverse(root.tab_file)
        full_text = " ".join(widgets_text)

        assert "Báo cáo PDF thử nghiệm" in full_text
        assert "Đây không phải chứng nhận giữ layout tuyệt đối" in full_text
        for banned in ("giữ nguyên PDF", "layout chính xác", "bảo toàn 100%", "enterprise", "tương đương Google"):
            assert banned not in full_text
    finally:
        root.destroy()


def test_pdf_experimental_ui_wording_is_safe():
    from translation_app.ui.main_window import MainWindow

    root = MainWindow()
    root.withdraw()
    try:
        widgets_text = []

        def traverse(widget):
            for child in widget.winfo_children():
                if hasattr(child, "cget"):
                    try:
                        text = child.cget("text")
                        if text:
                            widgets_text.append(text)
                    except Exception:
                        pass
                traverse(child)

        traverse(root.tab_file)
        full_text = " ".join(widgets_text)

        assert "thử nghiệm" in full_text
        assert "DOCX ổn định" in full_text
        assert "giữ nguyên PDF" not in full_text
        assert "layout chính xác" not in full_text
        assert "preserve layout tốt" not in full_text
    finally:
        root.destroy()


def test_pdf_experimental_ui_shows_supported_error(monkeypatch, tmp_path):
    from translation_app.utils.error_handler import FileProcessingError

    root, _ = _prepare_translate_file_ui(monkeypatch, tmp_path, ".pdf")
    errors = []
    try:
        root.use_experimental_pdf_output.set(True)
        monkeypatch.setattr(
            root.pdf_handler,
            "translate_to_pdf_experimental",
            lambda *args, **kwargs: (_ for _ in ()).throw(FileProcessingError("unsupported experimental pdf")),
        )
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showinfo", lambda *args, **kwargs: None)
        monkeypatch.setattr("translation_app.ui.main_window.messagebox.showerror", lambda title, message: errors.append((title, message)))

        root.translate_file()

        assert errors
        assert "PDF" in errors[0][1]
        assert "DOCX" in errors[0][1]
    finally:
        root.destroy()


def test_no_mojibake_after_pdf_ui_toggle():
    from translation_app.core.encoding_utils import detect_mojibake

    main_window_path = Path(__file__).parent.parent / "ui" / "main_window.py"
    content = main_window_path.read_text(encoding="utf-8")

    assert "Xuất PDF thử nghiệm cho PDF text đơn giản" in content
    assert "Báo cáo PDF thử nghiệm" in content
    assert "Xuất báo cáo JSON" in content
    assert "Xuất báo cáo HTML" in content
    assert "DOCX ổn định" in content
    assert not detect_mojibake(content)


def test_wizard_api_key_guide_onboarding():
    """Verify that the onboarding wizard UI elements are properly set up and functional without errors."""
    from translation_app.ui.main_window import MainWindow
    root = MainWindow()
    root.withdraw()
    try:
        # 1. UI has the quick setup section title
        # 2. Check the onboarding instruction about 15 API keys
        assert hasattr(root, "guide_data")
        assert "gemini" in root.guide_data
        assert "groq" in root.guide_data
        assert "openrouter" in root.guide_data
        assert "deepseek" in root.guide_data
        assert "mistral" in root.guide_data

        # Verify onboarding text content
        widgets_text = []
        def traverse(widget):
            for child in widget.winfo_children():
                if hasattr(child, "cget"):
                    try:
                        text = child.cget("text")
                        if text:
                            widgets_text.append(text)
                    except:
                        pass
                traverse(child)
        traverse(root.tab_ai)
        full_text = " ".join(widgets_text)

        assert "Bạn KHÔNG CẦN phải lấy đầy đủ" in full_text
        assert "Gemini AI" in full_text
        assert "Bước 1: Chọn nhà cung cấp" in full_text

        # 3. Verify step-by-step guides inside guide_data
        for prov_id in ["gemini", "groq", "openrouter", "deepseek", "mistral"]:
            prov_info = root.guide_data[prov_id]
            assert len(prov_info["steps"]) > 0
            assert prov_info["difficulty"] == "Dễ"

        # 4. Verify selection change callback changes the labels dynamically
        root.wizard_prov_var.set("Groq")
        root._on_wizard_selection_changed()
        assert root.lbl_wiz_name.cget("text") == "Groq AI"
        assert root.lbl_wiz_diff.cget("text") == "Dễ"
        assert root.lbl_wiz_model.cget("text") == "llama3-8b-8192"

        # Change to OpenRouter
        root.wizard_prov_var.set("OpenRouter")
        root._on_wizard_selection_changed()
        assert root.lbl_wiz_name.cget("text") == "OpenRouter"
        assert root.lbl_wiz_model.cget("text") == "google/gemini-2.5-flash:free"

        # 5. Verify copying suggested model works safely (mocking messagebox)
        root.wizard_prov_var.set("Gemini AI")
        root._on_wizard_selection_changed()
        # Mock messagebox showinfo
        import translation_app.ui.main_window
        original_showinfo = translation_app.ui.main_window.messagebox.showinfo
        showinfo_calls = []
        translation_app.ui.main_window.messagebox.showinfo = lambda title, msg: showinfo_calls.append((title, msg))
        try:
            root._on_wizard_copy_model()
            assert len(showinfo_calls) == 1
            assert "gemini-2.5-flash" in showinfo_calls[0][1]
        finally:
            translation_app.ui.main_window.messagebox.showinfo = original_showinfo

    finally:
        root.destroy()
