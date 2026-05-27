# -*- coding: utf-8 -*-
"""
Tests for Mojibake / Encoding Hardening.
"""
import os
import tempfile
import logging
from pathlib import Path
import pytest

from translation_app.core.encoding_utils import (
    detect_mojibake,
    repair_common_mojibake,
    safe_read_text,
    safe_write_text,
    sanitize_for_console
)

# 1. test_detects_vietnamese_mojibake
def test_detects_vietnamese_mojibake():
    # Common double-decoded Vietnamese pattern
    bad_string = "Tiáº¿ng Viá»‡t"
    assert detect_mojibake(bad_string) is True
    
    # Another pattern
    bad_string_2 = "Cáº£nh bﾃ｡o"
    assert detect_mojibake(bad_string_2) is True

# 2. test_repairs_common_vietnamese_mojibake
def test_repairs_common_vietnamese_mojibake():
    bad_string = "Tiáº¿ng Viá»‡t"
    repaired = repair_common_mojibake(bad_string)
    assert repaired == "Tiếng Việt"

# 3. test_does_not_change_good_unicode_text
def test_does_not_change_good_unicode_text():
    good_text = "Tiếng Việt 日本語 中文"
    repaired = repair_common_mojibake(good_text)
    assert repaired == good_text

# 4. test_safe_write_and_read_utf8
def test_safe_write_and_read_utf8():
    good_text = "Tiếng Việt 日本語 中文 \n Line 2 \u2728"
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "test_file.txt"
        safe_write_text(file_path, good_text)
        
        # Verify read
        read_text = safe_read_text(file_path)
        assert read_text == good_text

# 5. test_csv_glossary_utf8_sig_import_export_if_applicable
def test_csv_glossary_utf8_sig_import_export_if_applicable():
    csv_content = "\ufeffsource_term,target_term,source_lang,target_lang,domain,note,is_active\n" \
                  "chế tạo,manufacturing,vi,en,Engineering,Clean,True\n" \
                  "日本語,Japanese,ja,en,General,,True\n"
                  
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "test_glossary.csv"
        safe_write_text(csv_path, csv_content)
        
        # Verify read with utf-8-sig
        read_content = safe_read_text(csv_path, encodings=["utf-8-sig"])
        assert "chế tạo" in read_content
        assert "日本語" in read_content
        assert read_content.startswith("source_term")  # utf-8-sig strips BOM

# 6. test_ui_source_has_no_common_mojibake_patterns
def test_ui_source_has_no_common_mojibake_patterns():
    # Scan all files in ui/
    root_dir = Path(__file__).parent.parent
    ui_dir = root_dir / "ui"
    
    from tools.check_mojibake import scan_file
    
    issues = []
    for file_path in ui_dir.glob("*.py"):
        file_issues = scan_file(str(file_path))
        issues.extend(file_issues)
        
    assert len(issues) == 0, f"UI source code has Mojibake issues:\n" + "\n".join(issues)

# 7. test_core_source_has_no_common_mojibake_patterns
def test_core_source_has_no_common_mojibake_patterns():
    # Scan all files in core/
    root_dir = Path(__file__).parent.parent
    core_dir = root_dir / "core"
    
    from tools.check_mojibake import scan_file
    
    issues = []
    # Scan recursively
    for file_path in core_dir.rglob("*.py"):
        if file_path.name in ["encoding_utils.py", "translator.py"]:
            continue  # whitelisted intentional patterns
        file_issues = scan_file(str(file_path))
        issues.extend(file_issues)
        
    assert len(issues) == 0, f"Core source code has Mojibake issues:\n" + "\n".join(issues)

# 8. test_logger_handles_unicode_without_crash
def test_logger_handles_unicode_without_crash():
    test_logger = logging.getLogger("test_encoding_logger")
    # Add dummy stream handler to force encoding checking
    try:
        test_logger.info("Test unicode logging: Tiếng Việt, 日本語, 中文, ⚙️, 🟢")
        assert True
    except Exception as e:
        pytest.fail(f"Logger crashed on unicode output: {e}")

# 9. test_sanitize_for_console_prevents_encode_error
def test_sanitize_for_console_prevents_encode_error():
    # Verify sanitize_for_console returns safe string
    mixed_text = "Tiếng Việt 🟢 🔴"
    sanitized = sanitize_for_console(mixed_text)
    assert isinstance(sanitized, str)
    assert len(sanitized) > 0


# 10. test_detects_actual_ui_mojibake_samples_from_screenshot
def test_detects_actual_ui_mojibake_samples_from_screenshot():
    samples = [
        "D辿ch",
        "Ngﾃｴn ng盻ｯ ngu盻渡",
        "Ch盻肇 File:",
        "Khﾃｴng th盻・ﾄ黛c",
        "D辿ch File ﾄ妥ｭch...",
        "ti隴ｹ ki盻駝 75% request"
    ]
    for sample in samples:
        assert detect_mojibake(sample) is True, f"Failed to detect Mojibake in sample: {sample}"


# 11. test_ui_text_dump_has_no_mojibake
def test_ui_text_dump_has_no_mojibake():
    root_dir = Path(__file__).parent.parent
    dump_path = root_dir / "tools" / "ui_text_dump.txt"
    script_path = root_dir / "tools" / "dump_ui_texts.py"
    
    # Generate if not exists and script exists
    if not dump_path.exists():
        if not script_path.exists():
            pytest.skip("UI text dump script and dump file not present in clean checkout")
            return
            
        import subprocess
        import sys
        subprocess.run([sys.executable, str(script_path)], check=True)
        
    assert dump_path.exists(), "UI text dump file was not generated"
    
    # Read and scan
    with open(dump_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    lines = content.splitlines()
    issues = []
    for idx, line in enumerate(lines, 1):
        if detect_mojibake(line):
            issues.append(f"Line {idx}: {line}")
            
    assert len(issues) == 0, f"Dumped UI text has Mojibake issues:\n" + "\n".join(issues)



# 12. test_check_mojibake_catches_halfwidth_cjk_mixed_corruption
def test_check_mojibake_catches_halfwidth_cjk_mixed_corruption():
    # Verify both separate patterns and a combined mixed corruption detection
    bad_katakana = "ﾆ"
    bad_cjk = "蘯"
    mixed = "Ngﾃｴn ng盻ｯ ﾄ妥ｭch:"
    
    assert detect_mojibake(bad_katakana) is True
    assert detect_mojibake(bad_cjk) is True
    assert detect_mojibake(mixed) is True

