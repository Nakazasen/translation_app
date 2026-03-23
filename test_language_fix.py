#!/usr/bin/env python3
"""
Test script to verify Chinese language code fix
"""

import sys
import os

# Setup imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from translation_app.core.translator import TranslationService
from translation_app.utils.logger import setup_logging, logger

def test_chinese_translation():
    """Test translation from Japanese to Chinese"""
    try:
        setup_logging()
        service = TranslationService()

        # Test Japanese to Chinese (should work now)
        result = service.translate_text("こんにちは", "ja", "zh-CN")
        print(f"✅ Japanese to Chinese Simplified: '{result}'")

        # Test generic Chinese code (zh -> zh-CN)
        result_generic = service.translate_text("こんにちは", "ja", "zh")
        print(f"✅ Japanese to generic Chinese (zh): '{result_generic}'")

        # Test backward compatibility
        result2 = service.translate_text("こんにちは", "ja", "zh-cn")
        print(f"✅ Backward compatibility (zh-cn): '{result2}'")

        # Test Traditional Chinese
        result3 = service.translate_text("こんにちは", "ja", "zh-TW")
        print(f"✅ Japanese to Traditional Chinese: '{result3}'")

        print("\n🎉 All Chinese language tests passed!")
        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    success = test_chinese_translation()
    if not success:
        sys.exit(1)
