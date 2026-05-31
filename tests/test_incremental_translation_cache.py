import pytest

from translation_app.config import config
from translation_app.core.file_handlers.text_handler import TextHandler
from translation_app.core.incremental_translation_cache import get_cache_path
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
