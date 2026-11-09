@echo off
setlocal
cd /d "%~dp0"

echo ============================================================================
echo   AUTONOMOUS QC ^& PROJECT AUDIT INTELLIGENCE PLATFORM (Universal Launcher)
echo ============================================================================

if exist "QC_Intelligence_Platform.exe" (
    echo [1/1] Launching Standalone Executable QC_Intelligence_Platform.exe...
    "QC_Intelligence_Platform.exe" %*
    exit /b %ERRORLEVEL%
)

echo [1/2] Checking Python environment...
if not exist ".venv\Scripts\python.exe" (
    echo Creating local virtual environment ^(.venv^)...
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
)

echo [2/2] Starting QC Intelligence Platform...
".venv\Scripts\python.exe" desktop_launcher.py %*

