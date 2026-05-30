import pytest
import tkinter as tk
import customtkinter as ctk
from translation_app.ui.main_window import MainWindow
from translation_app.core.ai_service import get_ai_service
from translation_app.core.providers import get_default_provider_profiles
from translation_app.core.translator import TranslationService

def test_lbl_last_translation_source_exists():
    root = MainWindow()
    root.withdraw()
    try:
        assert hasattr(root, "lbl_last_translation_source")
        assert isinstance(root.lbl_last_translation_source, (tk.Label, ctk.CTkLabel))
        assert root.lbl_last_translation_source.cget("text") == ""
    finally:
        root.destroy()

def test_translate_paragraph_updates_telemetry_label(monkeypatch):
    root = MainWindow()
    root.withdraw()
    try:
        # Mock translate_text to set last_translation_metadata
        def fake_translate_text(text, src, dest):
            root.translation_service.last_translation_metadata = {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "strategy": "ai",
                "fallback_count": 1,
                "attempts": []
            }
            return "Dịch: " + text

        monkeypatch.setattr(root.translation_service, "translate_text", fake_translate_text)

        root.entry_paragraph_input.delete("1.0", tk.END)
        root.entry_paragraph_input.insert(tk.END, "Xin chào")
        root.translate_paragraph()

        # Telemetry label must be updated
        telemetry = root.lbl_last_translation_source.cget("text")
        assert "DeepSeek" in telemetry
        assert "deepseek-chat" in telemetry
        assert "Fallback: 1 lần" in telemetry
    finally:
        root.destroy()

def test_provider_priority_buttons_exist():
    root = MainWindow()
    root.withdraw()
    try:
        assert hasattr(root, "btn_move_up")
        assert hasattr(root, "btn_move_down")
        assert root.btn_move_up.cget("text") == "▲ Di chuyển lên"
        assert root.btn_move_down.cget("text") == "▼ Di chuyển xuống"
    finally:
        root.destroy()

def test_move_provider_up_down(monkeypatch):
    root = MainWindow()
    root.withdraw()
    try:
        config_mgr = root.config_manager
        config_mgr.providers_config = get_default_provider_profiles()
        config_mgr.provider_order = [
            "gemini",
            "chatanywhere",
            "deepseek",
            "nvidia_nim",
            "openai_compatible",
            "google",
        ]
        config_mgr.save_config()

        # Select 'chatanywhere' in prov_tree
        root.prov_tree.selection_set("chatanywhere")
        
        # Move 'chatanywhere' up => it should become index 0
        root._move_provider_up()
        assert config_mgr.provider_order[0] == "chatanywhere"
        assert config_mgr.provider_order[1] == "gemini"

        # Move 'chatanywhere' down => it should go back to index 1
        root._move_provider_down()
        assert config_mgr.provider_order[0] == "gemini"
        assert config_mgr.provider_order[1] == "chatanywhere"
    finally:
        root.destroy()
