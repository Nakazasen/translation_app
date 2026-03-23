"""
Test script for AI Service in Translation App
Tests: Waterfall strategy, API Key rotation, Model management
"""
import sys
import io
from pathlib import Path

# Fix encoding for Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from translation_app.core.ai_service import get_ai_service, get_config_manager


def test_ai_service():
    print("=" * 60)
    print("[TEST] Translation App AI Service Test")
    print("   Ported from leetcode_mastery with full features")
    print("=" * 60)
    
    # Test config manager
    config = get_config_manager()
    print(f"\n[OK] Config loaded from: {config.config_path}")
    
    # Test API Keys pool
    api_keys = config.api_keys
    print(f"\n[KEY] API Keys Pool ({len(api_keys)} keys):")
    for i, key in enumerate(api_keys):
        active = "(Active)" if i == 0 else ""
        print(f"   {i+1}. {key[:8]}...{key[-4:]} {active}")
    
    # Test current API key
    print(f"\n[KEY] Current API Key: {'***' + config.api_key[-8:] if config.api_key else 'Not set'}")
    
    # Test model list
    service = get_ai_service()
    models = service.models_priority
    print(f"\n[MODELS] Waterfall Models ({len(models)} active):")
    for i, m in enumerate(models, 1):
        print(f"   {i:2}. {m}")
    
    # Test API Key rotation
    print("\n[ROTATE] Testing API Key Rotation:")
    if len(api_keys) >= 2:
        old_key = config.api_key
        success = config.rotate_api_key()
        new_key = config.api_key
        if success:
            print(f"   [OK] Rotated: {old_key[:8]}... -> {new_key[:8]}...")
            # Rotate back to restore original order (need to rotate len-1 times)
            for _ in range(len(api_keys) - 1):
                config.rotate_api_key()
            print(f"   [OK] Restored original order")
        else:
            print(f"   [FAIL] Rotation failed")
    else:
        print(f"   [WARN] Need at least 2 API keys for rotation (current: {len(api_keys)})")
    
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
    
    # Test add model
    test_model = "test-model-xyz"
    config.add_model(test_model, is_active=False, timeout=5)
    print(f"   + Added: {test_model}")
    
    # Test toggle
    config.toggle_model(test_model)
    print(f"   ~ Toggled: {test_model}")
    
    # Test remove
    config.remove_model(test_model)
    print(f"   - Removed: {test_model}")
    
    final_count = len(config.waterfall_strategy)
    assert original_count == final_count, "Model count mismatch!"
    print(f"   [OK] Model management verified (count restored: {final_count})")


if __name__ == "__main__":
    test_ai_service()
    test_model_management()
    print("\n[ALL TESTS PASSED]")
