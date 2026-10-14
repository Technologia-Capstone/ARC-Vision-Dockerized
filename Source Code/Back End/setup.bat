@echo off
:: Automated setup and environment configuration script for Windows.
:: Verifies Python installation, installs VC++ runtime prerequisites, creates virtual environments, and installs dependencies.
:: Handles automated pip upgrades, PyTorch installation, dependency resolution, and environment verification.

echo.
echo ============================================================
echo  Automated School Event Photo Clustering System - Setup
echo ============================================================
echo.

REM ?? Check for Python ????????????????????????????????????????
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found on PATH.
    echo.
    echo Please install Python 3.11 from: https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

REM ?? Check Python version (requires 3.10+) ???????????????????
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python 3.10 or newer is required.
    python --version
    echo.
    echo Please install Python 3.11 from: https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

python --version
echo.

REM ?? Step 1: Install Visual C++ Redistributable ???????????????
echo [1/4] Checking Visual C++ Redistributable...
echo       (Required by onnxruntime - safe to skip if already installed)
echo.

REM Download vc_redist.x64.exe silently if not already present
if not exist "%TEMP%\vc_redist.x64.exe" (
    echo       Downloading VC++ Redistributable...
    powershell -Command "try { Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile '%TEMP%\vc_redist.x64.exe' -UseBasicParsing; Write-Host '      Download complete.' } catch { Write-Host '      Download failed - skipping. Install manually if needed.' }"
)

REM Install silently (/install /quiet /norestart)
if exist "%TEMP%\vc_redist.x64.exe" (
    echo       Installing VC++ Redistributable [silent]...
    "%TEMP%\vc_redist.x64.exe" /install /quiet /norestart
    if %ERRORLEVEL% EQU 0 (
        echo       VC++ Redistributable installed successfully.
    ) else if %ERRORLEVEL% EQU 1638 (
        echo       VC++ Redistributable already installed - OK.
    ) else (
        echo       [WARN] VC++ install returned code %ERRORLEVEL% - may already be installed.
    )
) else (
    echo       [WARN] Could not download VC++ Redistributable.
    echo             If the system fails to start, download it manually:
    echo             https://aka.ms/vs/17/release/vc_redist.x64.exe
)
echo.

REM ?? Step 2: Create virtual environment ??????????????????????
echo [2/4] Creating virtual environment (.venv)...
if exist ".venv\" (
    echo       Found existing .venv - removing it to ensure a clean install...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -Recurse -Force '.venv' -ErrorAction SilentlyContinue" >nul 2>&1
    if exist ".venv\" rmdir /s /q .venv 2>nul
    if exist ".venv\" (
        echo.
        echo [ERROR] Could not delete the existing '.venv' folder.
        echo         This usually happens if another terminal, command prompt, or code editor
        echo         [like VS Code] is locking the folder.
        echo.
        echo Please close all programs or terminals using '.venv' and run setup.bat again.
        pause
        exit /b 1
    )
)
python -m venv .venv
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)
echo       Done.
echo.

REM ?? Step 3: Upgrade pip ????????????????????????
echo [3/4] Upgrading pip...
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [WARN] Failed to upgrade pip. Proceeding anyway...
) else (
    echo       Done.
)
echo.

REM ?? Step 4: Install dependencies from requirements.txt ??????
echo [4/4] Installing dependencies (this may take several minutes)...
echo       Downloading PyTorch CPU build (~700 MB)...
.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to install PyTorch CPU build.
    pause
    exit /b 1
)

echo.
echo       Installing remaining packages (pinned versions)...
.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to install dependencies from requirements.txt.
    pause
    exit /b 1
)
echo.

REM ?? Verify environment ????????????????????????????????????????
echo Verifying installation...
.venv\Scripts\python.exe check_env.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Setup verification failed. See message above.
    pause
    exit /b 1
)

REM ?? Create input folder ???????????????????????????????????????
if not exist "input\" (
    mkdir input
    echo [INFO] Created 'input\' folder - place your photos here.
)

echo.
echo ============================================================
echo  Setup complete!
echo ============================================================
echo.
echo  Next steps:
echo  1. Place your school event photos in the 'input\' folder
echo  2. Run the system:     run.bat
echo.
pause

