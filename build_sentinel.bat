@echo off
setlocal enabledelayedexpansion
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

REM ========================================
REM   NINA plugin (C#) - staged for bundling
REM ========================================
REM services\nina_plugin_install.py expects the DLL at
REM   <app root>\nina_plugin\PFRSentinel.NINA.dll
REM (sys._MEIPASS when frozen, repo root from source). PFRSentinel.spec picks it
REM up from there if it exists. The .NET SDK is NOT a hard build requirement:
REM without it we still produce a working app, minus the one-click plugin install.
echo.
echo Building NINA plugin...

set NINA_PLUGIN_PROJ=nina-plugin\PFRSentinel.NINA\PFRSentinel.NINA.csproj
set NINA_PLUGIN_DLL=nina-plugin\PFRSentinel.NINA\bin\Release\net8.0-windows\PFRSentinel.NINA.dll
set NINA_PLUGIN_STAGE=nina_plugin

where dotnet >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo WARNING: 'dotnet' not found - skipping the NINA plugin build.
    echo          Install with: winget install Microsoft.DotNet.SDK.8
    if exist "%NINA_PLUGIN_STAGE%\PFRSentinel.NINA.dll" (
        echo WARNING: reusing the previously staged DLL - it may be STALE.
    ) else (
        echo          This build will NOT include the NINA plugin; the in-app
        echo          install button will report the bundle as missing.
    )
    goto :nina_plugin_done
)

if not exist "%NINA_PLUGIN_PROJ%" (
    echo WARNING: %NINA_PLUGIN_PROJ% not found - skipping the NINA plugin build.
    goto :nina_plugin_done
)

REM The project's PostBuild target copies the DLL into
REM %LOCALAPPDATA%\NINA\Plugins\3.0.0\... and deliberately FAILS when NINA holds
REM the file open. That is the right behaviour for plugin development and the
REM wrong one for packaging, so point LOCALAPPDATA at a throwaway folder for this
REM build - a developer with NINA open can still cut an installer.
set NINA_PLUGIN_DEPLOY_STUB=%TEMP%\PFRSentinel-nina-build
if not exist "%NINA_PLUGIN_DEPLOY_STUB%" mkdir "%NINA_PLUGIN_DEPLOY_STUB%"

dotnet build "%NINA_PLUGIN_PROJ%" -c Release --nologo -p:LOCALAPPDATA="%NINA_PLUGIN_DEPLOY_STUB%"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: NINA plugin build failed!
    echo The .NET SDK is present, so this is a real build error - not a missing toolchain.
    if not defined BUILD_FROM_INSTALLER pause
    exit /b 1
)

if not exist "%NINA_PLUGIN_DLL%" (
    echo.
    echo ERROR: NINA plugin build reported success but %NINA_PLUGIN_DLL% is missing!
    if not defined BUILD_FROM_INSTALLER pause
    exit /b 1
)

if not exist "%NINA_PLUGIN_STAGE%" mkdir "%NINA_PLUGIN_STAGE%"
copy /y "%NINA_PLUGIN_DLL%" "%NINA_PLUGIN_STAGE%\PFRSentinel.NINA.dll" >nul
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Could not stage the NINA plugin DLL to %NINA_PLUGIN_STAGE%\
    if not defined BUILD_FROM_INSTALLER pause
    exit /b 1
)
echo NINA plugin staged: %NINA_PLUGIN_STAGE%\PFRSentinel.NINA.dll

:nina_plugin_done

echo.
echo Building executable with PyInstaller...
venv\Scripts\python.exe -m PyInstaller %SPEC_FILE%

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Build failed!
    pause
    exit /b 1
)

REM Step 2: Sign executable (if certificate available)
echo.
echo Signing executable...

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

if exist %SIGNTOOL% (
    echo Using certificate: %CODE_SIGNING_THUMBPRINT%
    echo NOTE: Approve signing request in SimplySign mobile app...
    %SIGNTOOL% sign /sha1 %CODE_SIGNING_THUMBPRINT% /tr http://time.certum.pl /td SHA256 /fd SHA256 /d "PFR Sentinel" "dist\PFRSentinel\PFRSentinel.exe"
    if !ERRORLEVEL! EQU 0 (
        echo Executable signed successfully!
    ) else (
        echo WARNING: Signing failed, continuing with unsigned executable
    )
) else (
    echo WARNING: signtool.exe not found, skipping code signing
    echo Install Windows SDK to enable signing
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

REM Only pause if run directly (not from installer script)
if not defined BUILD_FROM_INSTALLER pause
exit /b 0
