@echo off
REM Build script for ASIOverlayWatchDog executable
REM Creates a Windows executable using PyInstaller

echo ========================================
echo   ASIOverlayWatchDog - Build Executable
echo ========================================
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
if exist dist\ASIOverlayWatchDog rmdir /s /q dist\ASIOverlayWatchDog

echo.
echo Building executable with PyInstaller...
venv\Scripts\python.exe -m PyInstaller ASIOverlayWatchDog.spec

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
echo   dist\ASIOverlayWatchDog\ASIOverlayWatchDog.exe
echo.
echo You can now run:
echo   dist\ASIOverlayWatchDog\ASIOverlayWatchDog.exe
echo.
echo Or build the installer with:
echo   build_installer.bat
echo.

pause
