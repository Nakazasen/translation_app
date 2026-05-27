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
