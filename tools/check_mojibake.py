#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Mojibake scanner tool to identify encoding corruptions.
"""
import os
import sys

MOJIBAKE_PATTERNS = [
    "Ã‚", "Ãƒ", "Ã„", "Ã…", "Ã†", "Ã‡", "Ãˆ", "Ã‰", "ÃŠ", "Ã‹", "ÃŒ", "ÃŽ",
    "Ã‘", "Ã’", "Ã“", "Ã”", "Ã•", "Ã–", "Ã—", "Ã˜", "Ã™", "Ãœ",
    "ÃŸ", "Ã¡", "Ã¢", "Ã³", "Ã´", "Ãµ", "Ã¶", "Ã·", "Ã¸", "Ã¹", "Ãº", "Ã»", "Ã¼",
    "ã‚", "ãƒ", "ã€", "ã€€", "ã‚¬", "ã‚®", "ã‚°", "ã‚²", "ã‚", "ã‚¶", "ã‚¸", "ã‚º", "ã‚¼",
    "ã‚¾", "ãƒ€", "ãƒぢ", "ãƒ竚", "ãƒ・", "ãƒ・", "ãƒ・", "ãƒ・", "ãƒ・", "ãƒ・",
    "縺", "譁", "繧", "繝",
    "Tiáº", "Há»", "Nháº", "Cáº", "áº", "á»", "áº¿", "á»‡", "áº¡", "áº£", "áº¥", "áº§", "áº©",
    "áº«", "áº­", "áº¯", "áº±", "áº¹", "áº»", "áº½", "áº¿", "á»?", "á»ƒ", 
    "á»‡", "á»‰", "á»±", "á»»", "á»½",
    "Â ", "Â°", "Â©", "Â®",
    "D辿", "Ngﾃ", "Khﾃ", "ﾆ", "ｷ", "蘯", "黛", "盻", "ﾄ", "辿", "ﾃ", "窶", "ﾜ"
]

# Files to ignore/whitelist from scan (e.g. self-checking encoding test files containing intentional patterns)
WHITELIST_FILES = {
    "check_mojibake.py",
    "test_encoding_utils.py",
    "encoding_utils.py",
    "translator.py"
}

def scan_file(file_path):
    issues = []
    # Verify file can be read as UTF-8
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError as e:
        issues.append(f"UnicodeDecodeError: Could not decode file as UTF-8: {e}")
        return issues
    except Exception as e:
        issues.append(f"FileReadError: Failed to read file: {e}")
        return issues

    # Scan for Mojibake patterns
    basename = os.path.basename(file_path)
    if basename in WHITELIST_FILES:
        return issues

    lines = content.splitlines()
    for idx, line in enumerate(lines, 1):
        for pattern in MOJIBAKE_PATTERNS:
            if pattern in line:
                issues.append(f"Line {idx}: Found Mojibake pattern '{pattern}' in line: {line.strip()[:100]}")
                break # Avoid duplicate reports per line

    return issues

def safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        # Fallback to ascii representation or safe characters
        print(msg.encode(sys.stdout.encoding or 'ascii', errors='replace').decode(sys.stdout.encoding or 'ascii'))

def main():
    root_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    target_dirs = ["core", "ui", "tests"]
    
    total_files = 0
    total_issues = 0
    
    safe_print("=" * 60)
    safe_print("[SCAN] RUNNING MOJIBAKE SCANNER...")
    safe_print("=" * 60)

    for target in target_dirs:
        dir_path = os.path.join(root_dir, target)
        if not os.path.exists(dir_path):
            continue
            
        for root, _, files in os.walk(dir_path):
            for file in files:
                if not file.endswith((".py", ".md", ".txt", ".json", ".csv", ".yml", ".yaml")):
                    continue
                    
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, root_dir)
                
                total_files += 1
                issues = scan_file(file_path)
                if issues:
                    total_issues += len(issues)
                    safe_print(f"\n[FAIL] {rel_path} has {len(issues)} encoding issue(s):")
                    for issue in issues:
                        safe_print(f"   - {issue}")
                        
    safe_print("\n" + "=" * 60)
    safe_print(f"[SUMMARY] Scanned {total_files} files. Found {total_issues} issues.")
    safe_print("=" * 60)
    
    if total_issues > 0:
        sys.exit(1)
    else:
        safe_print("[OK] No Mojibake detected! Repository is clean and robust.")
        sys.exit(0)

if __name__ == "__main__":
    main()
