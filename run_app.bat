@echo off
setlocal EnableDelayedExpansion

REM ========================================================
REM Translation Application Launcher for Windows
REM ========================================================

cd /d "%~dp0"
set "APP_DIR=%~dp0"

echo ========================================
echo    TRANSLATION APPLICATION LAUNCHER
echo ========================================
echo.

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

for %%I in ("%APP_DIR%..") do set "PARENT_DIR=%%~fI"
set "PYTHONPATH=%PARENT_DIR%;%PYTHONPATH%"

echo [1/3] Detecting Python environment...
set "PYTHON_EXE="

if exist "%APP_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%APP_DIR%.venv\Scripts\python.exe"
    echo   -> Found Virtual Environment: .venv
    goto :PYTHON_FOUND
)

if exist "%PARENT_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%PARENT_DIR%\.venv\Scripts\python.exe"
    echo   -> Found Virtual Environment: ..\.venv
    goto :PYTHON_FOUND
)

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py -3"
    echo   -> Found Windows Python Launcher (py -3)
    goto :PYTHON_FOUND
)

python -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=python"
    echo   -> Found System Python
    goto :PYTHON_FOUND
)

echo ERROR: Valid Python interpreter or virtual environment not found!
echo Please install Python 3.8+ or configure .venv.
pause
exit /b 1

:PYTHON_FOUND
echo.
echo [2/3] Verifying dependencies and modules...
if exist "%APP_DIR%requirements.txt" (
    echo   -> Checking requirements...
    %PYTHON_EXE% -m pip install -r "%APP_DIR%requirements.txt" --quiet
    if errorlevel 1 (
        echo   [Warning] Could not update pip packages automatically. Continuing...
    )
)

if exist "%APP_DIR%test_import.py" (
    echo   -> Running import tests...
    %PYTHON_EXE% "%APP_DIR%test_import.py"
    if errorlevel 1 (
        echo.
        echo ERROR: Import test failed! Please check messages above.
        pause
        exit /b 1
    )
)

echo.
echo ========================================
echo [3/3] Launching Translation Application...
echo ========================================
echo Close this window or press Ctrl+C to stop the application.
echo.

if exist "%APP_DIR%main.py" (
    %PYTHON_EXE% "%APP_DIR%main.py"
) else (
    %PYTHON_EXE% -m translation_app
)

echo.
echo Application closed.
pause
