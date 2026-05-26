import os
import tempfile
import pytest
import sqlite3
from deep_translator import GoogleTranslator

from translation_app.core.translation_memory import TranslationMemoryManager, normalize_text, get_segment_hash
from translation_app.core.translator import TranslationService
from translation_app.core.ai_service import get_ai_service

@pytest.fixture
def temp_db_path():
    """Fixture to create a temporary database path and clean it up after test."""
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass

@pytest.fixture
def tm_manager(temp_db_path):
    """Fixture to initialize a TranslationMemoryManager with a temporary DB."""
    import translation_app.core.translation_memory
    translation_app.core.translation_memory._tm_manager = None
    return TranslationMemoryManager(temp_db_path)

def test_tm_normalization():
    """Verify that spaces/tabs are collapsed but newlines are preserved."""
    assert normalize_text("  hello   world  ") == "hello world"
    assert normalize_text("hello\n  world   \t ") == "hello\nworld"
    assert normalize_text("\n\nhello\n\n") == "hello"

def test_tm_exact_match_returns_cached_translation(tm_manager):
    """Verify that exact matches (even with space variations) return the cached translation."""
    src = "ja"
    tgt = "vi"
    source_text = "  こんにちは   世界  "  # Normalized: "こんにちは 世界"
    translated_text = "Xin chào thế giới"
    
    # Save the segment using standard text
    saved = tm_manager.save_segment(src, tgt, "こんにちは 世界", translated_text, "test", "test-model")
    assert saved is True
    
    # Lookup using text with extra space variations
    cached = tm_manager.lookup_segment(src, tgt, source_text)
    assert cached == translated_text

def test_tm_saves_successful_translation(tm_manager):
    """Verify that successful translations are persisted correctly to the DB."""
    src = "en"
    tgt = "vi"
    source = "Hello"
    translated = "Xin chào"
    
    saved = tm_manager.save_segment(src, tgt, source, translated, "test-provider", "test-model")
    assert saved is True
    
    # Look directly in the database
    with sqlite3.connect(tm_manager.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT source_text, translated_text, provider, model FROM segments")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == source
        assert row[1] == translated
        assert row[2] == "test-provider"
        assert row[3] == "test-model"

def test_tm_does_not_cache_failed_translation(tm_manager):
    """Verify that translation memory does not cache empty strings or failure error keywords."""
    src = "en"
    tgt = "vi"
    
    # Empty translations should be rejected
    assert tm_manager.save_segment(src, tgt, "Hello", "") is False
    assert tm_manager.save_segment(src, tgt, "Hello", "   ") is False
    
    # Failed keywords should be rejected
    assert tm_manager.save_segment(src, tgt, "Hello", "Translation failed: timeout") is False
    assert tm_manager.save_segment(src, tgt, "Hello", "error: API limit reached") is False
    assert tm_manager.save_segment(src, tgt, "Hello", "Failed to translate cell") is False
    
    # Verify DB is completely empty
    with sqlite3.connect(tm_manager.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM segments")
        count = cursor.fetchone()[0]
        assert count == 0

def test_tm_separates_language_pairs(tm_manager):
    """Verify that translation memory distinguishes between different language pairs for same source text."""
    source = "Bonjour"
    
    # Save fr -> en
    tm_manager.save_segment("fr", "en", source, "Hello", "test", "model")
    
    # Save fr -> vi
    tm_manager.save_segment("fr", "vi", source, "Xin chào", "test", "model")
    
    # Lookup fr -> en should NOT return fr -> vi
    assert tm_manager.lookup_segment("fr", "en", source) == "Hello"
    assert tm_manager.lookup_segment("fr", "vi", source) == "Xin chào"
    assert tm_manager.lookup_segment("en", "vi", source) is None

def test_tm_hit_count_increments(tm_manager):
    """Verify that exact match lookups successfully increment the hit_count column."""
    src = "en"
    tgt = "vi"
    source = "Apple"
    translated = "Quả táo"
    
    tm_manager.save_segment(src, tgt, source, translated, "test", "model")
    
    # Initial hit count should be 0
    with sqlite3.connect(tm_manager.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT hit_count FROM segments WHERE source_text = ?", (source,))
        assert cursor.fetchone()[0] == 0
        
    # Perform lookup 1
    res1 = tm_manager.lookup_segment(src, tgt, source)
    assert res1 == translated
    
    # Hit count should be 1
    with sqlite3.connect(tm_manager.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT hit_count FROM segments WHERE source_text = ?", (source,))
        assert cursor.fetchone()[0] == 1
        
    # Perform lookup 2
    res2 = tm_manager.lookup_segment(src, tgt, source)
    assert res2 == translated
    
    # Hit count should be 2
    with sqlite3.connect(tm_manager.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT hit_count FROM segments WHERE source_text = ?", (source,))
        assert cursor.fetchone()[0] == 2

def test_translator_uses_tm_cache_before_provider_call(temp_db_path, monkeypatch):
    """Verify that TranslationService uses TM cache first and does not invoke the translation provider."""
    # 1. Set up global TM manager with our temporary database
    import translation_app.core.translation_memory
    translation_app.core.translation_memory._tm_manager = None
    
    from translation_app.core.translation_memory import get_tm_manager
    tm = get_tm_manager(temp_db_path)
    
    src = "en"
    tgt = "vi"
    source = "UniqueTestingStringThatWillNeverExistNormally"
    translated = "TM Cached Translation Successful"
    
    # Pre-cache the translation
    tm.save_segment(src, tgt, source, translated, "test-provider", "test-model")
    
    # 2. Mock GoogleTranslator.translate to raise an error if called, proving it wasn't invoked
    from deep_translator import GoogleTranslator
    def mock_translate(*args, **kwargs):
        raise AssertionError("Translation provider was invoked but TM cache should have intercepted!")
    monkeypatch.setattr(GoogleTranslator, "translate", mock_translate)
    
    # 3. Call translation service
    service = TranslationService()
    service.set_strategy("google translate (mặc định)")
    
    res = service.translate_text(source, src, tgt)
    assert res == translated

def test_translator_does_not_save_when_tm_disabled(temp_db_path, monkeypatch):
    """Verify that when use_translation_memory=False, no TM lookup or save is performed."""
    import translation_app.core.translation_memory
    translation_app.core.translation_memory._tm_manager = None
    
    from translation_app.core.translation_memory import get_tm_manager
    tm = get_tm_manager(temp_db_path)
    
    # 1. Disable TM in config
    ai_service = get_ai_service()
    ai_service.config_manager.use_translation_memory = False
    
    # 2. Mock GoogleTranslator to return a fixed mock translation
    from deep_translator import GoogleTranslator
    monkeypatch.setattr(GoogleTranslator, "translate", lambda self, text: "Mocked Translation")
    
    src = "en"
    tgt = "vi"
    source = "Some new text to translate"
    
    # 3. Run translator
    service = TranslationService()
    service.set_strategy("google translate (mặc định)")
    
    res = service.translate_text(source, src, tgt)
    assert res == "Mocked Translation"
    
    # Verify that the translation was NOT saved in TM
    cached = tm.lookup_segment(src, tgt, source)
    assert cached is None
    
    # Re-enable TM to avoid side effects on other tests
    ai_service.config_manager.use_translation_memory = True


def test_translation_event_callback_failure_does_not_fail_translation(monkeypatch):
    service = TranslationService()
    service.set_strategy("google translate (mặc định)")
    service.set_runtime_observer(lambda event, metadata: (_ for _ in ()).throw(RuntimeError("observer boom")))

    monkeypatch.setattr(GoogleTranslator, "translate", lambda self, text: "Observer Safe")

    result = service.translate_text("Hello world", "en", "vi")

    assert result == "Observer Safe"
