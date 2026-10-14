"""
Centralized application logging configuration and factory module.
Initializes unified formatting, stream output handlers, and optional file logging across all backend modules.
Handles log level configurations, timestamp formatting, and suppression of noisy third-party libraries.
"""

import logging
import sys
from pathlib import Path


_INITIALIZED: bool = False
_LOG_FORMAT: str = (
    "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
)
_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_file: Path | None = None,
    debug: bool = False,
) -> None:
    """
    Configure the root logger once for the entire application.

    Must be called before any module calls ``get_logger()``.

    Args:
        log_file: Optional path to write log output. Parent directories
                  are created automatically.
        debug:    If True, sets level to DEBUG; otherwise INFO.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    level = logging.DEBUG if debug else logging.INFO
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    for noisy in ("PIL", "matplotlib", "urllib3", "insightface", "onnxruntime"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A configured ``logging.Logger`` instance.
    """
    return logging.getLogger(name)
