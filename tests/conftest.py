import pytest


@pytest.fixture(autouse=True)
def isolated_ai_service_config(tmp_path, monkeypatch):
    """Keep test config writes out of the repo-level data directory."""
    import translation_app.core.ai_service as ai_service_module
    import translation_app.core.translation_memory as tm_module

    monkeypatch.setattr(ai_service_module, "DEFAULT_CONFIG_PATH", tmp_path / "ai_settings.json")
    ai_service_module._service_instance = None
    tm_module._tm_manager = None
    yield
    ai_service_module._service_instance = None
    tm_module._tm_manager = None
