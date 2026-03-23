"""
Auto-update service for translation application
"""
import os
import sys
import re
import shutil
import subprocess
import glob
from datetime import datetime
from tkinter import messagebox
from translation_app.config import config
from translation_app.utils.logger import logger

def get_current_version():
    """Lấy version từ biến nội bộ của chương trình"""
    try:
        from translation_app import __version__
        return __version__
    except Exception as e:
        logger.error(f"Error getting current version: {e}")
    return "1.0.0"



def parse_version(v_str):
    """Parse version string to tuple for comparison"""
    try:
        return tuple(map(int, v_str.split('.')))
    except Exception:
        return (0,)

def check_for_updates():
    """Kiểm tra bản cập nhật mới từ các folder mạng"""
    current_v_str = get_current_version()
    current_v = parse_version(current_v_str)
    
    logger.info(f"Checking for updates. Current version: {current_v_str}")
    
    latest_file = None
    latest_version = current_v
    latest_v_str = current_v_str

    for folder in config.update_folders:
        if not os.path.exists(folder):
            logger.warning(f"Update folder not accessible: {folder}")
            continue
            
        pattern = os.path.join(folder, config.update_file_pattern)
        files = glob.glob(pattern)
        
        for file_path in files:
            filename = os.path.basename(file_path)
            match = re.search(r'ver(\d+(\.\d+)*)', filename, re.IGNORECASE)
            if match:
                v_str = match.group(1)
                v = parse_version(v_str)
                if v > latest_version:
                    latest_version = v
                    latest_v_str = v_str
                    latest_file = file_path
    
    if latest_file:
        logger.info(f"New version found: {latest_v_str} at {latest_file}")
        return {
            'version': latest_v_str,
            'path': latest_file
        }
    
    logger.info("No updates found.")
    return None

def perform_update(update_info):
    """Thực hiện quá trình cập nhật"""
    if not update_info:
        return
        
    try:
        new_exe_path = update_info['path']
        new_version = update_info['version']
        
        ans = messagebox.askyesno(
            "Cập nhật phần mềm",
            f"Đã có phiên bản mới: {new_version}\n"
            f"Bạn có muốn cập nhật ngay không?\n\n"
            f"Lưu ý: Chương trình sẽ tự khởi động lại sau khi cập nhật."
        )
        
        if not ans:
            return

        # Prepare update script
        current_exe = sys.executable
        current_dir = os.path.dirname(current_exe)
        new_exe_name = os.path.basename(new_exe_path) # e.g. DichTuDong_ver7.exe
        target_exe_path = os.path.join(current_dir, new_exe_name)
        
        batch_file = os.path.join(current_dir, "do_update.bat")
        
        with open(batch_file, "w", encoding='utf-8') as f:
            f.write("@echo off\n")
            f.write("chcp 65001 >nul\n")
            f.write("echo Đang đợi chương trình đóng lại...\n")
            
            # Kill the CURRENT process
            current_exe_filename = os.path.basename(current_exe)
            f.write(f"taskkill /f /im \"{current_exe_filename}\" >nul 2>&1\n")
            f.write("timeout /t 3 /nobreak >nul\n")
            
            f.write(f"echo Đang cập nhật lên {new_exe_name}...\n")
            
            # Copy new file to current directory with its NEW name
            f.write(f"copy /y \"{new_exe_path}\" \"{target_exe_path}\"\n")
            
            # DELETE THE OLD FILE (if names are different)
            if target_exe_path.lower() != current_exe.lower():
                f.write(f"del /f /q \"{current_exe}\"\n")
            
            f.write("echo Cập nhật hoàn tất! Đang khởi động bản mới...\n")
            f.write("timeout /t 2 /nobreak >nul\n")
            
            # Clear environment
            f.write("set _MEIPASS=\n")
            f.write("set _MEIPASS2=\n")
            
            # Start the NEW exe
            f.write(f"start \"\" \"{target_exe_path}\"\n")
            f.write("del \"%~f0\" & exit\n")
            
        # Run batch and exit
        subprocess.Popen([batch_file], shell=True)
        sys.exit(0)

        
    except Exception as e:
        logger.error(f"Update failed: {e}", exc_info=True)
        messagebox.showerror("Lỗi cập nhật", f"Phát sinh lỗi khi cập nhật:\n{str(e)}")
