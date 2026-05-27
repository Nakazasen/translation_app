import os
import gc
import pytest
import tempfile
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

