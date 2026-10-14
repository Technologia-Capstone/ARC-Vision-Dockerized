"""
Pre-flight environment and dependency verification script.
Validates Python runtime versions and imports for PyTorch, MTCNN, InsightFace, ONNX Runtime, and Scikit-Learn.
Handles diagnostic error reporting with OS-specific remediation instructions for missing binaries or VC++ redistributables.
"""

import sys

VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
SEPARATOR = "=" * 60

def fail(title: str, detail: str, fix: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  [SETUP ERROR] {title}")
    print(SEPARATOR)
    print(f"\n  {detail}\n")
    print(f"  HOW TO FIX:\n  {fix}\n")
    print(SEPARATOR)
    sys.exit(1)


# ── 1. Python version ─────────────────────────────────────────────────────────
major, minor = sys.version_info[:2]
if major < 3 or (major == 3 and minor < 10):
    fix_msg = (
        "Install Python 3.10+ using Homebrew: brew install python@3.10"
        if sys.platform == "darwin"
        else "Download Python 3.11 from: https://www.python.org/downloads/windows/\n"
             "  Make sure to check 'Add Python to PATH' during installation."
    )
    fail(
        "Python version too old",
        f"Detected Python {major}.{minor}. This project requires Python 3.10 or newer.",
        fix_msg
    )

# ── 2. onnxruntime ────────────────────────────────────────────────────────────
try:
    import onnxruntime  # noqa: F401
except ImportError as e:
    err = str(e)
    if sys.platform == "win32" and ("DLL load failed" in err or "specified module could not be found" in err):
        fail(
            "Missing Visual C++ Redistributable (DLL not found)",
            "onnxruntime cannot load because the Microsoft Visual C++ Runtime\n"
            "  is not installed on this machine.\n\n"
            "  Error detail: " + err,
            f"Download and install the Visual C++ Redistributable:\n"
            f"  {VCREDIST_URL}\n\n"
            "  After installing, re-run run.bat — no other changes needed."
        )
    else:
        fix_cmd = "./start_server.sh" if sys.platform == "darwin" else "setup.bat"
        fail(
            "onnxruntime not installed",
            f"Could not import onnxruntime: {e}",
            f"Run {fix_cmd} or 'pip install -r requirements.txt' to install dependencies."
        )


# ── 3. insightface ────────────────────────────────────────────────────────────
try:
    import insightface  # noqa: F401
except ImportError as e:
    fail(
        "insightface not installed",
        f"Could not import insightface: {e}",
        "Re-run setup.bat to reinstall all dependencies."
    )

# ── 4. facenet-pytorch (MTCNN) ────────────────────────────────────────────────
try:
    from facenet_pytorch import MTCNN  # noqa: F401
except ImportError as e:
    fail(
        "facenet-pytorch not installed",
        f"Could not import facenet_pytorch: {e}",
        "Re-run setup.bat to reinstall all dependencies."
    )

# ── 5. torch ──────────────────────────────────────────────────────────────────
try:
    import torch  # noqa: F401
except ImportError as e:
    fail(
        "PyTorch not installed",
        f"Could not import torch: {e}",
        "Re-run setup.bat to reinstall all dependencies."
    )

# ── 6. scikit-learn ───────────────────────────────────────────────────────────
try:
    import sklearn  # noqa: F401
except ImportError as e:
    fail(
        "scikit-learn not installed",
        f"Could not import sklearn: {e}",
        "Re-run setup.bat to reinstall all dependencies."
    )

# ── All checks passed ─────────────────────────────────────────────────────────
print("[OK] Environment check passed — all dependencies are healthy.")
