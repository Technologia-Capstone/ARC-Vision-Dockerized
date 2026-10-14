@echo off
:: Universal standalone desktop launcher for A.R.C. Vision on Windows.
:: Resolves relative backend paths, configures DLL search directories for bundled Python 3.11, and launches desktop_app.py.
:: Handles automatic fallback to standalone background server and browser mode if required.
setlocal enabledelayedexpansion
title A.R.C. Vision - Launching...

:: Get absolute directory of this launcher
set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"

:: Resolve Back End directory
if exist "%APP_DIR%..\Source Code\Back End" (
    cd /d "%APP_DIR%..\Source Code\Back End"
) else if exist "%APP_DIR%Source Code\Back End" (
    cd /d "%APP_DIR%Source Code\Back End"
)

set "BACKEND_DIR=%CD%"

:: Ensure input and output folders exist
if not exist "input" mkdir "input"
if not exist "output" mkdir "output"

:: Set up DLL and site-packages paths for embedded Python runtime
set "PY_WIN=%BACKEND_DIR%\.python_win"
if exist "%PY_WIN%" (
    set "PATH=%PY_WIN%;%PY_WIN%\Lib\site-packages;%PY_WIN%\Lib\site-packages\torch\lib;%PY_WIN%\Lib\site-packages\onnxruntime\capi;%PY_WIN%\Lib\site-packages\cv2;%PY_WIN%\Lib\site-packages\numpy.libs;%PY_WIN%\Lib\site-packages\scipy.libs;%PATH%"
    set "PYTHONPATH=%BACKEND_DIR%;%PY_WIN%\Lib\site-packages"
    set "PY_EXE=%PY_WIN%\python.exe"
    set "PYW_EXE=%PY_WIN%\pythonw.exe"
) else if exist "%BACKEND_DIR%\.venv\Scripts\python.exe" (
    set "PY_EXE=%BACKEND_DIR%\.venv\Scripts\python.exe"
    set "PYW_EXE=%BACKEND_DIR%\.venv\Scripts\pythonw.exe"
) else (
    set "PY_EXE=python.exe"
    set "PYW_EXE=pythonw.exe"
)

echo ===================================================
echo   A.R.C. Vision - Automated Recognition and Clustering
echo ===================================================
echo.
echo Starting backend server and desktop application...
echo.

:: Launch desktop application
"%PY_EXE%" desktop_app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [Fallback] Launching standalone server and browser...
    start "" "%PYW_EXE%" server.py
    timeout /t 2 /nobreak >nul
    start "" "http://127.0.0.1:8000/loading.html"
)

exit /b 0
