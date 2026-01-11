@echo off
REM Build script for PFR Sentinel executable
REM Creates a Windows executable using PyInstaller
REM
REM IMPORTANT: For production releases, set DEV_MODE_AVAILABLE = False in services\dev_mode_config.py
REM
REM Usage:
REM   build_sentinel.bat

echo ========================================
echo   PFR Sentinel - Build Executable
echo ========================================
echo.

set SPEC_FILE=PFRSentinel.spec

echo Building: PySide6 Fluent UI
echo Spec file: %SPEC_FILE%
echo.

REM Activate virtual environment if it exists
if exist venv\Scripts\activate.bat (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo WARNING: Virtual environment not found
    echo Continuing with system Python...
)

echo.
echo Cleaning old build artifacts...
if exist build rmdir /s /q build
if exist dist\PFRSentinel rmdir /s /q dist\PFRSentinel

echo.
echo Building executable with PyInstaller...
venv\Scripts\python.exe -m PyInstaller %SPEC_FILE%

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Build failed!
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Build completed successfully!
echo ========================================
echo.
echo Executable location:
echo   dist\PFRSentinel\PFRSentinel.exe
echo.
echo ========================================
echo   REMINDER: Production Build Checklist
echo ========================================
echo.
echo Before releasing, verify:
echo   1. services\dev_mode_config.py has DEV_MODE_AVAILABLE = False
echo   2. Test executable doesn't create raw_debug files
echo   3. Test executable doesn't show Developer Mode section in UI
echo.
echo You can now run:
echo   dist\PFRSentinel\PFRSentinel.exe
echo.
echo Or build the installer with:
echo   build_sentinel_installer.bat
echo.

pause
