@echo off
REM ============================================================
REM Run Test Suite for ASIOverlayWatchDog
REM ============================================================
REM Usage: run_tests.bat [options]
REM Options:
REM   --quick    Run only fast tests (skip hardware tests)
REM   --verbose  Show verbose output
REM   --camera   Include camera hardware tests
REM ============================================================

setlocal EnableDelayedExpansion

REM Navigate to project root (parent of scripts directory)
cd /d "%~dp0"
if exist "scripts\run_tests.bat" cd ..

REM Activate virtual environment
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo Warning: Virtual environment not found, using system Python
)

REM Parse arguments
set PYTEST_ARGS=-v
set SKIP_CAMERA=1

:parse_args
if "%~1"=="" goto :run_tests
if /i "%~1"=="--quick" (
    set PYTEST_ARGS=!PYTEST_ARGS! -x --ignore=tests/test_camera.py
    shift
    goto :parse_args
)
if /i "%~1"=="--verbose" (
    set PYTEST_ARGS=!PYTEST_ARGS! -vv
    shift
    goto :parse_args
)
if /i "%~1"=="--camera" (
    set SKIP_CAMERA=0
    set PYTEST_ARGS=!PYTEST_ARGS! -m "requires_camera"
    shift
    goto :parse_args
)
shift
goto :parse_args

:run_tests
echo ============================================================
echo Running ASIOverlayWatchDog Test Suite
echo ============================================================
echo.

REM Check if pytest is installed
python -c "import pytest" 2>nul
if errorlevel 1 (
    echo Installing pytest...
    pip install pytest pytest-cov
)

REM Run tests
if %SKIP_CAMERA%==1 (
    echo Running tests (excluding hardware camera tests)...
    python -m pytest tests/ %PYTEST_ARGS% -m "not requires_camera" --tb=short
) else (
    echo Running all tests including hardware tests...
    python -m pytest tests/ %PYTEST_ARGS% --tb=short
)

set TEST_RESULT=%errorlevel%

echo.
if %TEST_RESULT%==0 (
    echo ============================================================
    echo All tests passed!
    echo ============================================================
) else (
    echo ============================================================
    echo Some tests failed. Exit code: %TEST_RESULT%
    echo ============================================================
)

exit /b %TEST_RESULT%
