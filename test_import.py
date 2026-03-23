#!/usr/bin/env python3
"""
Test script to verify imports work correctly
"""

import sys
import os

# For testing, setup sys.path correctly
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

def test_imports():
    """Test all imports"""
    try:
        print("Testing imports...")

        # Test basic imports first
        try:
            import tkinter
            import tkinter.ttk as ttk
            print("✓ Tkinter imports successful")
        except ImportError:
            print("⚠️ Tkinter not available (expected in headless environment)")

        # Test config import
        try:
            from translation_app.config import config
            print("✓ Config import successful")
        except ImportError as e:
            print(f"❌ Config import failed: {e}")
            return False

        # Test logger import
        try:
            from translation_app.utils.logger import setup_logging, logger
            print("✓ Logger import successful")
        except ImportError as e:
            print(f"❌ Logger import failed: {e}")
            return False

        # Test error handler import
        try:
            from translation_app.utils.error_handler import TranslationError
            print("✓ Error handler import successful")
        except ImportError as e:
            print(f"❌ Error handler import failed: {e}")
            return False

        # Test validators import
        try:
            from translation_app.utils.validators import FileValidator
            print("✓ Validators import successful")
        except ImportError as e:
            print(f"❌ Validators import failed: {e}")
            return False

        # Test translator import
        try:
            from translation_app.core.translator import TranslationService
            print("✓ Translator import successful")
        except ImportError as e:
            print(f"❌ Translator import failed: {e}")
            return False

        # Test OCR handler import
        try:
            from translation_app.core.ocr_handler import get_ocr_handler
            print("✓ OCR handler import successful")
        except ImportError as e:
            print(f"❌ OCR handler import failed: {e}")
            return False

        # Test file handlers import
        try:
            from translation_app.core.file_handlers.excel_handler import ExcelHandler
            from translation_app.core.file_handlers.word_handler import WordHandler
            from translation_app.core.file_handlers.powerpoint_handler import PowerPointHandler
            from translation_app.core.file_handlers.pdf_handler import PDFHandler
            from translation_app.core.file_handlers.text_handler import TextHandler
            print("✓ File handlers import successful")
        except ImportError as e:
            print(f"❌ File handlers import failed: {e}")
            return False

        # Test email handler import
        try:
            from translation_app.core.email_handler import EmailHandler
            print("✓ Email handler import successful")
        except ImportError as e:
            print(f"❌ Email handler import failed: {e}")
            return False

        # Test UI imports (skip MainWindow as it may open GUI)
        try:
            from translation_app.ui.theme import setup_theme
            from translation_app.ui.components import create_styled_button
            print("✓ UI components import successful")
        except ImportError as e:
            print(f"❌ UI components import failed: {e}")
            return False

        print("\n🎉 All imports successful! Application should work.")
        return True

    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    success = test_imports()
    if not success:
        sys.exit(1)
    print("\n✅ Ready to run: python main.py")
