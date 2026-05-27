# -*- coding: utf-8 -*-
"""
Encoding utilities for safe file I/O, Mojibake detection, and console handling.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

MOJIBAKE_PATTERNS = [
    "Ã‚", "Ãƒ", "Ã„", "Ã…", "Ã†", "Ã‡", "Ãˆ", "Ã‰", "ÃŠ", "Ã‹", "ÃŒ", "ÃŽ",
    "Ã‘", "Ã’", "Ã“", "Ã”", "Ã•", "Ã–", "Ã—", "Ã˜", "Ã™", "Ãœ",
    "ÃŸ", "Ã¡", "Ã¢", "Ã³", "Ã´", "Ãµ", "Ã¶", "Ã·", "Ã¸", "Ã¹", "Ãº", "Ã»", "Ã¼",
    "ã‚", "ãƒ", "ã€", "ã€€", "ã‚¬", "ã‚®", "ã‚°", "ã‚²", "ã‚", "ã‚¶", "ã‚¸", "ã‚º", "ã‚¼",
    "ã‚¾", "ãƒ€", "ãƒぢ", "ãƒ竚", "ãƒ・", "ãƒ・",
    "縺", "譁", "繧", "繝",
    "Tiáº", "Há»", "Nháº", "Cáº", "áº", "á»", "áº¿", "á»‡", "áº¡", "áº£", "áº¥", "áº§", "áº©",
    "áº«", "áº­", "áº¯", "áº±", "áº¹", "áº»", "áº½", "áº¿", "á»?", "á»ƒ", 
    "á»‡", "á»‰", "á»±", "á»»", "á»½",
    "Â ", "Â°", "Â©", "Â®",
    "D辿", "Ngﾃ", "Khﾃ", "ﾆ", "ｷ", "蘯", "黛", "盻", "ﾄ", "辿", "ﾃ", "窶", "ﾜ"
]

def detect_mojibake(text: str) -> bool:
    """
    Detect if a string contains common Mojibake/corruption patterns.
    """
    if not text:
        return False
    
    # Check for replacement character
    if "\uFFFD" in text:
        return True
        
    # Check for matched patterns
    for pattern in MOJIBAKE_PATTERNS:
        if pattern in text:
            return True
            
    return False

def repair_common_mojibake(text: str) -> str:
    """
    Repair common CP1252/Latin-1 double-decoded UTF-8 string corruptions.
    """
    if not text or not detect_mojibake(text):
        return text

    # Try CP1252 to UTF-8
    try:
        candidate = text.encode("cp1252").decode("utf-8")
        if not detect_mojibake(candidate):
            return candidate
    except Exception:
        pass

    # Try Latin-1 to UTF-8
    try:
        candidate = text.encode("latin-1").decode("utf-8")
        if not detect_mojibake(candidate):
            return candidate
    except Exception:
        pass

    return text

def safe_read_text(path: str | Path, encodings: Optional[List[str]] = None) -> str:
    """
    Safely read text file using multiple encodings with graceful fallbacks.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if encodings is None:
        encodings = ["utf-8-sig", "utf-8", "cp932", "shift_jis", "cp1252"]

    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc) as f:
                content = f.read()
            # If successfully read without issues, return it
            return content
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.warning(f"Error reading {file_path} with {enc}: {e}")
            continue

    # Fallback to UTF-8 with errors='replace' to avoid throwing an exception
    logger.warning(f"Fallback to UTF-8 with errors='replace' for file: {file_path.name}")
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Critical failure reading file: {file_path.name}: {e}")
        return ""

def safe_write_text(path: str | Path, text: str) -> None:
    """
    Safely write text to file in UTF-8 format, ensuring directory exists.
    """
    file_path = Path(path)
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        # Use standard newline='\n' for consistent files
        with open(file_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text or "")
    except Exception as e:
        logger.error(f"Failed to write text file {file_path.name}: {e}")
        raise

def sanitize_for_console(text: str) -> str:
    """
    Sanitize text to be safe for console printing under different terminal encodings.
    """
    if not text:
        return ""
    encoding = sys.stdout.encoding or 'ascii'
    try:
        # Check if text is encodable in stdout encoding
        text.encode(encoding)
        return text
    except UnicodeEncodeError:
        # Fallback to ascii representation or replacement
        return text.encode(encoding, errors='replace').decode(encoding)
