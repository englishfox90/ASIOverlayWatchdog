@echo off
REM Camera Settings Reset Script Launcher
REM Runs fix_cameras.py with proper Python environment

echo ================================================================
echo PFR Sentinel - Camera Settings Reset
echo ================================================================
echo.

REM Check if virtual environment exists
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
    echo.
) else (
    echo Warning: Virtual environment not found. Using system Python.
    echo.
)

REM Run the fix script
python fix_cameras.py
set EXIT_CODE=%ERRORLEVEL%

echo.
echo Press any key to exit...
pause >nul

exit /b %EXIT_CODE%
