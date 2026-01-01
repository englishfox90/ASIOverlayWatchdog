@echo off
echo Starting PFR Sentinel (Modern UI)...
cd /d "%~dp0"

REM Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Run the PySide6 UI
python main_pyside.py

REM Keep window open on error
if errorlevel 1 pause
