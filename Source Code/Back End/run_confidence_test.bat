@echo off
:: Automated confidence and accuracy test launcher for Windows.
:: Activates the Python environment and executes the clustering confidence and quality validation test suite.
:: Handles test environment execution and terminal output reporting.

cd /d "%~dp0"

set "RUN_PY="
if exist ".python_win\python.exe" (
    set "RUN_PY=%CD%\.python_win\python.exe"
    goto :run_test
)

call .venv\Scripts\activate.bat 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Virtual environment not found. Please run setup.bat first.
    pause
    exit /b 1
)
set "RUN_PY=.venv\Scripts\python.exe"

:run_test
echo.
echo ============================================================
echo  Photo Clustering - Confidence Test
echo ============================================================
echo.

"%RUN_PY%" tests\confidence_test.py %*

echo.
pause
