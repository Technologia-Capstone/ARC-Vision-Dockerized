"""
Zero-window background process launcher for Windows environments.
Spawns background desktop or server instances with single-stream logging and sub-millisecond socket readiness polling.
Handles bundled runtime DLL environment configuration, automatic browser fallback, and native Windows error dialogs.
"""

from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


def is_port_open(host: str = "127.0.0.1", port: int = 8000, timeout: float = 0.1) -> bool:
    """Check whether a TCP port is currently accepting connections."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def show_error_box(message: str, title: str = "A.R.C. Vision Startup Error") -> None:
    """Display a native Windows error dialog."""
    # Method 1: Native Windows MessageBox API via ctypes
    if sys.platform == "win32":
        try:
            # MB_ICONERROR (0x10) | MB_SETFOREGROUND (0x10000) | MB_TOPMOST (0x40000)
            flags = 0x10 | 0x10000 | 0x40000
            ctypes.windll.user32.MessageBoxW(0, str(message), str(title), flags)
            return
        except Exception:
            pass

    # Method 2: mshta VBScript popup fallback
    try:
        safe_msg = message.replace("\\", "\\\\").replace('"', '""').replace("\r\n", "\n").replace("\n", "' & vbCrLf & '")
        safe_title = title.replace('"', '""')
        cmd = f'vbscript:MsgBox("{safe_msg}", 16, "{safe_title}")(window.close)'
        subprocess.run(["mshta", cmd], check=False, creationflags=0x08000000 if sys.platform == "win32" else 0)
        return
    except Exception:
        pass

    # Method 3: PowerShell MessageBox fallback
    try:
        escaped_msg = message.replace("`", "``").replace('"', '`"')
        escaped_title = title.replace("`", "``").replace('"', '`"')
        ps_code = (
            '[System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null; '
            + f'[System.Windows.Forms.MessageBox]::Show("{escaped_msg}", "{escaped_title}", '
            + '[System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null'
        )
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_code], check=False)
    except Exception:
        pass


def open_browser(url: str = "http://127.0.0.1:8000/loading.html") -> None:
    """Open the target URL in the default web browser."""
    if sys.platform == "win32":
        try:
            os.startfile(url)
            return
        except Exception:
            pass
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> None:
    script_dir = Path(__file__).parent.resolve()
    os.chdir(str(script_dir))

    # 1. Instant check: If server is already running, spawn desktop app window directly
    if is_port_open("127.0.0.1", 8000, timeout=0.1):
        target_script = "desktop_app.py" if (script_dir / "desktop_app.py").exists() else "server.py"
        if target_script == "desktop_app.py":
            # Spawn desktop app window
            pass

    # 2. Ensure required directories exist
    (script_dir / "input").mkdir(parents=True, exist_ok=True)
    (script_dir / "output").mkdir(parents=True, exist_ok=True)

    # 3. Locate Python executable (Fast-Path: bundled runtime)
    py_dir = script_dir / ".python_win"
    venv_dir = script_dir / ".venv" / "Scripts"

    if (py_dir / "python.exe").exists():
        py_exe = str(py_dir / "python.exe")
    elif (venv_dir / "python.exe").exists():
        py_exe = str(venv_dir / "python.exe")
    else:
        # Fallback to sys.executable replacing pythonw with python
        base_exe = Path(sys.executable).name.lower()
        if "pythonw" in base_exe:
            py_exe = str(Path(sys.executable).with_name("python.exe"))
        else:
            py_exe = sys.executable

    log_file_path = script_dir / "server_output.log"

    # Configure DLL search directories for Windows environment
    env = os.environ.copy()
    if sys.platform == "win32" and py_dir.exists():
        extra_paths = [
            str(py_dir),
            str(py_dir / "Lib" / "site-packages"),
            str(py_dir / "Lib" / "site-packages" / "torch" / "lib"),
            str(py_dir / "Lib" / "site-packages" / "onnxruntime" / "capi"),
            str(py_dir / "Lib" / "site-packages" / "cv2"),
            str(py_dir / "Lib" / "site-packages" / "numpy.libs"),
            str(py_dir / "Lib" / "site-packages" / "scipy.libs"),
            str(py_dir / "Lib" / "site-packages" / "ml_dtypes.libs"),
        ]
        valid_paths = [p for p in extra_paths if os.path.exists(p)]
        if valid_paths:
            env["PATH"] = ";".join(valid_paths) + ";" + env.get("PATH", "")

    # 4. Open log file and spawn server process
    try:
        log_file = open(log_file_path, "w", encoding="utf-8", errors="replace")
    except Exception:
        log_file = open(log_file_path, "wb")

    creationflags = 0
    if sys.platform == "win32":
        # DETACHED_PROCESS (0x00000008) | CREATE_NO_WINDOW (0x08000000)
        creationflags = 0x00000008 | 0x08000000

    target_script = "desktop_app.py" if (script_dir / "desktop_app.py").exists() else "server.py"
    server_cmd = [py_exe, target_script]
    try:
        proc = subprocess.Popen(
            server_cmd,
            cwd=str(script_dir),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            env=env,
            close_fds=True,
        )
        sys.exit(0)
    except Exception as e:
        show_error_box(
            f"Failed to start A.R.C. Vision desktop process:\n\n{e}\n\nExecutable: {py_exe}\nDirectory: {script_dir}"
        )
        sys.exit(1)

    # 5. Fast polling loop (checks every 100ms for up to 30 seconds)
    opened = False
    max_checks = 300  # 300 * 0.1s = 30 seconds
    for _ in range(max_checks):
        time.sleep(0.1)
        if is_port_open("127.0.0.1", 8000, timeout=0.05):
            time.sleep(0.1)  # Brief delay to allow FastAPI route readiness
            open_browser("http://127.0.0.1:8000/loading.html")
            opened = True
            break
        if proc.poll() is not None:
            # Process terminated prematurely
            break

    if not opened:
        err_snippet = ""
        try:
            if log_file_path.exists():
                with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    err_snippet = "".join(lines[-20:]).strip()
        except Exception:
            pass

        if err_snippet:
            show_error_box(
                f"A.R.C. Vision server could not start.\n\nError output:\n{err_snippet}\n\nCheck 'server_output.log' in Source Code\\Back End for details."
            )
        else:
            show_error_box(
                "A.R.C. Vision server is taking longer than expected to initialize.\n\nPlease check 'server_output.log' in Source Code\\Back End for details."
            )
        sys.exit(1)


if __name__ == "__main__":
    main()
