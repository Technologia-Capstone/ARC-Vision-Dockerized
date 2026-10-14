"""
Image loading, decoding, and preprocessing utility functions.
Loads image files into RGB arrays, applies automatic EXIF orientation transposition, and generates thumbnails.
Handles multi-format image validation, directory scanning, and memory-efficient image resizing.
"""

from __future__ import annotations

import os
import cv2
import numpy as np
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError

import config
from utils.logging_utils import get_logger

logger = get_logger(__name__)


def get_image_files(folder: Path) -> list[Path]:
    """
    Recursively collect all accepted image files from a directory.

    Args:
        folder: Root directory to search.

    Returns:
        Sorted list of image file Paths matching ``config.ACCEPTED_FORMATS``.

    Raises:
        FileNotFoundError: If ``folder`` does not exist.
        NotADirectoryError: If ``folder`` is not a directory.
    """
    if not folder.exists():
        raise FileNotFoundError(f"Input folder not found: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Expected a directory, got: {folder}")

    accepted = set(fmt.lower() for fmt in config.ACCEPTED_FORMATS)
    found: list[Path] = []

    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for file in files:
            if file.startswith("."):
                continue
            ext = Path(file).suffix.lower()
            if ext in accepted:
                found.append(Path(root) / file)

    unique = sorted(found)
    logger.info(f"Found {len(unique)} image(s) in '{folder}'")
    return unique



def load_image_rgb(path: Path, max_dim: int = 1280) -> np.ndarray | None:
    """
    Load an image from disk directly as an RGB numpy array, automatically handling
    EXIF orientation and downscaling large photos (e.g. 4K/8K) to max_dim (1280px)
    with zero redundant color conversions for high-throughput batch processing.
    """
    try:
        with Image.open(path) as pil_img:
            # If large JPEG, Pillow draft mode accelerates decoding
            if max_dim and hasattr(pil_img, "draft"):
                try:
                    pil_img.draft("RGB", (max_dim, max_dim))
                except Exception:
                    pass
            pil_img = ImageOps.exif_transpose(pil_img)
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")

            w, h = pil_img.size
            if max_dim and (w > max_dim or h > max_dim):
                scale = max_dim / float(max(w, h))
                new_w = max(1, int(w * scale))
                new_h = max(1, int(h * scale))
                resample_mode = getattr(Image, "Resampling", Image).BILINEAR
                pil_img = pil_img.resize((new_w, new_h), resample=resample_mode)

            rgb = np.array(pil_img, dtype=np.uint8)
        return rgb
    except Exception as exc:
        logger.warning(f"Could not load image '{path}': {exc}")
        return None


def load_image_bgr(path: Path) -> np.ndarray | None:
    """
    Load an image from disk as a BGR numpy array (OpenCV convention),
    automatically transposing according to EXIF orientation metadata tags.

    Args:
        path: Absolute or relative path to the image file.

    Returns:
        NumPy array of shape ``(H, W, 3)`` in BGR format, or
        ``None`` if the file cannot be read.
    """
    rgb = load_image_rgb(path, max_dim=0)
    if rgb is None:
        return None
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)



def validate_image(path: Path) -> bool:
    """
    Verify that a file is a valid, readable image using Pillow.

    Args:
        path: Path to the candidate image file.

    Returns:
        ``True`` if the file is a valid image, ``False`` otherwise.
    """
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except (UnidentifiedImageError, Exception) as exc:
        logger.warning(f"Invalid image '{path.name}': {exc}")
        return False


def bgr_to_rgb(image: np.ndarray) -> np.ndarray:
    """Convert a BGR image array to RGB in-place safe copy."""
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def rgb_to_bgr(image: np.ndarray) -> np.ndarray:
    """Convert an RGB image array to BGR in-place safe copy."""
    return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)


def resize_image(
    image: np.ndarray,
    target_size: tuple[int, int],
) -> np.ndarray:
    """
    Resize an image to the given ``(width, height)`` using Lanczos interpolation.

    Args:
        image:       Source image array (H, W, C).
        target_size: Target ``(width, height)`` in pixels.

    Returns:
        Resized image array.
    """
    return cv2.resize(image, target_size, interpolation=cv2.INTER_LANCZOS4)


def crop_region(
    image: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
) -> np.ndarray:
    """
    Safely crop a rectangular region from an image, clamping to bounds.

    Args:
        image: Source image array.
        x1, y1: Top-left corner.
        x2, y2: Bottom-right corner.

    Returns:
        Cropped sub-image. Returns an empty array if the region is invalid.
    """
    h, w = image.shape[:2]
    x1 = max(0, min(x1, w - 1))
    y1 = max(0, min(y1, h - 1))
    x2 = max(x1 + 1, min(x2, w))
    y2 = max(y1 + 1, min(y2, h))
    return image[y1:y2, x1:x2]
