import sys
import os
import logging

# Add current directory to path so we can import modules
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from translation_app.core.translator import TranslationService
from translation_app.core.file_handlers.powerpoint_handler import PowerPointHandler
from translation_app.utils.logger import setup_logging

def main():
    # Force UTF-8 for stdout to avoid cp932 errors with emojis
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')

    input_file = r"D:\VINH\VINH\Nghiep vu co 3\60. AMS\MOMデータ連携説明_20251220.pptx"
    output_file = input_file.replace(".pptx", "_translated_vn.pptx")
    
    print(f"Input: {input_file}")
    print(f"Output: {output_file}")
    
    if not os.path.exists(input_file):
        print(f"Error: Input file not found: {input_file}")
        return

    # Initialize Service
    # reduce max_workers to 1 to be gentle 
    service = TranslationService(max_workers=1)
    
    # Switch back to AI as requested by user
    service.set_strategy("gemini ai -> google translate")
    
    handler = PowerPointHandler(service)
    
    print("Starting translation... This may take a few minutes...")
    try:
        stats = handler.translate(input_file, output_file, 'ja', 'vi')
        print("-" * 50)
        print("Translation Completed Successfully!")
        print(f"Output saved to: {output_file}")
        print("Statistics:", stats)
        print("-" * 50)
    except Exception as e:
        print(f"Error during translation: {e}")
        import traceback
        traceback.print_exc()
    finally:
        service.shutdown()

if __name__ == "__main__":
    main()
