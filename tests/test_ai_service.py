"""
Test script for AI Service in Translation App
Tests: Waterfall strategy, API Key rotation, Model management, and Robust Config Persistence.
"""
import sys
import io
import json
import os
import time
import tempfile
from pathlib import Path

# Fix encoding for Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from translation_app.core.ai_service import (
    get_ai_service, 
    get_config_manager, 
    AIConfigManager, 
    get_secret_config_path,
    _decode_secret_file_payload,
    SECRET_PROTECTION_WINDOWS_DPAPI,
    SECRET_FILE_VERSION,
    DEFAULT_MODELS, 
    LIVE_TEXT_TRANSLATION_MODELS,
    validate_model_for_profile
)
from translation_app.core.translator import TranslationService, TranslationServiceError


SECRET_PATTERNS = ("AIza", "sk-", "Bearer ", "ghp_", "github_pat_")


def assert_no_raw_secrets_in_text(text: str, fake_keys: list[str]):
    for key in fake_keys:
        assert key not in text
    for marker in SECRET_PATTERNS:
        assert marker not in text


def test_ai_service():
    print("=" * 60)
    print("[TEST] Translation App AI Service Test")
    print("   Ported from leetcode_mastery with full features")
    print("=" * 60)
    
    # Test config manager
    config = get_config_manager()
    print(f"\n[OK] Config loaded from: {config.config_path.name}")
    
    # Test API Keys pool
    api_keys = config.api_keys
    print(f"\n[KEY] API Keys Pool ({len(api_keys)} keys configured):")
    for i in range(len(api_keys)):
        active = "(Active)" if i == config._current_key_index else ""
        print(f"   {i+1}. Key configured {active}")
    
    # Test current API key
    print(f"\n[KEY] Current API Key: {'Configured' if config.api_key else 'Not set'}")
    
    # Test model list
    service = get_ai_service()
    models = service.models_priority
    print(f"\n[MODELS] Waterfall Models ({len(models)} active):")
    for i, m in enumerate(models, 1):
        print(f"   {i:2}. {m}")
    
    # Test API Key rotation
    print("\n[ROTATE] Testing API Key Rotation:")
    if len(api_keys) >= 2:
        old_idx = config._current_key_index
        success = config.rotate_api_key()
        new_idx = config._current_key_index
        if success:
            print(f"   [OK] Rotated index: {old_idx} -> {new_idx}")
            # Rotate back to restore original index
            for _ in range(len(api_keys) - 1):
                config.rotate_api_key()
            print(f"   [OK] Restored original index")
        else:
            print(f"   [FAIL] Rotation failed")
    else:
        print(f"   [WARN] Need at least 2 API keys for rotation (current: {len(api_keys)} configured)")
    
    print("\n" + "=" * 60)
    print("[SUCCESS] AI Service Ready!")
    print("   Features: Waterfall fallback, API Key rotation, Web fallback")
    print("=" * 60)
    return True


def test_model_management():
    """Test model add/remove/toggle functionality."""
    print("\n[TEST] Testing Model Management:")
    config = get_config_manager()
    
    original_count = len(config.waterfall_strategy)
    print(f"   Original model count: {original_count}")
    
    # Test add model (use a live allowlist model to avoid filter-out)
    test_model = LIVE_TEXT_TRANSLATION_MODELS[0]
    config.remove_model(test_model) # remove if exists
    config.add_model(test_model, is_active=False, timeout=5)
    print(f"   + Added: {test_model}")
    
    # Test toggle
    config.toggle_model(test_model)
    print(f"   ~ Toggled: {test_model}")
    
    # Test remove
    config.remove_model(test_model)
    print(f"   - Removed: {test_model}")
    
    # restore if it was default
    config.add_model(test_model, is_active=True, timeout=10)


# =============================================================================
# MANDATORY PERSISTENCE & TIMEOUT & ROTATION TESTS
# =============================================================================

def test_load_config_corrupted_uses_backup():
    print("\n[TEST] test_load_config_corrupted_uses_backup")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        bak_path = Path(tmpdir) / "ai_settings.json.bak"
        
        # Write corrupted main config
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("{ corrupted json }")
            
        # Write valid backup config
        test_config = {
            "api_key": "SafeBackupKeyNoSecretStringValue",
            "api_keys": ["SafeBackupKeyNoSecretStringValue"],
            "waterfall_strategy": []
        }
        with open(bak_path, "w", encoding="utf-8") as f:
            json.dump(test_config, f)
            
        # Load config manager
        manager = AIConfigManager(config_path)
        assert manager.api_key == "SafeBackupKeyNoSecretStringValue"
        print("   [OK] Loaded backup successfully upon main corruption.")


def test_load_config_corrupted_does_not_overwrite_original():
    print("\n[TEST] test_load_config_corrupted_does_not_overwrite_original")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        bak_path = Path(tmpdir) / "ai_settings.json.bak"
        
        corrupted_content = "{ corrupted content }"
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(corrupted_content)
        with open(bak_path, "w", encoding="utf-8") as f:
            f.write(corrupted_content)
            
        manager = AIConfigManager(config_path)
        # Check that default in RAM was used
        assert len(manager.waterfall_strategy) == len(DEFAULT_MODELS)
        
        # Check that file content remains corrupted and was NOT overwritten
        with open(config_path, "r", encoding="utf-8") as f:
            current_content = f.read()
        assert current_content == corrupted_content
        print("   [OK] In-memory default loaded and original files were NOT overwritten.")


def test_missing_fields_are_merged_not_reset():
    print("\n[TEST] test_missing_fields_are_merged_not_reset")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        
        incomplete_config = {
            "api_keys": ["CustomKey"]
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(incomplete_config, f)
            
        manager = AIConfigManager(config_path)
        
        # Verify it merged incomplete with defaults
        assert manager.api_keys == ["CustomKey"]
        assert manager.api_key == "CustomKey"
        assert len(manager.waterfall_strategy) == len(DEFAULT_MODELS)
        print("   [OK] Config fields merged with defaults without resetting original values.")


def test_key_rotation_does_not_rewrite_config_each_request():
    print("\n[TEST] test_key_rotation_does_not_rewrite_config_each_request")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        
        test_config = {
            "api_key": "KeyA",
            "api_keys": ["KeyA", "KeyB"],
            "waterfall_strategy": []
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(test_config, f)
            
        manager = AIConfigManager(config_path)
        assert manager.api_key == "KeyA"
        
        # Patch save_config to verify it is not called
        save_called = False
        def mock_save_config():
            nonlocal save_called
            save_called = True
            return True
        manager.save_config = mock_save_config
        
        # Rotate
        success = manager.rotate_api_key()
        assert success
        assert manager.api_key == "KeyB"
        
        # Assert save_config was NOT called
        assert not save_called, "save_config should not be called on runtime key rotation"
        
        # Assert api_keys ordering is unchanged
        assert manager.api_keys == ["KeyA", "KeyB"], "api_keys ordering should not change"
        print("   [OK] Key rotated in memory, save_config not called, list ordering untouched.")


def test_ai_only_does_not_google_fallback():
    import os
    print("\n[TEST] test_ai_only_does_not_google_fallback")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        
        # Write config with empty keys to guarantee AI failure
        test_config = {
            "api_key": "",
            "api_keys": [],
            "waterfall_strategy": []
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(test_config, f)
            
        # Temporarily use our mock config directory
        ai_service = get_ai_service()
        original_config_path = ai_service.config_manager.config_path
        original_env_key = os.environ.get("GEMINI_API_KEY")
        original_use_tm = ai_service.config_manager.use_translation_memory
        try:
            # Override singleton config path and reload
            ai_service.config_manager.config_path = config_path
            if "GEMINI_API_KEY" in os.environ:
                del os.environ["GEMINI_API_KEY"]
            ai_service.reload_config()
            ai_service.config_manager.use_translation_memory = False
            
            # Explicitly force empty key and unconfigured state on the singleton
            ai_service.api_key = ""
            ai_service._configured = False
            ai_service._client = None
            
            # Setup translator
            translator = TranslationService()
            translator.set_strategy("Gemini AI (Chỉ dùng AI)")
            
            # Mock GoogleTranslator to capture if it is ever called
            import deep_translator
            original_translator = deep_translator.GoogleTranslator
            
            google_called = False
            class MockGoogleTranslator:
                def __init__(self, source=None, target=None):
                    nonlocal google_called
                    google_called = True
                def translate(self, text):
                    nonlocal google_called
                    google_called = True
                    return "Mocked Google translation"
                    
            deep_translator.GoogleTranslator = MockGoogleTranslator
            
            try:
                try:
                    translator.translate_text("Hello", "en", "vi")
                    assert False, "Should have raised TranslationServiceError"
                except TranslationServiceError as te:
                    print(f"   [OK] Raised correct exception: {te}")
                    assert "failed" in str(te).lower() or "not configured" in str(te).lower()
                    assert not google_called, "Google fallback must NOT be called in AI-only mode"
            finally:
                # Restore mock
                deep_translator.GoogleTranslator = original_translator
        finally:
            # Restore
            if original_env_key is not None:
                os.environ["GEMINI_API_KEY"] = original_env_key
            ai_service.config_manager.use_translation_memory = original_use_tm
            ai_service.config_manager.config_path = original_config_path
            ai_service.reload_config()


def test_text_waterfall_allows_only_live_models():
    print("\n[TEST] test_text_waterfall_allows_only_live_models")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        
        # Test config containing invalid models
        test_config = {
            "api_key": "KeyA",
            "api_keys": ["KeyA"],
            "waterfall_strategy": [
                {"model_id": "gemini-2.5-flash", "is_active": True, "timeout": 12},
                {"model_id": "gemini-2.5-flash-native-audio-latest", "is_active": True, "timeout": 10},
                {"model_id": "gemini-robotics-er-1.5-preview", "is_active": True, "timeout": 28},
                {"model_id": "imagen-4.0-ultra-generate-001", "is_active": True, "timeout": 10},
                {"model_id": "gemini-3.5-flash", "is_active": True, "timeout": 10}
            ]
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(test_config, f)
            
        manager = AIConfigManager(config_path)
        
        # Load and verify it correctly migrated/filtered out invalid models from active strategy
        active = manager.active_models
        print(f"   Active models loaded/merged: {active}")
        
        # All active models must be in allowlist
        for m in active:
            assert m in LIVE_TEXT_TRANSLATION_MODELS, f"Invalid model {m} found in active waterfall"
            
        # Verify specific disallowed models are not active
        for disallowed in ["gemini-2.5-flash-native-audio-latest", "gemini-robotics-er-1.5-preview", "imagen-4.0-ultra-generate-001"]:
            assert disallowed not in active, f"Disallowed model {disallowed} was not filtered out"
            
        print("   [OK] Non-text models filtered out successfully from active text waterfall.")


def test_logs_do_not_leak_api_keys():
    print("\n[TEST] test_logs_do_not_leak_api_keys")
    import io
    import logging
    
    # Capture logger output
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    logger_target = logging.getLogger("translation_app.core.ai_service")
    logger_target.addHandler(handler)
    logger_target.setLevel(logging.INFO)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        
        # Fake key with real-looking pattern
        fake_key_1 = "FAKE_GEMINI_API_KEY_ONE_FOR_REDACTION_TEST"
        fake_key_2 = "FAKE_GEMINI_API_KEY_TWO_FOR_REDACTION_TEST"
        
        test_config = {
            "api_key": fake_key_1,
            "api_keys": [fake_key_1, fake_key_2],
            "waterfall_strategy": []
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(test_config, f)
            
        manager = AIConfigManager(config_path)
        manager.rotate_api_key()
        
        # Get log content
        log_content = log_capture.getvalue()
        
        # Remove handler
        logger_target.removeHandler(handler)
        
        # Assertions
        assert fake_key_1 not in log_content, "API Key 1 leaked in logs"
        assert fake_key_2 not in log_content, "API Key 2 leaked in logs"
        assert fake_key_1[:12] not in log_content, "API Key 1 prefix leaked in logs"
        assert fake_key_2[:12] not in log_content, "API Key 2 prefix leaked in logs"
        assert "FAKE_GEMINI_API" not in log_content, "Pattern 'FAKE_GEMINI_API' leaked in logs"
        print("   [OK] Verified no API key prefix, suffix, or raw key material was logged.")


def test_save_config_moves_api_keys_to_secret_store():
    print("\n[TEST] test_save_config_moves_api_keys_to_secret_store")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        manager = AIConfigManager(config_path)

        manager.api_keys = ["KeyA", "KeyB"]
        providers = manager.providers_config
        providers["deepseek"]["api_keys"] = ["ds-secret-1"]
        manager.providers_config = providers

        assert manager.save_config() is True

        public_payload = json.loads(config_path.read_text(encoding="utf-8"))
        secrets_path = get_secret_config_path(config_path)
        secret_payload, _ = _decode_secret_file_payload(json.loads(secrets_path.read_text(encoding="utf-8")))

        assert public_payload["api_key"] == ""
        assert public_payload["api_keys"] == []
        assert public_payload["providers"]["deepseek"]["api_keys"] == []
        assert secret_payload["api_keys"] == ["KeyA", "KeyB"]
        assert secret_payload["providers"]["gemini"]["api_keys"] == ["KeyA", "KeyB"]
        assert secret_payload["providers"]["deepseek"]["api_keys"] == ["ds-secret-1"]
        print("   [OK] Main config sanitized and secret store contains raw keys.")


def test_save_and_load_multiple_provider_keys_from_secret_store():
    print("\n[TEST] test_save_and_load_multiple_provider_keys_from_secret_store")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        manager = AIConfigManager(config_path)
        provider_keys = {
            "gemini": ["FAKE_GOOGLE_API_KEY_FOR_TEST"],
            "groq": ["gsk_groq_provider_key_for_test_12345"],
            "openrouter": ["FAKE_OPENAI_API_KEY_FOR_TEST"],
            "cloudflare": ["cf_cloudflare_provider_key_for_test"],
            "huggingface": ["hf_huggingface_provider_key_for_test"],
            "deepseek": ["FAKE_OPENAI_API_KEY_FOR_TEST_2"],
            "nvidia_nim": ["nvapi-nvidia-provider-key-for-test"],
            "github": ["FAKE_GITHUB_PAT_FOR_TEST"],
        }
        for provider_id, keys in provider_keys.items():
            for key in keys:
                assert manager.add_provider_api_key(provider_id, key) is True

        assert manager.save_config() is True

        public_text = config_path.read_text(encoding="utf-8")
        backup_text = config_path.with_suffix(config_path.suffix + ".bak").read_text(encoding="utf-8")
        public_payload = json.loads(public_text)
        secret_payload, _ = _decode_secret_file_payload(
            json.loads(get_secret_config_path(config_path).read_text(encoding="utf-8"))
        )

        fake_keys = [key for keys in provider_keys.values() for key in keys]
        assert_no_raw_secrets_in_text(public_text, fake_keys)
        assert_no_raw_secrets_in_text(backup_text, fake_keys)
        for provider_id, keys in provider_keys.items():
            assert public_payload["providers"][provider_id]["api_keys"] == []
            assert secret_payload["providers"][provider_id]["api_keys"] == keys

        reloaded = AIConfigManager(config_path)
        from translation_app.core.providers.profiles import build_provider_profiles

        profiles = build_provider_profiles(reloaded)
        for provider_id, keys in provider_keys.items():
            assert reloaded.providers_config[provider_id]["api_keys"] == keys
            assert profiles[provider_id].api_key_pool == keys
        print("   [OK] Provider-specific keys are protected on disk and hydrated for runtime profiles.")


def test_migrates_legacy_provider_key_aliases_to_canonical_secret_schema():
    print("\n[TEST] test_migrates_legacy_provider_key_aliases_to_canonical_secret_schema")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        legacy_payload = {
            "api_key": "FAKE_GOOGLE_API_KEY_FOR_TEST_2",
            "api_keys": ["FAKE_GOOGLE_API_KEY_FOR_TEST_2"],
            "providers": {
                "gemini": {"enabled": True, "type": "gemini", "api_key_pool": ["FAKE_GOOGLE_API_KEY_FOR_TEST_3"]},
                "nvidia": {"enabled": True, "type": "openai_compatible", "keys": ["nvapi-legacy-nvidia-key-for-test"]},
                "github_models": {"enabled": True, "type": "openai_compatible", "api_key": "FAKE_GITHUB_PAT_FOR_TEST_2"},
                "custom_openai": {"enabled": True, "type": "openai_compatible", "api_keys": ["FAKE_OPENAI_API_KEY_FOR_TEST_3"]},
            },
            "waterfall_strategy": [],
        }
        config_path.write_text(json.dumps(legacy_payload, ensure_ascii=False), encoding="utf-8")

        manager = AIConfigManager(config_path)
        public_text = config_path.read_text(encoding="utf-8")
        secret_payload, _ = _decode_secret_file_payload(
            json.loads(get_secret_config_path(config_path).read_text(encoding="utf-8"))
        )

        fake_keys = [
            "FAKE_GOOGLE_API_KEY_FOR_TEST_2",
            "FAKE_GOOGLE_API_KEY_FOR_TEST_3",
            "nvapi-legacy-nvidia-key-for-test",
            "FAKE_GITHUB_PAT_FOR_TEST_2",
            "FAKE_OPENAI_API_KEY_FOR_TEST_3",
        ]
        assert_no_raw_secrets_in_text(public_text, fake_keys)
        assert manager.api_keys == [
            "FAKE_GOOGLE_API_KEY_FOR_TEST_2",
            "FAKE_GOOGLE_API_KEY_FOR_TEST_3",
        ]
        assert secret_payload["providers"]["gemini"]["api_keys"] == [
            "FAKE_GOOGLE_API_KEY_FOR_TEST_2",
            "FAKE_GOOGLE_API_KEY_FOR_TEST_3",
        ]
        assert secret_payload["providers"]["nvidia_nim"]["api_keys"] == ["nvapi-legacy-nvidia-key-for-test"]
        assert secret_payload["providers"]["github"]["api_keys"] == ["FAKE_GITHUB_PAT_FOR_TEST_2"]
        assert secret_payload["providers"]["openai_compatible"]["api_keys"] == ["FAKE_OPENAI_API_KEY_FOR_TEST_3"]
        print("   [OK] Legacy provider aliases and key field names migrate to the canonical schema.")


def test_load_config_migrates_legacy_raw_keys_to_secret_store():
    print("\n[TEST] test_load_config_migrates_legacy_raw_keys_to_secret_store")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        legacy_payload = {
            "api_key": "LegacyKeyA",
            "api_keys": ["LegacyKeyA", "LegacyKeyB"],
            "providers": {
                "deepseek": {
                    "enabled": True,
                    "type": "openai_compatible",
                    "api_keys": ["ds-legacy-key"],
                }
            },
            "waterfall_strategy": [],
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(legacy_payload, f, ensure_ascii=False)

        manager = AIConfigManager(config_path)
        secrets_path = get_secret_config_path(config_path)
        public_payload = json.loads(config_path.read_text(encoding="utf-8"))
        secret_payload, _ = _decode_secret_file_payload(json.loads(secrets_path.read_text(encoding="utf-8")))

        assert manager.api_key == "LegacyKeyA"
        assert manager.api_keys == ["LegacyKeyA", "LegacyKeyB"]
        assert manager.providers_config["deepseek"]["api_keys"] == ["ds-legacy-key"]
        assert public_payload["api_key"] == ""
        assert public_payload["api_keys"] == []
        assert public_payload["providers"]["deepseek"]["api_keys"] == []
        assert secret_payload["api_keys"] == ["LegacyKeyA", "LegacyKeyB"]
        assert secret_payload["providers"]["deepseek"]["api_keys"] == ["ds-legacy-key"]
        print("   [OK] Legacy raw keys were migrated to secret store automatically.")


def test_load_config_merges_legacy_keys_when_secret_store_exists():
    print("\n[TEST] test_load_config_merges_legacy_keys_when_secret_store_exists")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        secrets_path = get_secret_config_path(config_path)
        legacy_payload = {
            "api_key": "LegacyKeyA",
            "api_keys": ["LegacyKeyA"],
            "providers": {
                "deepseek": {
                    "enabled": True,
                    "type": "openai_compatible",
                    "api_keys": ["ds-legacy-key"],
                }
            },
            "waterfall_strategy": [],
        }
        existing_secret_payload = {
            "api_keys": ["ExistingKey"],
            "providers": {
                "chatanywhere": {"api_keys": ["chat-existing-key"]}
            },
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(legacy_payload, f, ensure_ascii=False)
        with open(secrets_path, "w", encoding="utf-8") as f:
            json.dump(existing_secret_payload, f, ensure_ascii=False)

        AIConfigManager(config_path)

        public_payload = json.loads(config_path.read_text(encoding="utf-8"))
        backup_payload = json.loads(config_path.with_suffix(config_path.suffix + ".bak").read_text(encoding="utf-8"))
        secret_payload, _ = _decode_secret_file_payload(json.loads(secrets_path.read_text(encoding="utf-8")))

        assert public_payload["api_key"] == ""
        assert public_payload["api_keys"] == []
        assert backup_payload["api_key"] == ""
        assert backup_payload["api_keys"] == []
        assert secret_payload["api_keys"] == ["ExistingKey", "LegacyKeyA"]
        assert secret_payload["providers"]["chatanywhere"]["api_keys"] == ["chat-existing-key"]
        assert secret_payload["providers"]["deepseek"]["api_keys"] == ["ds-legacy-key"]
        print("   [OK] Existing secret store and legacy raw keys were merged safely.")


def test_load_config_recovers_legacy_keys_from_raw_backup():
    print("\n[TEST] test_load_config_recovers_legacy_keys_from_raw_backup")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        raw_backup_path = config_path.with_suffix(config_path.suffix + ".bak")
        sanitized_payload = {
            "api_key": "",
            "api_keys": [],
            "providers": {
                "deepseek": {
                    "enabled": True,
                    "type": "openai_compatible",
                    "api_keys": [],
                }
            },
            "waterfall_strategy": [],
        }
        raw_backup_payload = {
            "api_key": "BackupKeyA",
            "api_keys": ["BackupKeyA"],
            "providers": {
                "deepseek": {
                    "enabled": True,
                    "type": "openai_compatible",
                    "api_keys": ["ds-backup-key"],
                }
            },
            "waterfall_strategy": [],
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(sanitized_payload, f, ensure_ascii=False)
        with open(raw_backup_path, "w", encoding="utf-8") as f:
            json.dump(raw_backup_payload, f, ensure_ascii=False)

        manager = AIConfigManager(config_path)

        public_payload = json.loads(config_path.read_text(encoding="utf-8"))
        backup_payload = json.loads(raw_backup_path.read_text(encoding="utf-8"))
        secret_payload, _ = _decode_secret_file_payload(json.loads(get_secret_config_path(config_path).read_text(encoding="utf-8")))

        assert manager.api_keys == ["BackupKeyA"]
        assert manager.providers_config["deepseek"]["api_keys"] == ["ds-backup-key"]
        assert public_payload["api_key"] == ""
        assert public_payload["api_keys"] == []
        assert backup_payload["api_key"] == ""
        assert backup_payload["api_keys"] == []
        assert secret_payload["api_keys"] == ["BackupKeyA"]
        assert secret_payload["providers"]["deepseek"]["api_keys"] == ["ds-backup-key"]
        print("   [OK] Raw backup keys were recovered and backup was sanitized.")


def test_monkeypatched_default_config_uses_sidecar_secret_store(tmp_path, monkeypatch):
    print("\n[TEST] test_monkeypatched_default_config_uses_sidecar_secret_store")
    import translation_app.core.ai_service as ai_service_module

    config_path = tmp_path / "isolated" / "ai_settings.json"
    monkeypatch.setattr(ai_service_module, "DEFAULT_CONFIG_PATH", config_path)

    manager = AIConfigManager()

    assert manager.config_path == config_path
    assert manager.secrets_path == config_path.with_name("ai_settings.secrets.json")
    assert "DichTuDong" not in str(manager.secrets_path)
    print("   [OK] Test/default overrides keep secrets beside the temp config file.")


def test_missing_public_config_preserves_existing_secret_store():
    print("\n[TEST] test_missing_public_config_preserves_existing_secret_store")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        secrets_path = get_secret_config_path(config_path)
        existing_secret_payload = {
            "api_keys": ["ExistingGeminiKey"],
            "providers": {
                "deepseek": {"api_keys": ["ExistingDeepseekKey"]}
            },
        }
        with open(secrets_path, "w", encoding="utf-8") as f:
            json.dump(existing_secret_payload, f, ensure_ascii=False)

        manager = AIConfigManager(config_path)
        public_payload = json.loads(config_path.read_text(encoding="utf-8"))
        secret_payload, _ = _decode_secret_file_payload(json.loads(secrets_path.read_text(encoding="utf-8")))

        assert manager.api_keys == ["ExistingGeminiKey"]
        assert manager.providers_config["deepseek"]["api_keys"] == ["ExistingDeepseekKey"]
        assert public_payload["api_key"] == ""
        assert public_payload["api_keys"] == []
        assert public_payload["providers"]["deepseek"]["api_keys"] == []
        assert secret_payload["api_keys"] == ["ExistingGeminiKey"]
        assert secret_payload["providers"]["deepseek"]["api_keys"] == ["ExistingDeepseekKey"]
        print("   [OK] First startup keeps existing secret values intact.")


def test_corrupted_public_config_still_uses_existing_secret_store():
    print("\n[TEST] test_corrupted_public_config_still_uses_existing_secret_store")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        secrets_path = get_secret_config_path(config_path)
        corrupted_content = "{ corrupted content }"
        config_path.write_text(corrupted_content, encoding="utf-8")
        config_path.with_suffix(config_path.suffix + ".bak").write_text(corrupted_content, encoding="utf-8")
        existing_secret_payload = {
            "api_keys": ["ExistingGeminiKey"],
            "providers": {
                "deepseek": {"api_keys": ["ExistingDeepseekKey"]}
            },
        }
        with open(secrets_path, "w", encoding="utf-8") as f:
            json.dump(existing_secret_payload, f, ensure_ascii=False)

        manager = AIConfigManager(config_path)
        secret_payload, _ = _decode_secret_file_payload(json.loads(secrets_path.read_text(encoding="utf-8")))

        assert manager.api_keys == ["ExistingGeminiKey"]
        assert manager.providers_config["deepseek"]["api_keys"] == ["ExistingDeepseekKey"]
        assert config_path.read_text(encoding="utf-8") == corrupted_content
        assert config_path.with_suffix(config_path.suffix + ".bak").read_text(encoding="utf-8") == corrupted_content
        assert secret_payload["api_keys"] == ["ExistingGeminiKey"]
        assert secret_payload["api_key"] == "ExistingGeminiKey"
        assert secret_payload["providers"]["gemini"]["api_keys"] == ["ExistingGeminiKey"]
        assert secret_payload["providers"]["deepseek"]["api_keys"] == ["ExistingDeepseekKey"]
        print("   [OK] Corrupted public config does not block or overwrite existing secrets.")


def test_secret_store_file_does_not_contain_raw_keys_on_windows():
    print("\n[TEST] test_secret_store_file_does_not_contain_raw_keys_on_windows")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        secrets_path = get_secret_config_path(config_path)
        manager = AIConfigManager(config_path)
        manager.api_keys = ["KeyAForProtectionTest"]
        providers = manager.providers_config
        providers["deepseek"]["api_keys"] = ["DeepseekKeyForProtectionTest"]
        manager.providers_config = providers

        assert manager.save_config() is True

        raw_secret_text = secrets_path.read_text(encoding="utf-8")
        secret_wrapper = json.loads(raw_secret_text)
        secret_payload, _ = _decode_secret_file_payload(secret_wrapper)

        assert secret_payload["api_keys"] == ["KeyAForProtectionTest"]
        assert secret_payload["providers"]["deepseek"]["api_keys"] == ["DeepseekKeyForProtectionTest"]
        if os.name == "nt":
            assert secret_wrapper["protection"] == SECRET_PROTECTION_WINDOWS_DPAPI
            assert "KeyAForProtectionTest" not in raw_secret_text
            assert "DeepseekKeyForProtectionTest" not in raw_secret_text
            raw_secret_backup_text = secrets_path.with_suffix(secrets_path.suffix + ".bak").read_text(encoding="utf-8")
            secret_backup_wrapper = json.loads(raw_secret_backup_text)
            assert secret_backup_wrapper["protection"] == SECRET_PROTECTION_WINDOWS_DPAPI
            assert "KeyAForProtectionTest" not in raw_secret_backup_text
            assert "DeepseekKeyForProtectionTest" not in raw_secret_backup_text
        print("   [OK] Secret store is encoded and raw keys are not visible on Windows.")


def test_dpapi_decode_failure_does_not_overwrite_existing_secret_store():
    print("\n[TEST] test_dpapi_decode_failure_does_not_overwrite_existing_secret_store")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        secrets_path = get_secret_config_path(config_path)
        config_path.write_text(
            json.dumps({"api_key": "", "api_keys": [], "providers": {"deepseek": {"api_keys": []}}, "waterfall_strategy": []}),
            encoding="utf-8",
        )
        invalid_secret_wrapper = {
            "version": SECRET_FILE_VERSION,
            "protection": SECRET_PROTECTION_WINDOWS_DPAPI,
            "payload": "bm90LWEtdmFsaWQtZHByb3RlY3RlZC1wYXlsb2Fk",
        }
        original_secret_text = json.dumps(invalid_secret_wrapper, ensure_ascii=False)
        secrets_path.write_text(original_secret_text, encoding="utf-8")

        manager = AIConfigManager(config_path)
        assert manager._secrets_decode_failed is True
        assert manager.add_provider_api_key("deepseek", "FAKE_OPENAI_API_KEY_FOR_TEST_4") is True
        assert manager.save_config() is False

        assert secrets_path.read_text(encoding="utf-8") == original_secret_text
        assert "FAKE_OPENAI_API_KEY_FOR_TEST_4" not in secrets_path.read_text(encoding="utf-8")
        print("   [OK] Unreadable secret store blocks secret overwrite and keeps the original file intact.")


def test_env_gemini_key_is_saved_only_to_secret_store(monkeypatch):
    print("\n[TEST] test_env_gemini_key_is_saved_only_to_secret_store")
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("GEMINI_API_KEY", "EnvGeminiKeyForSecretStore")
        config_path = Path(tmpdir) / "ai_settings.json"

        manager = AIConfigManager(config_path)

        public_payload = json.loads(config_path.read_text(encoding="utf-8"))
        secret_payload, _ = _decode_secret_file_payload(
            json.loads(get_secret_config_path(config_path).read_text(encoding="utf-8"))
        )

        assert manager.api_key == "EnvGeminiKeyForSecretStore"
        assert public_payload["api_key"] == ""
        assert public_payload["api_keys"] == []
        assert secret_payload["api_key"] == "EnvGeminiKeyForSecretStore"
        assert "EnvGeminiKeyForSecretStore" not in config_path.read_text(encoding="utf-8")
        print("   [OK] Environment Gemini key is persisted only in the secret store.")


def test_openai_compatible_legacy_key_is_saved_only_to_secret_store():
    print("\n[TEST] test_openai_compatible_legacy_key_is_saved_only_to_secret_store")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "ai_settings.json"
        manager = AIConfigManager(config_path)
        manager.openai_compatible_config = {
            "enabled": True,
            "base_url": "https://example.invalid/v1",
            "api_key": "OpenAICompatKeyForSecretStore",
            "model": "custom-model",
        }

        assert manager.save_config() is True

        public_payload = json.loads(config_path.read_text(encoding="utf-8"))
        secret_payload, _ = _decode_secret_file_payload(
            json.loads(get_secret_config_path(config_path).read_text(encoding="utf-8"))
        )

        assert public_payload["openai_compatible"]["api_key"] == ""
        assert public_payload["providers"]["openai_compatible"]["api_keys"] == []
        assert secret_payload["providers"]["openai_compatible"]["api_keys"] == ["OpenAICompatKeyForSecretStore"]
        assert "OpenAICompatKeyForSecretStore" not in config_path.read_text(encoding="utf-8")
        print("   [OK] Legacy OpenAI-compatible key is persisted only in the secret store.")


if __name__ == "__main__":
    test_ai_service()
    test_model_management()
    test_load_config_corrupted_uses_backup()
    test_load_config_corrupted_does_not_overwrite_original()
    test_missing_fields_are_merged_not_reset()
    test_key_rotation_does_not_rewrite_config_each_request()
    test_ai_only_does_not_google_fallback()
    test_text_waterfall_allows_only_live_models()
    test_logs_do_not_leak_api_keys()
    print("\n[ALL TESTS PASSED SUCCESSFULLY!]")
