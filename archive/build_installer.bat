@echo off
REM Complete build script for ASIOverlayWatchDog
REM Builds executable and creates Windows installer

echo ========================================
echo   ASIOverlayWatchDog - Full Build
echo ========================================
echo.

REM Step 1: Build executable
echo [1/2] Building executable...
call build_exe.bat
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Executable build failed!
    pause
    exit /b 1
)

echo.
echo [2/2] Creating installer...

REM Sync version from version.py to version.iss
echo Synchronizing version...
python update_version.py
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Version synchronization failed!
    pause
    exit /b 1
)

REM Check if Inno Setup is installed
set "INNO_X86=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
set "INNO_X64=C:\Program Files\Inno Setup 6\ISCC.exe"

if exist "%INNO_X86%" (
    set "INNO_PATH=%INNO_X86%"
    goto :inno_found
)

if exist "%INNO_X64%" (
    set "INNO_PATH=%INNO_X64%"
    goto :inno_found
)

echo.
echo ERROR: Inno Setup not found!
echo.
echo Please install Inno Setup from:
echo https://jrsoftware.org/isinfo.php
echo.
echo Expected location:
echo   C:\Program Files (x86)\Inno Setup 6\ISCC.exe
echo   OR
echo   C:\Program Files\Inno Setup 6\ISCC.exe
echo.
pause
exit /b 1

:inno_found
REM Create installer output directory
if not exist installer\dist mkdir installer\dist

REM Build installer with proper escaping
echo Building installer with Inno Setup...
"%INNO_PATH%" installer\ASIOverlayWatchDog.iss

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Installer build failed!
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Build completed successfully!
echo ========================================
echo.
echo Installer location:
for /f "tokens=*" %%v in ('python -c "import version; print(version.__version__)"') do set VERSION=%%v
echo   installer\dist\ASIOverlayWatchDog-%VERSION%-setup.exe
echo.
echo You can now:
echo   1. Test the installer
echo   2. Distribute the installer to users
echo.
echo Log files will be stored in:
echo   %%LOCALAPPDATA%%\ASIOverlayWatchDog\Logs
echo   (7-day automatic rotation)
echo.

pause
