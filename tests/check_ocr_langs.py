import pytesseract
import os
import sys

# Add the project's parent directory to sys.path
sys.path.insert(0, r'C:\ProgramData\Sandbox')

try:
    from translation_app.config import config
    
    # Setup Tesseract path manually for this check
    tesseract_found = False
    for path in config.tesseract_paths:
        if os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            tesseract_found = True
            break
            
    if tesseract_found:
        print(f"Available languages: {pytesseract.get_languages()}")
    else:
        print("Tesseract not found in configured paths.")
except Exception as e:
    print(f"Error: {e}")
