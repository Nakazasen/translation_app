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
from translation_app.core.provider_router import ProviderRouter
from translation_app.core.providers import OpenAICompatibleProvider


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
    secret_key = "sk-never-leak-me-123456789"
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
        "AIzaSySentinelTestKey1234567890 "
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
    secret_key = "sk-fake-deepseek-key-999"
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
    
    secret_key = "sk-added-via-test-12345"
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
        assert "PDF này không phù hợp với chế độ thử nghiệm" in errors[0][1]
        assert "DOCX ổn định" in errors[0][1]
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
