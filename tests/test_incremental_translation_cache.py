import pytest

from translation_app.config import config
from translation_app.core.file_handlers.text_handler import TextHandler
from translation_app.core.incremental_translation_cache import (
    get_cache_path,
    get_cached_translation,
    load_incremental_cache,
    record_cached_translation,
    save_incremental_cache,
)
from translation_app.utils.error_handler import FileProcessingError


class ResumableFakeTranslationService:
    def __init__(self):
        self.calls = []
        self.fail_on_call = None

    def raise_if_file_translation_stopped(self):
        return None

    def translate_text(self, text, src_lang, dest_lang):
        self.calls.append(text)
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("simulated provider failure")
        return f"[{text}]"


def test_text_handler_reuses_incremental_cache_after_mid_file_failure(monkeypatch, tmp_path):
    import translation_app.core.incremental_translation_cache as incremental_cache

    monkeypatch.setattr(incremental_cache, "get_incremental_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(config, "max_text_length", 2)

    input_file = tmp_path / "source.txt"
    output_file = tmp_path / "translated.txt"
    input_file.write_text("abcdef", encoding="utf-8")

    service = ResumableFakeTranslationService()
    handler = TextHandler(service)
    service.fail_on_call = 2

    with pytest.raises(FileProcessingError):
        handler.translate(str(input_file), str(output_file), "vi", "en")

    cache_path = get_cache_path(str(input_file), "vi", "en", "text")
    assert cache_path.exists()

    service.calls = []
    service.fail_on_call = None
    handler.translate(str(input_file), str(output_file), "vi", "en")

    assert service.calls == ["cd", "ef"]
    assert output_file.read_text(encoding="utf-8") == "[ab][cd][ef]"
    assert not cache_path.exists()


def test_legacy_cache_without_new_metadata_loads(monkeypatch, tmp_path):
    import translation_app.core.incremental_translation_cache as incremental_cache

    monkeypatch.setattr(incremental_cache, "get_incremental_cache_dir", lambda: tmp_path / "cache")

    input_file = tmp_path / "source.txt"
    input_file.write_text("Hello", encoding="utf-8")
    payload = {
        "input_file": str(input_file),
        "source_file_hash": incremental_cache.build_file_fingerprint(str(input_file)),
        "source_lang": "en",
        "target_lang": "vi",
        "handler": "text",
        "updated_at": "2024-01-01T00:00:00+00:00",
        "segments": {
            "chunk:0:5": {
                "source_hash": "unused",
                "translated_text": "Xin chao",
            }
        },
    }
    cache_path = get_cache_path(str(input_file), "en", "vi", "text")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(__import__("json").dumps(payload), encoding="utf-8")

    loaded = load_incremental_cache(str(input_file), "en", "vi", "text")

    assert loaded["segments"] == payload["segments"]
    assert loaded["cache_schema_version"] == 1
    assert loaded["provider_id"] == ""
    assert loaded["model_id"] == ""


def test_source_file_hash_change_does_not_reuse_cache(monkeypatch, tmp_path):
    import translation_app.core.incremental_translation_cache as incremental_cache

    monkeypatch.setattr(incremental_cache, "get_incremental_cache_dir", lambda: tmp_path / "cache")

    input_file = tmp_path / "source.txt"
    input_file.write_text("Hello", encoding="utf-8")
    payload = load_incremental_cache(str(input_file), "en", "vi", "text")
    record_cached_translation(payload, "chunk:0:5", "en", "vi", "Hello", "Xin chao")
    save_incremental_cache(str(input_file), "en", "vi", "text", payload)

    input_file.write_text("Hello changed", encoding="utf-8")
    loaded = load_incremental_cache(str(input_file), "en", "vi", "text")

    assert loaded["segments"] == {}
    assert loaded["source_file_hash"] == incremental_cache.build_file_fingerprint(str(input_file))


def test_target_language_change_does_not_reuse_cache(monkeypatch, tmp_path):
    import translation_app.core.incremental_translation_cache as incremental_cache

    monkeypatch.setattr(incremental_cache, "get_incremental_cache_dir", lambda: tmp_path / "cache")

    input_file = tmp_path / "source.txt"
    input_file.write_text("Hello", encoding="utf-8")
    payload = load_incremental_cache(str(input_file), "en", "vi", "text")
    record_cached_translation(payload, "chunk:0:5", "en", "vi", "Hello", "Xin chao")
    save_incremental_cache(str(input_file), "en", "vi", "text", payload)

    loaded = load_incremental_cache(str(input_file), "en", "fr", "text")

    assert loaded["segments"] == {}
    assert loaded["target_lang"] == "fr"


def test_handler_change_does_not_reuse_cache(monkeypatch, tmp_path):
    import translation_app.core.incremental_translation_cache as incremental_cache

    monkeypatch.setattr(incremental_cache, "get_incremental_cache_dir", lambda: tmp_path / "cache")

    input_file = tmp_path / "source.txt"
    input_file.write_text("Hello", encoding="utf-8")
    payload = load_incremental_cache(str(input_file), "en", "vi", "text")
    record_cached_translation(payload, "chunk:0:5", "en", "vi", "Hello", "Xin chao")
    save_incremental_cache(str(input_file), "en", "vi", "text", payload)

    loaded = load_incremental_cache(str(input_file), "en", "vi", "word")

    assert loaded["segments"] == {}
    assert loaded["handler"] == "word"


def test_provider_model_metadata_is_saved_when_provided(monkeypatch, tmp_path):
    import translation_app.core.incremental_translation_cache as incremental_cache

    monkeypatch.setattr(incremental_cache, "get_incremental_cache_dir", lambda: tmp_path / "cache")

    input_file = tmp_path / "source.txt"
    input_file.write_text("Hello", encoding="utf-8")
    metadata = {
        "strategy": "router",
        "provider_policy": "ai_first",
        "provider_id": "groq",
        "model_id": "llama-test",
        "handler_version": "text-v2",
    }
    payload = load_incremental_cache(str(input_file), "en", "vi", "text", metadata=metadata)
    record_cached_translation(payload, "chunk:0:5", "en", "vi", "Hello", "Xin chao")
    save_incremental_cache(str(input_file), "en", "vi", "text", payload, metadata=metadata)

    loaded = load_incremental_cache(str(input_file), "en", "vi", "text")

    assert loaded["cache_schema_version"] == 2
    assert loaded["provider_policy"] == "ai_first"
    assert loaded["strategy"] == "router"
    assert loaded["provider_id"] == "groq"
    assert loaded["model_id"] == "llama-test"
    assert loaded["handler_version"] == "text-v2"


def test_provider_model_change_does_not_invalidate_without_strict_matching(monkeypatch, tmp_path):
    import translation_app.core.incremental_translation_cache as incremental_cache

    monkeypatch.setattr(incremental_cache, "get_incremental_cache_dir", lambda: tmp_path / "cache")

    input_file = tmp_path / "source.txt"
    input_file.write_text("Hello", encoding="utf-8")
    original_metadata = {"provider_id": "groq", "model_id": "llama-test"}
    payload = load_incremental_cache(str(input_file), "en", "vi", "text", metadata=original_metadata)
    record_cached_translation(payload, "chunk:0:5", "en", "vi", "Hello", "Xin chao")
    save_incremental_cache(str(input_file), "en", "vi", "text", payload, metadata=original_metadata)

    loaded = load_incremental_cache(
        str(input_file),
        "en",
        "vi",
        "text",
        metadata={"provider_id": "deepseek", "model_id": "deepseek-test"},
    )

    assert get_cached_translation(loaded, "chunk:0:5", "en", "vi", "Hello") == "Xin chao"


def test_provider_model_change_invalidates_with_strict_matching(monkeypatch, tmp_path):
    import translation_app.core.incremental_translation_cache as incremental_cache

    monkeypatch.setattr(incremental_cache, "get_incremental_cache_dir", lambda: tmp_path / "cache")

    input_file = tmp_path / "source.txt"
    input_file.write_text("Hello", encoding="utf-8")
    original_metadata = {"provider_id": "groq", "model_id": "llama-test"}
    payload = load_incremental_cache(str(input_file), "en", "vi", "text", metadata=original_metadata)
    record_cached_translation(payload, "chunk:0:5", "en", "vi", "Hello", "Xin chao")
    save_incremental_cache(str(input_file), "en", "vi", "text", payload, metadata=original_metadata)

    loaded = load_incremental_cache(
        str(input_file),
        "en",
        "vi",
        "text",
        metadata={"provider_id": "deepseek", "model_id": "deepseek-test"},
        strict_provider_model=True,
    )

    assert loaded["segments"] == {}
    assert loaded["provider_id"] == "deepseek"
    assert loaded["model_id"] == "deepseek-test"
