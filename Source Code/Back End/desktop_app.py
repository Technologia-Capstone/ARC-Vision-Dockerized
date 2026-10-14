"""
Native desktop application wrapper for A.R.C. Vision across macOS and Windows.
Spawns background FastAPI server lifecycle and renders dedicated desktop window via PyWebView or Edge/Chrome App-Mode.
Handles native file/folder picker integration, automated health polling, and clean application shutdown.
"""

from __future__ import annotations

import io
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

# Safe stream guards for headless / pythonw windowed execution
class _SafeStream:
    def __init__(self, fallback=None):
        self.fallback = fallback
        self.encoding = "utf-8"
        self.errors = "replace"

    def write(self, s):
        if self.fallback:
            try:
                return self.fallback.write(s)
            except Exception:
                pass
        return len(s) if s else 0

    def flush(self):
        if self.fallback:
            try:
                self.fallback.flush()
            except Exception:
                pass

    def isatty(self):
        return False

    @property
    def buffer(self):
        return io.BytesIO()

if sys.stdout is None:
    sys.stdout = _SafeStream()
if sys.stderr is None:
    sys.stderr = _SafeStream()

# Ensure backend root is in sys.path
SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Windows DLL directories configuration
if sys.platform == "win32":
    dll_candidates = [
        os.path.join(str(SCRIPT_DIR), ".python_win"),
        os.path.join(str(SCRIPT_DIR), ".python_win", "Lib", "site-packages"),
        os.path.join(str(SCRIPT_DIR), ".python_win", "Lib", "site-packages", "torch", "lib"),
        os.path.join(str(SCRIPT_DIR), ".python_win", "Lib", "site-packages", "onnxruntime", "capi"),
        os.path.join(str(SCRIPT_DIR), ".python_win", "Lib", "site-packages", "cv2"),
        os.path.join(str(SCRIPT_DIR), ".python_win", "Lib", "site-packages", "numpy.libs"),
        os.path.join(str(SCRIPT_DIR), ".python_win", "Lib", "site-packages", "scipy.libs"),
        os.path.join(str(SCRIPT_DIR), ".python_win", "Lib", "site-packages", "ml_dtypes.libs"),
    ]
    for d in dll_candidates:
        if os.path.exists(d):
            try:
                os.add_dll_directory(d)
            except Exception:
                pass
            os.environ["PATH"] = d + ";" + os.environ.get("PATH", "")

# Configure Chromium / WebView2 engine arguments for un-interacted media autoplay
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

import config

SERVER_HOST = getattr(config, "SERVER_HOST", "127.0.0.1")
SERVER_PORT = getattr(config, "SERVER_PORT", 8000)
BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"
HEALTH_URL = f"{BASE_URL}/api/health"
APP_URL = f"{BASE_URL}/loading.html"

_server_thread: threading.Thread | None = None
_server_instance = None
_server_process: subprocess.Popen | None = None
_app_browser_process: subprocess.Popen | None = None


def is_port_open(host: str = SERVER_HOST, port: int = SERVER_PORT, timeout: float = 0.1) -> bool:
    """Check whether the backend TCP port is accepting connections."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def is_server_healthy(timeout: float = 0.5) -> bool:
    """Verify backend health endpoint returns 200 OK."""
    try:
        req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "ARC-Vision-Desktop"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_backend_in_thread() -> bool:
    """Start uvicorn server in a daemon thread."""
    global _server_thread, _server_instance
    try:
        import uvicorn
        from server import app

        uv_config = uvicorn.Config(
            app=app,
            host=SERVER_HOST,
            port=SERVER_PORT,
            log_level="warning",
            access_log=False,
            workers=1,
            loop="asyncio",
        )
        _server_instance = uvicorn.Server(uv_config)

        def run_srv():
            try:
                _server_instance.run()
            except Exception as e:
                print(f"[DesktopApp] Server thread exited: {e}", file=sys.stderr)

        _server_thread = threading.Thread(target=run_srv, daemon=True, name="ARC-Vision-Server")
        _server_thread.start()
        return True
    except Exception as exc:
        print(f"[DesktopApp] Failed to start in-thread server: {exc}", file=sys.stderr)
        return False


def start_backend_in_subprocess() -> bool:
    """Fallback: Start server.py as a detached background subprocess."""
    global _server_process
    py_dir = SCRIPT_DIR / ".python_win"
    venv_dir = SCRIPT_DIR / ".venv"

    if sys.platform == "win32" and (py_dir / "python.exe").exists():
        py_exe = str(py_dir / "python.exe")
    elif (venv_dir / "bin" / "python").exists():
        py_exe = str(venv_dir / "bin" / "python")
    elif (venv_dir / "Scripts" / "python.exe").exists():
        py_exe = str(venv_dir / "Scripts" / "python.exe")
    else:
        py_exe = sys.executable

    log_path = SCRIPT_DIR / "server_output.log"
    try:
        log_f = open(log_path, "a", encoding="utf-8", errors="replace")
    except Exception:
        log_f = open(log_path, "wb")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW

    try:
        _server_process = subprocess.Popen(
            [py_exe, "server.py"],
            cwd=str(SCRIPT_DIR),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        return True
    except Exception as exc:
        print(f"[DesktopApp] Failed to spawn server subprocess: {exc}", file=sys.stderr)
        return False


def wait_for_server_ready(max_seconds: float = 30.0) -> bool:
    """Poll health endpoint until server responds or timeout occurs."""
    start_t = time.time()
    while time.time() - start_t < max_seconds:
        if is_server_healthy(timeout=0.3):
            return True
        time.sleep(0.15)
    return False


def on_window_closed() -> None:
    """Handle clean shutdown when user closes the desktop window."""
    global _server_instance, _server_process
    print("[DesktopApp] Application window closed. Shutting down server...", file=sys.stderr)

    if _server_instance is not None:
        try:
            _server_instance.should_exit = True
        except Exception:
            pass

    if _server_process is not None:
        try:
            _server_process.terminate()
            _server_process.wait(timeout=2.0)
        except Exception:
            try:
                _server_process.kill()
            except Exception:
                pass


def find_windows_app_browser() -> tuple[str | None, str]:
    """Locate Microsoft Edge or Chrome executable for standalone app-mode window on Windows."""
    candidates = [
        (os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"), "msedge"),
        (os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"), "msedge"),
        (os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"), "msedge"),
        (os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"), "chrome"),
        (os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"), "chrome"),
        (os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"), "chrome"),
    ]
    for path, b_type in candidates:
        if os.path.exists(path):
            return path, b_type
    return None, ""


def launch_windows_app_mode(url: str = APP_URL) -> bool:
    """Launch dedicated standalone desktop window via Edge or Chrome App Mode."""
    global _app_browser_process
    browser_exe, b_type = find_windows_app_browser()
    if not browser_exe:
        return False

    profile_dir = SCRIPT_DIR / ".app_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        browser_exe,
        f"--app={url}",
        "--window-size=1400,880",
        f"--user-data-dir={profile_dir}",
        "--autoplay-policy=no-user-gesture-required",
        "--disable-extensions",
        "--disable-plugins",
        "--no-first-run",
    ]

    try:
        _app_browser_process = subprocess.Popen(cmd, cwd=str(SCRIPT_DIR))
        # Monitor process in foreground until user closes window
        _app_browser_process.wait()
        return True
    except Exception as exc:
        print(f"[DesktopApp] Failed to launch app mode window: {exc}", file=sys.stderr)
        return False


class DesktopBridge:
    def __init__(self):
        self._window = None

    def set_window(self, window):
        self._window = window

    def select_files(self) -> list[str]:
        if self._window:
            try:
                import webview
                res = self._window.create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=True,
                    file_types=('Image Files (*.jpg;*.jpeg;*.png;*.webp;*.bmp;*.tiff)', 'All files (*.*)')
                )
                return [str(p) for p in res] if res else []
            except Exception as e:
                print(f"[DesktopBridge] select_files error: {e}", file=sys.stderr)
        return []

    def select_folder(self) -> str:
        if self._window:
            try:
                import webview
                res = self._window.create_file_dialog(
                    webview.FOLDER_DIALOG
                )
                if res and len(res) > 0:
                    return str(res[0])
            except Exception as e:
                print(f"[DesktopBridge] select_folder error: {e}", file=sys.stderr)
        return ""

    def open_downloads_folder(self) -> bool:
        downloads_dir = str(Path.home() / "Downloads")
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", downloads_dir], check=False)
            elif sys.platform == "win32":
                subprocess.run(["explorer", downloads_dir], check=False)
            return True
        except Exception:
            return False


bridge = DesktopBridge()


def launch_pywebview_window() -> bool:
    """Attempt to launch window using PyWebView."""
    import webview

    # On macOS, ensure application window gets active foreground dock policy and configure WKWebView media autoplay
    if sys.platform == "darwin":
        try:
            from AppKit import NSApplication, NSApplicationActivationPolicyRegular, NSRunningApplication, NSApplicationActivateIgnoringOtherApps
            cocoa_app = NSApplication.sharedApplication()
            cocoa_app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
            curr = NSRunningApplication.currentApplication()
            if curr:
                curr.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        except Exception:
            pass

        try:
            import webview.platforms.cocoa as cocoa
            if hasattr(cocoa, 'BrowserView') and not getattr(cocoa.BrowserView, '_arc_patched', False):
                orig_cocoa_init = cocoa.BrowserView.__init__

                def safe_cocoa_init(self, window):
                    orig_cocoa_init(self, window)
                    try:
                        if hasattr(self, 'webview') and hasattr(self.webview, 'configuration'):
                            cfg = self.webview.configuration()
                            if hasattr(cfg, 'setMediaTypesRequiringUserActionForPlayback_'):
                                cfg.setMediaTypesRequiringUserActionForPlayback_(0)
                            if hasattr(cfg, 'setAllowsInlineMediaPlayback_'):
                                cfg.setAllowsInlineMediaPlayback_(True)
                    except Exception as e:
                        print(f"[DesktopApp] WKWebView config notice: {e}", file=sys.stderr)

                cocoa.BrowserView.__init__ = safe_cocoa_init
                cocoa.BrowserView._arc_patched = True
        except Exception as exc:
            print(f"[DesktopApp] Cocoa WebKit hook notice: {exc}", file=sys.stderr)

    window_title = "A.R.C. Vision — Automated Recognition and Clustering"
    window = webview.create_window(
        title=window_title,
        url=APP_URL,
        width=1400,
        height=880,
        min_size=(1024, 700),
        background_color="#0F172A",
        text_select=True,
        zoomable=True,
        confirm_close=False,
        js_api=bridge,
    )
    bridge.set_window(window)
    window.events.closed += on_window_closed

    webview.start(debug=False)
    return True


def main() -> None:
    """Main desktop application entry point."""
    os.chdir(str(SCRIPT_DIR))

    # Ensure required input and output directories exist
    (SCRIPT_DIR / "input").mkdir(parents=True, exist_ok=True)
    (SCRIPT_DIR / "output").mkdir(parents=True, exist_ok=True)

    server_already_running = is_server_healthy(timeout=0.2) or is_port_open(SERVER_HOST, SERVER_PORT)

    if not server_already_running:
        started = start_backend_in_thread()
        if not started:
            start_backend_in_subprocess()

    # Launch Desktop Window via multi-tier strategy
    gui_launched = False

    # Tier 1: Try PyWebView native window
    try:
        launch_pywebview_window()
        gui_launched = True
    except Exception as e:
        print(f"[DesktopApp] PyWebView window launch notice: {e}", file=sys.stderr)

    # Tier 2 (Windows): Standalone Edge / Chrome App Mode Window
    if not gui_launched and sys.platform == "win32":
        wait_for_server_ready(max_seconds=5.0)
        try:
            gui_launched = launch_windows_app_mode(APP_URL)
        except Exception as e:
            print(f"[DesktopApp] Edge App Mode launch notice: {e}", file=sys.stderr)

    # Tier 3: Browser Fallback if no window framework succeeded
    if not gui_launched:
        wait_for_server_ready(max_seconds=5.0)
        import webbrowser
        try:
            if sys.platform == "win32":
                os.startfile(APP_URL)
            else:
                webbrowser.open(APP_URL)
        except Exception:
            pass

    on_window_closed()


if __name__ == "__main__":
    main()
