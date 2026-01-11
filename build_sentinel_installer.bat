@echo off
REM Complete build script for PFR Sentinel
REM Builds executable and creates Windows installer
REM
REM Usage:
REM   build_sentinel_installer.bat

echo ========================================
echo   PFR Sentinel - Full Build
echo ========================================
echo.

echo Building: PySide6 Fluent UI
echo.

REM Step 0: Sync version.iss from version.py
echo [0/3] Syncing version from version.py...
python scripts\update_version.py
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Version sync failed!
    pause
    exit /b 1
)
echo.

REM Step 1: Build executable
echo [1/3] Building executable...
call build_sentinel.bat
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Executable build failed!
    pause
    exit /b 1
)

REM Step 2: Build installer
echo.
echo [2/3] Building installer (UPX disabled to avoid false positives)...

REM Check for Inno Setup
set ISCC_PATH="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC_PATH% (
    set ISCC_PATH="C:\Program Files\Inno Setup 6\ISCC.exe"
)

if not exist %ISCC_PATH% (
    echo.
    echo WARNING: Inno Setup not found!
    echo Please install Inno Setup 6 from: https://jrsoftware.org/isinfo.php
    echo.
    echo Executable was built successfully:
    echo   dist\PFRSentinel\PFRSentinel.exe
    pause
    exit /b 0
)

%ISCC_PATH% installer\PFRSentinel.iss
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Installer build failed!
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Full Build Completed!
echo ========================================
echo.
echo Installer location:
echo   releases\PFRSentinel_Setup.exe
echo.
echo ========================================
echo   Next: Upload to VirusTotal
echo ========================================
echo.
echo To scan for false positives and get results for GitHub:
echo   python scripts\upload_to_virustotal.py
echo.
echo Requires free API key from: https://www.virustotal.com/gui/join-us
echo Set via: set VIRUSTOTAL_API_KEY=your_key_here
echo.
pause
