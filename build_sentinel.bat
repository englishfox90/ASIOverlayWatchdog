@echo off
REM Build script for PFR Sentinel executable
REM Creates a Windows executable using PyInstaller
REM
REM Usage:
REM   build_sentinel.bat          # Build new PySide6 UI (default)
REM   build_sentinel.bat --legacy # Build old Tkinter UI

echo ========================================
echo   PFR Sentinel - Build Executable
echo ========================================
echo.

REM Check for UI flag
set UI_TYPE=pyside
set SPEC_FILE=PFRSentinel_PySide.spec
set UI_NAME=PySide6 (Modern Fluent UI)

if /i "%1"=="--legacy" (
    set UI_TYPE=tkinter
    set SPEC_FILE=PFRSentinel.spec
    set UI_NAME=Tkinter (Legacy UI)
)

echo Building: %UI_NAME%
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
echo UI Version: %UI_NAME%
echo Executable location:
echo   dist\PFRSentinel\PFRSentinel.exe
echo.
echo You can now run:
echo   dist\PFRSentinel\PFRSentinel.exe
echo.
echo Or build the installer with:
echo   build_sentinel_installer.bat
echo.

pause
