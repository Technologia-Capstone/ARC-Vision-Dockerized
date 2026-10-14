"""
Multi-modal feature extraction module for clothing color and spatial geometry analysis.
Extracts normalized 3D HSV color histograms from torso regions and computes spatial bounding-box coordinates.
Handles auxiliary feature extraction to disambiguate similar facial profiles across lighting variations.
"""

from __future__ import annotations

import numpy as np
import cv2
from pathlib import Path

import config
from core.face_detector import DetectedFace
from utils.image_utils import crop_region
from utils.logging_utils import get_logger

logger = get_logger(__name__)

# Total histogram length: H_BINS × S_BINS × V_BINS
_HIST_LEN = config.COLOR_H_BINS * config.COLOR_S_BINS * config.COLOR_V_BINS


class FeatureExtractor:
    """
    Extracts clothing color histograms and spatial bounding-box features.

    Both features are L2-normalized so they can be concatenated with the
    ArcFace embedding for weighted feature fusion.

    Usage::

        extractor = FeatureExtractor()
        faces = extractor.extract_all(faces, full_image_rgb)
    """

    def extract_clothing_color(
        self,
        image_rgb: np.ndarray,
        bbox: list[float],
    ) -> np.ndarray:
        """
        Extract a normalized HSV color histogram from the torso region.

        The torso region is inferred as the area directly below the face
        bounding box, scaled by ``config.TORSO_HEIGHT_FRACTION`` and
        ``config.TORSO_WIDTH_MULTIPLIER``.

        Args:
            image_rgb: Full source image in RGB format.
            bbox:      Face bounding box ``[x1, y1, x2, y2]``.

        Returns:
            L2-normalized HSV histogram as a flat ``(_HIST_LEN,)`` array.
            Returns a zero vector if the torso region is invalid.
        """
        torso = self._get_torso_region(image_rgb, bbox)
        if torso is None or torso.size == 0:
            logger.debug("Torso region unavailable — returning zero histogram")
            return np.zeros(_HIST_LEN, dtype=np.float32)

        # Convert RGB torso crop → HSV for color analysis
        torso_hsv = cv2.cvtColor(torso, cv2.COLOR_RGB2HSV)

        # Compute 3D histogram
        hist = cv2.calcHist(
            [torso_hsv],
            [0, 1, 2],
            None,
            [config.COLOR_H_BINS, config.COLOR_S_BINS, config.COLOR_V_BINS],
            [0, 180, 0, 256, 0, 256],
        ).flatten().astype(np.float32)

        # L2-normalize
        norm = np.linalg.norm(hist)
        if norm > 1e-6:
            hist /= norm

        return hist

    def extract_spatial(
        self,
        image_shape: tuple[int, int],
        bbox: list[float],
    ) -> np.ndarray:
        """
        Extract normalized bounding box geometry as a 6-dim feature vector.

        All values are in the range [0, 1]:
        - ``center_x`` / image width
        - ``center_y`` / image height
        - ``face_width`` / image width
        - ``face_height`` / image height
        - ``aspect_ratio`` (width / height, clamped to [0, 1])
        - ``relative_area`` (bbox area / image area)

        Args:
            image_shape: ``(height, width)`` of the original image.
            bbox:        Face bounding box ``[x1, y1, x2, y2]``.

        Returns:
            6-dimensional normalized spatial feature vector.
        """
        img_h, img_w = image_shape
        x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]

        face_w = max(x2 - x1, 1.0)
        face_h = max(y2 - y1, 1.0)
        center_x = (x1 + x2) / 2.0
        center_y = (y1 + y2) / 2.0
        aspect_ratio = min(face_w / face_h, 1.0)
        relative_area = (face_w * face_h) / max(img_w * img_h, 1)

        features = np.array([
            center_x / max(img_w, 1),
            center_y / max(img_h, 1),
            face_w / max(img_w, 1),
            face_h / max(img_h, 1),
            aspect_ratio,
            min(relative_area, 1.0),
        ], dtype=np.float32)

        return features

    def extract_for_face(
        self,
        face: DetectedFace,
        image_rgb: np.ndarray,
    ) -> DetectedFace:
        """
        Extract both clothing and spatial features for a single face.

        Modifies the ``DetectedFace`` in-place by setting
        ``color_histogram`` and ``spatial_features``.

        Args:
            face:      The detected face to enrich.
            image_rgb: Full source image in RGB format.

        Returns:
            The same ``DetectedFace`` with features populated.
        """
        face.color_histogram = self.extract_clothing_color(
            image_rgb, face.bbox
        )
        face.spatial_features = self.extract_spatial(
            face.image_shape, face.bbox
        )
        return face

    def extract_all(
        self,
        faces: list[DetectedFace],
        image_rgb: np.ndarray,
    ) -> list[DetectedFace]:
        """
        Extract features for all faces in an image.

        Args:
            faces:     List of ``DetectedFace`` objects from the same image.
            image_rgb: Full source image in RGB format.

        Returns:
            The same list with features populated in-place.
        """
        for face in faces:
            self.extract_for_face(face, image_rgb)
        return faces

    def _get_torso_region(
        self,
        image_rgb: np.ndarray,
        bbox: list[float],
    ) -> np.ndarray | None:
        """
        Estimate and crop the torso region below the detected face.

        The torso window is centered on the face's horizontal center,
        starts at the bottom of the face bounding box, and extends
        downward by ``TORSO_HEIGHT_FRACTION`` of the image height.

        Args:
            image_rgb: Full source image in RGB.
            bbox:      Face bounding box ``[x1, y1, x2, y2]``.

        Returns:
            Torso crop as a numpy array, or ``None`` if out of bounds.
        """
        img_h, img_w = image_rgb.shape[:2]
        x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]

        face_w = x2 - x1
        face_cx = (x1 + x2) / 2.0

        # Torso width is proportional to face width
        torso_half_w = (face_w * config.TORSO_WIDTH_MULTIPLIER) / 2.0
        torso_x1 = int(face_cx - torso_half_w)
        torso_x2 = int(face_cx + torso_half_w)

        # Torso starts just below the chin
        torso_y1 = int(y2)
        torso_y2 = int(y2 + img_h * config.TORSO_HEIGHT_FRACTION)

        # Guard: region must be within image bounds
        torso_x1 = max(0, torso_x1)
        torso_x2 = min(img_w, torso_x2)
        torso_y1 = max(0, torso_y1)
        torso_y2 = min(img_h, torso_y2)

        if torso_x2 <= torso_x1 or torso_y2 <= torso_y1:
            return None

        return image_rgb[torso_y1:torso_y2, torso_x1:torso_x2]


# ── Module-level FastAPI-ready entry point ────────────────────────────────────

_extractor_instance: FeatureExtractor | None = None


def extract_features(
    faces: list[DetectedFace],
    image_rgb: np.ndarray,
) -> list[DetectedFace]:
    """
    Module-level function for feature extraction on a list of faces.

    Lazily initializes a singleton ``FeatureExtractor`` on first call.

    Args:
        faces:     List of detected faces from a single image.
        image_rgb: Full source image in RGB.

    Returns:
        The same list with ``color_histogram`` and ``spatial_features`` set.
    """
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = FeatureExtractor()
    return _extractor_instance.extract_all(faces, image_rgb)
