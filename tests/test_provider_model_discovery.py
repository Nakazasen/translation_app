# -*- coding: utf-8 -*-
import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from copy import deepcopy

import pytest

from translation_app.core.ai_service import AIConfigManager
from translation_app.core.providers import build_provider_profiles


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_manager(tmp_path: Path, payload: dict | None = None) -> AIConfigManager:
    config_path = tmp_path / "ai_settings.json"
    if payload is not None:
        _write_config(config_path, payload)
    return AIConfigManager(str(config_path))


class _FakeUrlOpenResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_refresh_chatanywhere_models_from_openai_compatible_models_endpoint(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)
    providers = manager.providers_config
    providers["chatanywhere"]["base_url"] = "https://mock-chatanywhere.org/v1"
    providers["chatanywhere"]["api_keys"] = ["sk-chatanywhere-token"]
    manager.providers_config = providers

    mock_response = {
        "data": [
            {"id": "gpt-5", "object": "model"},
            {"id": "gpt-5-mini", "object": "model"},
            {"id": "deepseek-v3", "object": "model"},
        ]
    }
    monkeypatch.setattr(
        "translation_app.core.ai_service.urllib.request.urlopen",
        lambda request, timeout=0: _FakeUrlOpenResponse(mock_response),
    )

    discovered = manager.refresh_provider_models("chatanywhere")
    assert "gpt-5" in discovered
    assert "gpt-5-mini" in discovered
    assert "deepseek-v3" in discovered

    catalog = manager.get_provider_model_catalog_snapshot()
    deepseek_entry = next(m for m in catalog["providers"]["chatanywhere"]["models"] if m["id"] == "deepseek-v3")
    assert deepseek_entry["source"] == "api_discovered"
    assert deepseek_entry["visibility"] == "current_key_visible"
    assert deepseek_entry["capabilities"]["text"] is True
    assert deepseek_entry["capabilities"]["vision"] is False


def test_refresh_nvidia_models_from_models_endpoint(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)
    providers = manager.providers_config
    providers["nvidia_nim"]["base_url"] = "https://mock-nvidia.com/v1"
    providers["nvidia_nim"]["api_keys"] = ["nvapi-token"]
    manager.providers_config = providers

    mock_response = {
        "data": [
            {"id": "meta/llama-3.3-70b-instruct"},
            {"id": "nvidia/llama-3.1-nemotron-70b-instruct"},
            {"id": "gpt-4o-contaminated"}, # Non-native contaminated model noise
            {"id": "models/gemini-1.5-pro"}, # Non-native contaminated model noise
        ]
    }
    monkeypatch.setattr(
        "translation_app.core.ai_service.urllib.request.urlopen",
        lambda request, timeout=0: _FakeUrlOpenResponse(mock_response),
    )

    discovered = manager.refresh_provider_models("nvidia_nim")
    assert "meta/llama-3.3-70b-instruct" in discovered
    assert "nvidia/llama-3.1-nemotron-70b-instruct" in discovered
    assert "gpt-4o-contaminated" not in discovered
    assert "models/gemini-1.5-pro" not in discovered


def test_refresh_models_does_not_delete_user_added_models(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)
    manager.add_provider_model("deepseek", "custom-user-model", label="My Custom Model", source="user")
    
    providers = manager.providers_config
    providers["deepseek"]["base_url"] = "https://mock-deepseek.com/v1"
    providers["deepseek"]["api_keys"] = ["ds-key"]
    manager.providers_config = providers

    mock_response = {
        "data": [
            {"id": "deepseek-chat"},
        ]
    }
    monkeypatch.setattr(
        "translation_app.core.ai_service.urllib.request.urlopen",
        lambda request, timeout=0: _FakeUrlOpenResponse(mock_response),
    )

    discovered = manager.refresh_provider_models("deepseek")
    assert discovered == ["deepseek-chat"]

    # Verify custom model is preserved!
    catalog = manager.get_provider_model_catalog_snapshot()
    models = catalog["providers"]["deepseek"]["models"]
    model_ids = [m["id"] for m in models]
    assert "custom-user-model" in model_ids
    assert "deepseek-chat" in model_ids

    custom_entry = next(m for m in models if m["id"] == "custom-user-model")
    assert custom_entry["source"] == "user"
    assert custom_entry["label"] == "My Custom Model"


def test_refresh_models_preserves_existing_default_model_if_still_available(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)
    catalog = manager.provider_model_catalog
    catalog["providers"]["deepseek"]["default_model"] = "custom-user-model"
    catalog["providers"]["deepseek"]["models"] = [
        {"id": "custom-user-model", "label": "My Custom Model", "enabled": True, "source": "user"}
    ]
    manager.provider_model_catalog = catalog

    providers = manager.providers_config
    providers["deepseek"]["base_url"] = "https://mock-deepseek.com/v1"
    providers["deepseek"]["api_keys"] = ["ds-key"]
    manager.providers_config = providers

    mock_response = {
        "data": [
            {"id": "deepseek-chat"},
        ]
    }
    monkeypatch.setattr(
        "translation_app.core.ai_service.urllib.request.urlopen",
        lambda request, timeout=0: _FakeUrlOpenResponse(mock_response),
    )

    manager.refresh_provider_models("deepseek")
    
    # Assert default model is still custom-user-model since it remains enabled
    reloaded = manager.provider_model_catalog
    assert reloaded["providers"]["deepseek"]["default_model"] == "custom-user-model"


def test_refresh_models_sanitizes_authorization_error(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)
    providers = manager.providers_config
    providers["openai_compatible"]["base_url"] = "https://mock-openai.com/v1"
    providers["openai_compatible"]["api_keys"] = ["sk-super-secret-key-12345"]
    manager.providers_config = providers

    request = urllib.request.Request("https://mock-openai.com/v1/models")
    payload = json.dumps({"error": {"message": "Bearer sk-super-secret-key-12345 invalid"}}).encode("utf-8")

    def _raise(*args, **kwargs):
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs={},
            fp=io.BytesIO(payload),
        )

    monkeypatch.setattr("translation_app.core.ai_service.urllib.request.urlopen", _raise)

    with pytest.raises(RuntimeError) as excinfo:
        manager.refresh_provider_models("openai_compatible")

    message = str(excinfo.value)
    assert "sk-super-secret-key-12345" not in message
    assert "[REDACTED_API_KEY]" in message


def test_refresh_models_failure_does_not_destroy_catalog(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)
    old_catalog = deepcopy(manager.provider_model_catalog)
    
    providers = manager.providers_config
    providers["openai_compatible"]["base_url"] = "https://mock-openai.com/v1"
    providers["openai_compatible"]["api_keys"] = ["sk-super-secret-key-12345"]
    manager.providers_config = providers

    def _raise_error(*args, **kwargs):
        raise ConnectionResetError("Connection refused by target peer")

    monkeypatch.setattr("translation_app.core.ai_service.urllib.request.urlopen", _raise_error)

    with pytest.raises(RuntimeError):
        manager.refresh_provider_models("openai_compatible")

    # Assert catalog is completely intact and unaffected by failure
    assert manager.provider_model_catalog == old_catalog


def test_catalog_public_view_has_no_api_key_or_authorization(tmp_path):
    manager = _make_manager(tmp_path)
    providers = manager.providers_config
    providers["openai_compatible"]["api_keys"] = ["sk-secret-credentials"]
    manager.providers_config = providers

    public_view = manager.get_provider_model_catalog_public()
    assert "sk-secret-credentials" not in json.dumps(public_view)


def test_runtime_uses_discovered_default_model_not_seed_only(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)
    catalog = manager.provider_model_catalog
    catalog["providers"]["chatanywhere"]["default_model"] = "gpt-5-discovered"
    catalog["providers"]["chatanywhere"]["models"] = [
        {"id": "gpt-5-discovered", "label": "GPT 5", "enabled": True, "source": "api_discovered", "visibility": "current_key_visible"}
    ]
    manager.provider_model_catalog = catalog

    profiles = build_provider_profiles(manager)
    chatanywhere_profile = profiles["chatanywhere"]
    
    assert chatanywhere_profile.default_model == "gpt-5-discovered"
    assert chatanywhere_profile.model_pool == ["gpt-5-discovered"]
