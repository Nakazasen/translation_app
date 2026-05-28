# -*- coding: utf-8 -*-
import tkinter as tk
from pathlib import Path

import pytest

from translation_app.core.ai_service import AIConfigManager
from translation_app.ui.main_window import MainWindow


def _write_config(path: Path, payload: dict) -> None:
    import json
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_manager(tmp_path: Path, payload: dict | None = None) -> AIConfigManager:
    config_path = tmp_path / "ai_settings.json"
    if payload is not None:
        _write_config(config_path, payload)
    return AIConfigManager(str(config_path))


def test_model_list_shows_api_discovered_tags(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)
    manager.provider_model_catalog = {
        "version": 1,
        "providers": {
            "nvidia_nim": {
                "default_model": "llama-discovered-model",
                "models": [
                    {
                        "id": "llama-discovered-model",
                        "label": "llama-discovered-model",
                        "enabled": True,
                        "source": "api_discovered",
                        "visibility": "current_key_visible",
                        "capabilities": {"text": True, "vision": False}
                    },
                    {
                        "id": "user-custom-model",
                        "label": "user-custom-model",
                        "enabled": False,
                        "source": "user",
                        "visibility": "unverified",
                        "capabilities": {"text": True, "vision": False}
                    }
                ]
            }
        }
    }

    fake_service = type("FakeService", (), {"config_manager": manager})()
    monkeypatch.setattr("translation_app.core.ai_service.get_ai_service", lambda api_key=None: fake_service)

    root = MainWindow()
    root.withdraw()
    try:
        root.prov_tree.selection_set("nvidia_nim")
        root._on_provider_selected()

        items = list(root.listbox_models.get(0, tk.END))
        
        # Verify custom tag formatting matches spec exactly!
        # Status "Bật" or "Tắt", source mapped, visibility mapped
        assert any("llama-discovered-model [Bật | API-discovered | current-key-visible]" in x for x in items)
        assert any("user-custom-model [Tắt | configured/user | unverified]" in x for x in items)
    finally:
        root.destroy()


def test_model_dropdown_includes_discovered_models(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)
    manager.provider_model_catalog = {
        "version": 1,
        "providers": {
            "chatanywhere": {
                "default_model": "gpt-5-discovered",
                "models": [
                    {
                        "id": "gpt-5-discovered",
                        "label": "gpt-5-discovered",
                        "enabled": True,
                        "source": "api_discovered",
                        "visibility": "current_key_visible",
                        "capabilities": {"text": True, "vision": False}
                    },
                    {
                        "id": "gpt-4o-mini-seed",
                        "label": "gpt-4o-mini-seed",
                        "enabled": True,
                        "source": "seed",
                        "visibility": "live_validated",
                        "capabilities": {"text": True, "vision": False}
                    }
                ]
            }
        }
    }

    fake_service = type("FakeService", (), {"config_manager": manager})()
    monkeypatch.setattr("translation_app.core.ai_service.get_ai_service", lambda api_key=None: fake_service)

    root = MainWindow()
    root.withdraw()
    try:
        root.prov_tree.selection_set("chatanywhere")
        root._on_provider_selected()

        # The combobox values should be populated with enabled models
        combo_values = list(root.combo_model.cget("values"))
        assert "gpt-5-discovered" in combo_values
        assert "gpt-4o-mini-seed" in combo_values
        assert root.prov_default_model_var.get() == "gpt-5-discovered"
    finally:
        root.destroy()


def test_model_refresh_button_calls_discovery(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)
    called_refresh = []

    def mock_refresh(provider_name):
        called_refresh.append(provider_name)
        return ["discovered-a", "discovered-b"]

    monkeypatch.setattr(manager, "refresh_provider_models", mock_refresh)

    fake_service = type("FakeService", (), {"config_manager": manager})()
    monkeypatch.setattr("translation_app.core.ai_service.get_ai_service", lambda api_key=None: fake_service)

    root = MainWindow()
    root.withdraw()
    try:
        root.prov_tree.selection_set("chatanywhere")
        root._on_provider_selected()

        # Simulate clicking "Làm mới model" button
        root._refresh_provider_models_catalog()

        # Since it runs on a background thread, we wait briefly for the thread to complete
        import time
        start_time = time.time()
        while not called_refresh and time.time() - start_time < 3.0:
            root.update()
            time.sleep(0.05)

        assert "chatanywhere" in called_refresh
    finally:
        root.destroy()


def test_nvidia_models_can_exceed_seed_list(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)
    manager.provider_model_catalog = {
        "version": 1,
        "providers": {
            "nvidia_nim": {
                "default_model": "meta/llama-3.1-405b-instruct",
                "models": [
                    {"id": "meta/llama-3.1-405b-instruct", "label": "meta/llama-3.1-405b-instruct", "enabled": True, "source": "seed"},
                    {"id": "meta/llama-3.3-70b-instruct", "label": "meta/llama-3.3-70b-instruct", "enabled": True, "source": "api_discovered"},
                    {"id": "deepseek-ai/deepseek-v3", "label": "deepseek-ai/deepseek-v3", "enabled": True, "source": "api_discovered"},
                ]
            }
        }
    }

    fake_service = type("FakeService", (), {"config_manager": manager})()
    monkeypatch.setattr("translation_app.core.ai_service.get_ai_service", lambda api_key=None: fake_service)

    root = MainWindow()
    root.withdraw()
    try:
        root.prov_tree.selection_set("nvidia_nim")
        root._on_provider_selected()

        combo_values = list(root.combo_model.cget("values"))
        assert len(combo_values) == 3
        assert "meta/llama-3.3-70b-instruct" in combo_values
        assert "deepseek-ai/deepseek-v3" in combo_values
    finally:
        root.destroy()
