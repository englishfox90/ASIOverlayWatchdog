@echo off
REM Emergency Camera SDK Reset Script Launcher

echo ================================================================
echo PFR Sentinel - Emergency Camera SDK Reset
echo ================================================================
echo.
echo This script will reset ALL ZWO cameras to factory defaults.
echo Use this to fix SDK contamination issues.
echo.
echo CLOSE ALL CAMERA APPLICATIONS FIRST!
echo.
pause

REM Check if virtual environment exists
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
    echo.
) else (
    echo Warning: Virtual environment not found. Using system Python.
    echo.
)

REM Run the reset script
python reset_camera_sdk.py
set EXIT_CODE=%ERRORLEVEL%

echo.
echo Press any key to exit...
pause >nul

exit /b %EXIT_CODE%
