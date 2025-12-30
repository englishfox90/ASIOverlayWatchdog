@echo off
REM Build and package ASIOverlayWatchDog for release
REM This script runs tests then creates a portable ZIP ready for distribution

echo ========================================
echo ASIOverlayWatchDog Release Builder
echo ========================================
echo.

REM Check if venv exists
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found!
    echo Please run: python -m venv venv
    echo Then: .\venv\Scripts\Activate.ps1
    echo Then: pip install -r requirements.txt
    pause
    exit /b 1
)

REM Activate venv
echo [1/6] Activating virtual environment...
call venv\Scripts\activate.bat

REM Run tests first
echo [2/6] Running test suite...
python -m pytest tests/ -v -m "not requires_camera" --tb=short
if errorlevel 1 (
    echo.
    echo ERROR: Tests failed! Fix failing tests before building release.
    pause
    exit /b 1
)
echo Tests passed!
echo.

REM Clean previous builds
echo [3/6] Cleaning previous builds...
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build

REM Build with PyInstaller
echo [4/6] Building with PyInstaller...
pyinstaller --clean ASIOverlayWatchDog.spec
if errorlevel 1 (
    echo ERROR: PyInstaller build failed!
    pause
    exit /b 1
)

REM Check if ASICamera2.dll is in the output
if not exist "dist\ASIOverlayWatchDog\_internal\ASICamera2.dll" (
    echo WARNING: ASICamera2.dll not found in build output!
    echo Make sure ASICamera2.dll is in the project root before building.
    echo The build will work but camera capture will not function.
    pause
)

REM Get version from version.py
for /f "tokens=3 delims= " %%a in ('findstr "__version__" version.py') do set VERSION_RAW=%%a
set VERSION=%VERSION_RAW:"=%

REM Create portable ZIP
echo [5/6] Creating portable ZIP...
cd dist
powershell -Command "Compress-Archive -Path ASIOverlayWatchDog -DestinationPath ..\releases\ASIOverlayWatchDog-v%VERSION%-Portable.zip -Force"
cd ..

REM Done
echo [6/6] Build complete!
echo.
echo ========================================
echo Release package created:
echo releases\ASIOverlayWatchDog-v%VERSION%-Portable.zip
echo ========================================
echo.
echo File size:
dir releases\ASIOverlayWatchDog-v%VERSION%-Portable.zip | find "ASIOverlayWatchDog"
echo.
echo Next steps:
echo 1. Test the portable ZIP on a clean machine
echo 2. If all works, commit to Git: git add releases\*.zip
echo 3. Create release tag: git tag v%VERSION%
echo 4. Push: git push origin main --tags
echo.
pause
