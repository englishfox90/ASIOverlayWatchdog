@echo off
setlocal enabledelayedexpansion
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
echo [0/4] Syncing version from version.py...
python scripts\update_version.py
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Version sync failed!
    pause
    exit /b 1
)
echo.

REM Step 1: Build executable
echo [1/4] Building executable...
set BUILD_FROM_INSTALLER=1
REM Delete the previous exe first: the existence check below is the only guard
REM that the build actually ran, and a stale exe silently satisfies it. That
REM shipped a 3.7.3 binary inside an installer named 3.7.4.
if exist "dist\PFRSentinel\PFRSentinel.exe" del /q "dist\PFRSentinel\PFRSentinel.exe"
REM %~dp0 (this script's own folder), not a bare name: cmd does not search the
REM current directory for executables when NoDefaultCurrentDirectoryInExePath
REM is set, so `call build_sentinel.bat` fails with "not recognized" there.
call "%~dp0build_sentinel.bat"
if not exist "dist\PFRSentinel\PFRSentinel.exe" (
    echo ERROR: Executable build failed!
    pause
    exit /b 1
)

REM Step 2: Build installer
echo.
echo [2/4] Building installer (UPX disabled to avoid false positives)...

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

REM Clean old installer files to avoid stale glob matches
if exist "installer\dist\*.exe" (
    echo Cleaning old installer files...
    del /q "installer\dist\*.exe"
)

%ISCC_PATH% installer\PFRSentinel.iss
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Installer build failed!
    pause
    exit /b 1
)

REM Step 3: Sign installer
echo.
echo [3/4] Signing installer...

REM Auto-connect SimplySign if OTP URI is configured
if defined CERTUM_OTP_URI (
    echo Connecting to SimplySign...
    powershell -ExecutionPolicy Bypass -File "%~dp0scripts\Connect-SimplySign.ps1" -SkipIfConnected
)

REM Set signtool path
set SIGNTOOL="C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe"

REM Check for certificate thumbprint in environment or use default
if not defined CODE_SIGNING_THUMBPRINT (
    set CODE_SIGNING_THUMBPRINT=B5E267FE814CD41B883876712CA326C288FB3492
)

REM Find the installer file (has version in name)
for %%f in (installer\dist\*.exe) do set INSTALLER_FILE=%%f

if exist %SIGNTOOL% (
    echo Using certificate: %CODE_SIGNING_THUMBPRINT%
    echo NOTE: Approve signing request in SimplySign mobile app...
    %SIGNTOOL% sign /sha1 %CODE_SIGNING_THUMBPRINT% /tr http://time.certum.pl /td SHA256 /fd SHA256 /d "PFR Sentinel Setup" "%INSTALLER_FILE%"
    if !ERRORLEVEL! EQU 0 (
        echo Installer signed successfully!
    ) else (
        echo WARNING: Signing failed, continuing with unsigned installer
    )
) else (
    echo WARNING: signtool.exe not found, skipping code signing
    echo Install Windows SDK to enable signing
)

echo.
echo ========================================
echo   Full Build Completed!
echo ========================================
echo.
echo Installer location:
echo   %INSTALLER_FILE%
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
