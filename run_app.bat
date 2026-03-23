@echo off
REM Batch script to run the translation application on Windows

echo ========================================
echo    TRANSLATION APPLICATION LAUNCHER
echo ========================================
echo.

REM Check if we're in the right directory
if not exist "translation_app" (
    echo ERROR: translation_app directory not found!
    echo Please run this script from the parent directory of translation_app
    pause
    exit /b 1
)

echo Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

echo Installing dependencies...
pip install -r translation_app\requirements.txt
if errorlevel 1 (
    echo WARNING: Could not install dependencies automatically
    echo You may need to run: pip install -r translation_app\requirements.txt
    echo.
)

echo Testing imports...
python translation_app\test_import.py
if errorlevel 1 (
    echo ERROR: Import test failed!
    echo Please check the error messages above.
    pause
    exit /b 1
)

echo.
echo ========================================
echo Starting Translation Application...
echo ========================================
echo.
echo Close this window or press Ctrl+C to stop the application
echo.

python -m translation_app

echo.
echo Application closed.
pause
