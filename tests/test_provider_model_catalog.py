# -*- coding: utf-8 -*-
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from translation_app.core.ai_service import AIConfigManager
from translation_app.core.encoding_utils import detect_mojibake
from translation_app.core.providers import build_provider_profiles


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_manager(tmp_path: Path, payload: dict | None = None) -> AIConfigManager:
    config_path = tmp_path / "ai_settings.json"
    if payload is not None:
        _write_config(config_path, payload)
    return AIConfigManager(str(config_path))


def test_default_models_seed_only_when_missing(tmp_path):
    manager = _make_manager(
        tmp_path,
        {
            "api_key": "",
            "api_keys": [],
            "providers": {
                "deepseek": {
                    "enabled": True,
                    "type": "openai_compatible",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_keys": [],
                    "models": ["legacy-deepseek-model"],
                }
            },
        },
    )

    catalog = manager.get_provider_model_catalog_public()
    assert catalog["providers"]["deepseek"]["models"]
    assert catalog["providers"]["openai_compatible"]["models"] == []

    custom_catalog = {
        "version": 1,
        "providers": {
            "deepseek": {
                "default_model": "only-user-model",
                "models": [
                    {"id": "only-user-model", "label": "Only User Model", "enabled": True, "source": "user", "capabilities": {"text": True, "vision": False}},
                ],
            }
        },
    }
    manager.provider_model_catalog = custom_catalog
    roundtrip = manager.get_provider_model_catalog_public()
    deepseek_models = [item["id"] for item in roundtrip["providers"]["deepseek"]["models"]]
    assert deepseek_models == ["only-user-model"]


def test_user_added_models_are_not_reset(tmp_path):
    manager = _make_manager(tmp_path)
    assert manager.add_provider_model("deepseek", "custom-deepseek-r1", label="Custom DeepSeek R1") is True
    manager.save_config()

    reloaded = AIConfigManager(str(tmp_path / "ai_settings.json"))
    models = [item["id"] for item in reloaded.get_provider_model_catalog_public()["providers"]["deepseek"]["models"]]
    assert "custom-deepseek-r1" in models


def test_provider_model_catalog_public_redacts_no_secrets(tmp_path):
    manager = _make_manager(tmp_path)
    providers = manager.providers_config
    providers["deepseek"]["api_keys"] = ["sk-secret-provider-123"]
    manager.providers_config = providers

    public_catalog = manager.get_provider_model_catalog_public()
    assert "sk-secret-provider-123" not in json.dumps(public_catalog, ensure_ascii=False)


def test_add_remove_enable_disable_provider_model(tmp_path):
    manager = _make_manager(tmp_path)
    assert manager.add_provider_model("chatanywhere", "gpt-custom-1") is True
    assert manager.set_provider_model_enabled("chatanywhere", "gpt-custom-1", False) is True
    catalog = manager.get_provider_model_catalog_public()
    model_entry = next(item for item in catalog["providers"]["chatanywhere"]["models"] if item["id"] == "gpt-custom-1")
    assert model_entry["enabled"] is False
    assert manager.set_provider_model_enabled("chatanywhere", "gpt-custom-1", True) is True
    assert manager.remove_provider_model("chatanywhere", "gpt-custom-1") is True
    assert "gpt-custom-1" not in [item["id"] for item in manager.get_provider_model_catalog_public()["providers"]["chatanywhere"]["models"]]


def test_set_default_model_validates_model_exists(tmp_path):
    manager = _make_manager(tmp_path)
    assert manager.set_provider_default_model("nvidia_nim", "missing-model") is False
    assert manager.set_provider_default_model("nvidia_nim", "meta/llama-3.1-405b-instruct") is True


def test_router_uses_catalog_enabled_models(tmp_path):
    manager = _make_manager(tmp_path)
    manager.provider_model_catalog = {
        "version": 1,
        "providers": {
            "deepseek": {
                "default_model": "model-b",
                "models": [
                    {"id": "model-a", "enabled": True, "source": "user", "capabilities": {"text": True, "vision": False}},
                    {"id": "model-b", "enabled": True, "source": "user", "capabilities": {"text": True, "vision": False}},
                    {"id": "model-c", "enabled": False, "source": "user", "capabilities": {"text": True, "vision": False}},
                ],
            }
        },
    }

    profile = build_provider_profiles(manager)["deepseek"]
    assert profile.default_model == "model-b"
    assert profile.model_pool == ["model-b", "model-a"]


def test_disabled_model_is_skipped(tmp_path):
    manager = _make_manager(tmp_path)
    manager.provider_model_catalog = {
        "version": 1,
        "providers": {
            "openai_compatible": {
                "default_model": "allowed-model",
                "models": [
                    {"id": "allowed-model", "enabled": True, "source": "user", "capabilities": {"text": True, "vision": False}},
                    {"id": "disabled-model", "enabled": False, "source": "user", "capabilities": {"text": True, "vision": False}},
                ],
            }
        },
    }

    profile = build_provider_profiles(manager)["openai_compatible"]
    assert profile.model_pool == ["allowed-model"]
    assert "disabled-model" not in profile.model_pool


class _FakeUrlOpenResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_refresh_models_openai_compatible_mock(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)
    providers = manager.providers_config
    providers["openai_compatible"]["base_url"] = "https://mock.local/v1"
    providers["openai_compatible"]["api_keys"] = ["sk-test-refresh"]
    manager.providers_config = providers

    monkeypatch.setattr(
        "translation_app.core.ai_service.urllib.request.urlopen",
        lambda request, timeout=0: _FakeUrlOpenResponse({"data": [{"id": "catalog-model-a"}, {"id": "catalog-model-b"}]}),
    )

    discovered = manager.refresh_provider_models("openai_compatible")
    assert discovered == ["catalog-model-a", "catalog-model-b"]
    profile = build_provider_profiles(manager)["openai_compatible"]
    assert "catalog-model-a" in profile.model_pool
    assert "catalog-model-b" in profile.model_pool


def test_refresh_models_auth_error_is_sanitized(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)
    providers = manager.providers_config
    providers["openai_compatible"]["base_url"] = "https://mock.local/v1"
    providers["openai_compatible"]["api_keys"] = ["sk-secret-refresh-123"]
    manager.providers_config = providers

    request = urllib.request.Request("https://mock.local/v1/models")
    payload = json.dumps({"error": {"message": "Authorization: Bearer sk-secret-refresh-123 invalid_api_key"}}).encode("utf-8")

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
    assert "sk-secret-refresh-123" not in message
    assert "Authorization: [REDACTED_API_KEY]" in message


def test_import_export_catalog_roundtrip_utf8(tmp_path):
    manager = _make_manager(tmp_path)
    manager.add_provider_model("openai_compatible", "mô-hình-thử-nghiệm", label="Mô hình thử nghiệm")
    manager.set_provider_default_model("openai_compatible", "mô-hình-thử-nghiệm")

    export_path = tmp_path / "provider_model_catalog.json"
    manager.export_provider_model_catalog(str(export_path))

    imported = _make_manager(tmp_path / "imported")
    imported.import_provider_model_catalog(str(export_path))
    public_catalog = imported.get_provider_model_catalog_public()
    labels = [item["label"] for item in public_catalog["providers"]["openai_compatible"]["models"]]
    assert "Mô hình thử nghiệm" in labels


def test_ui_model_list_reads_catalog_not_hardcoded(tmp_path, monkeypatch):
    from translation_app.ui.main_window import MainWindow

    manager = _make_manager(tmp_path)
    manager.provider_model_catalog = {
        "version": 1,
        "providers": {
            "deepseek": {
                "default_model": "custom-ui-model",
                "models": [
                    {"id": "custom-ui-model", "label": "Custom UI Model", "enabled": True, "source": "user", "capabilities": {"text": True, "vision": False}},
                ],
            }
        },
    }

    fake_service = type("FakeService", (), {"config_manager": manager})()
    monkeypatch.setattr("translation_app.core.ai_service.get_ai_service", lambda api_key=None: fake_service)

    root = MainWindow()
    root.withdraw()
    try:
        root.prov_tree.selection_set("deepseek")
        root._on_provider_selected()
        combo_values = list(root.combo_model.cget("values"))
        assert combo_values == ["custom-ui-model"]
        assert root.prov_default_model_var.get() == "custom-ui-model"
    finally:
        root.destroy()


def test_check_mojibake_clean_after_model_catalog_ui():
    content = (Path(__file__).parent.parent / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "Thêm Model" in content
    assert "Làm mới model" in content
    assert not detect_mojibake(content)
