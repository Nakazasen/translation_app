@echo off
REM Batch script to run the translation application on Windows

echo ========================================
echo    TRANSLATION APPLICATION LAUNCHER
echo ========================================
echo.

REM Check where we are running from
set "IN_ROOT=0"
if exist "main.py" if exist "core" if exist "ui" set "IN_ROOT=1"

set "IN_PARENT=0"
if exist "translation_app" set "IN_PARENT=1"

if "%IN_ROOT%"=="1" (
    set "REQ_PATH=requirements.txt"
    set "RUN_CMD=python main.py"
    set "TEST_CMD=python test_import.py"
) else if "%IN_PARENT%"=="1" (
    set "REQ_PATH=translation_app\requirements.txt"
    set "RUN_CMD=python -m translation_app"
    set "TEST_CMD=python translation_app\test_import.py"
) else (
    echo ERROR: Translation application files not found!
    echo Please run this script from the project root directory or its parent directory.
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
pip install -r %REQ_PATH%
if errorlevel 1 (
    echo WARNING: Could not install dependencies automatically
    echo You may need to run: pip install -r %REQ_PATH%
    echo.
)

echo Testing imports...
%TEST_CMD%
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

%RUN_CMD%

echo.
echo Application closed.
pause
