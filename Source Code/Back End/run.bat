@echo off
:: Windows batch script for launching the A.R.C. Vision photo clustering system.
:: Detects bundled standalone Python or virtualenv environments and executes the clustering pipeline.
:: Handles runtime environment validation, pre-flight checks, and CLI argument forwarding.

cd /d "%~dp0"

REM 1. Check for bundled Python runtime (.python_win)
set "RUN_PY="
if exist ".python_win\python.exe" (
    set "RUN_PY=%CD%\.python_win\python.exe"
    goto :run_app
)

REM 2. Activate virtual environment if present
if not exist ".venv\Scripts\activate.bat" (
    echo [INFO] Windows virtual environment not found. Initializing setup...
    call setup.bat
)
call .venv\Scripts\activate.bat 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ============================================================
    echo  [ERROR] Virtual environment could not be activated.
    echo ============================================================
    echo.
    pause
    exit /b 1
)
set "RUN_PY=.venv\Scripts\python.exe"

REM 3. Run pre-flight environment check
"%RUN_PY%" check_env.py >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    "%RUN_PY%" check_env.py
    pause
    exit /b 1
)

:run_app
echo.
echo ============================================================
echo  Automated School Event Photo Clustering System (A.R.C.)
echo ============================================================
echo.

"%RUN_PY%" app.py %*

echo.
pause
