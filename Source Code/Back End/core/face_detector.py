"""
Face detection and geometric alignment module for the A.R.C. Vision pipeline.
Detects human faces in event photographs using MTCNN and extracts aligned RGB facial crops.
Handles bounding box localization, landmark detection, and detection confidence threshold filtering.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import torch
from facenet_pytorch import MTCNN

import config
from utils.logging_utils import get_logger

logger = get_logger(__name__)


@dataclass
class DetectedFace:
    """
    Container for a single face detection result.

    Attributes:
        image_path:    Source image file path.
        face_index:    0-based index among all faces detected in the image.
        bbox:          Bounding box as ``[x1, y1, x2, y2]`` (pixels).
        landmarks:     5-point facial landmarks array of shape ``(5, 2)``.
        confidence:    MTCNN detection confidence score (0.0 – 1.0).
        aligned_face:  Aligned and cropped face as RGB ``(112, 112, 3)`` array.
        image_shape:   Original image shape ``(height, width)``.
    """

    image_path: Path
    face_index: int
    bbox: list[float]
    landmarks: np.ndarray
    confidence: float
    aligned_face: np.ndarray
    image_shape: tuple[int, int]
    detection_time_ms: float = 0.0

    # Populated downstream by embedder / feature extractor
    embedding: np.ndarray = field(default_factory=lambda: np.array([]))
    color_histogram: np.ndarray = field(default_factory=lambda: np.array([]))
    spatial_features: np.ndarray = field(default_factory=lambda: np.array([]))
    fused_vector: np.ndarray = field(default_factory=lambda: np.array([]))
    cluster_label: int = -2   # -2 = not yet clustered; -1 = DBSCAN noise
    cosine_similarity: float | None = None
    similarity_to_centroid: float | None = None


class FaceDetector:
    """
    Wraps MTCNN for multi-face detection and geometric face alignment.

    Usage::

        detector = FaceDetector()
        faces = detector.detect_faces(image_rgb)

    Attributes:
        device: Torch device (cuda if available, else cpu).
        mtcnn:  Initialized MTCNN model instance.
    """

    def __init__(self) -> None:
        """Initialize MTCNN with configuration parameters."""
        import os
        try:
            num_threads = min(8, max(2, (os.cpu_count() or 4)))
            torch.set_num_threads(num_threads)
        except Exception:
            pass

        self.device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        logger.info(f"FaceDetector using device: {self.device}")

        # keep_all=True → return ALL faces, not just the largest
        self.mtcnn = MTCNN(
            image_size=config.FACE_IMAGE_SIZE,
            min_face_size=config.MTCNN_MIN_FACE_SIZE,
            thresholds=[0.6, 0.7, config.MTCNN_CONFIDENCE_THRESHOLD],
            keep_all=True,
            device=self.device,
            post_process=False,  # return raw pixel values, not normalized
        )
        logger.info(
            f"MTCNN initialized - min_face={config.MTCNN_MIN_FACE_SIZE}px, "
            f"confidence_threshold={config.MTCNN_CONFIDENCE_THRESHOLD}"
        )

    def detect_faces(
        self,
        image_rgb: np.ndarray,
        image_path: Path,
    ) -> list[DetectedFace]:
        """
        Detect all faces in an image and return aligned face crops.

        Args:
            image_rgb:  Input image as an RGB numpy array ``(H, W, 3)``.
            image_path: Source file path (stored in results for traceability).

        Returns:
            List of ``DetectedFace`` objects, one per detected face.
            Returns an empty list if no faces are found or detection fails.
        """
        t_start = time.perf_counter()
        results: list[DetectedFace] = []

        h, w = image_rgb.shape[:2]
        max_dim = 1280
        scale = 1.0
        if max(h, w) > max_dim:
            scale = max_dim / float(max(h, w))
            det_img = cv2.resize(image_rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
        else:
            det_img = image_rgb

        try:
            with torch.no_grad():
                boxes, probs, landmarks = self.mtcnn.detect(
                    det_img, landmarks=True
                )
        except Exception as exc:
            logger.warning(f"MTCNN detection failed for '{image_path.name}': {exc}")
            return results

        if boxes is None or probs is None:
            logger.debug(f"No faces detected in '{image_path.name}'")
            return results

        if scale != 1.0:
            boxes = np.array(boxes, dtype=np.float32) / scale
            landmarks = np.array(landmarks, dtype=np.float32) / scale

        elapsed_ms = (time.perf_counter() - t_start) * 1000

        for idx, (box, prob, lmk) in enumerate(zip(boxes, probs, landmarks)):

            if prob is None or float(prob) < config.MTCNN_CONFIDENCE_THRESHOLD:
                continue

            box_list = [float(v) for v in box]
            aligned = self._align_face(image_rgb, box_list, lmk)

            if aligned is None:
                logger.debug(
                    f"Face alignment failed for face {idx} in '{image_path.name}'"
                )
                continue

            face = DetectedFace(
                image_path=image_path,
                face_index=idx,
                bbox=box_list,
                landmarks=np.array(lmk, dtype=np.float32),
                confidence=float(prob),
                aligned_face=aligned,
                image_shape=(h, w),
                detection_time_ms=elapsed_ms,
            )
            results.append(face)

        results = self._filter_torso_artifacts(results)

        logger.debug(
            f"'{image_path.name}' -> {len(results)} face(s) detected "
            f"in {elapsed_ms:.1f} ms"
        )
        return results

    def _filter_torso_artifacts(self, faces: list[DetectedFace]) -> list[DetectedFace]:
        """
        Filter out secondary false-positive detections located on the torso/chest
        (e.g., uniform crests, sash emblems, buttons, or badges) in single-subject or portrait photos.
        """
        if len(faces) <= 1:
            return faces

        # Sort faces by confidence DESC, then by area DESC
        sorted_faces = sorted(
            faces,
            key=lambda f: (f.confidence, (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])),
            reverse=True,
        )

        primary = sorted_faces[0]
        p_w = primary.bbox[2] - primary.bbox[0]
        p_h = primary.bbox[3] - primary.bbox[1]
        p_area = p_w * p_h
        p_y2 = primary.bbox[3]

        valid_faces = [primary]

        for sec in sorted_faces[1:]:
            s_w = sec.bbox[2] - sec.bbox[0]
            s_h = sec.bbox[3] - sec.bbox[1]
            s_area = s_w * s_h
            s_y1 = sec.bbox[1]

            # If secondary box starts near or below the chin of primary face, and its area is much smaller
            is_torso_emblem = (s_y1 >= p_y2 - p_h * 0.25) and (s_area < p_area * 0.55) and (sec.confidence < 0.98 or primary.confidence > 0.99)
            if is_torso_emblem:
                logger.debug(
                    f"Filtered secondary torso emblem detection: '{sec.image_path.name}' "
                    f"face_index {sec.face_index} bbox={sec.bbox}"
                )
                continue
            valid_faces.append(sec)

        # Re-index remaining faces
        for new_idx, f in enumerate(valid_faces):
            f.face_index = new_idx

        return valid_faces

    def _align_face(
        self,
        image_rgb: np.ndarray,
        bbox: list[float],
        landmarks: np.ndarray,
    ) -> np.ndarray | None:
        """
        Geometrically align a face using eye landmarks (similarity transform).

        Alignment corrects in-plane rotation and scale so that ArcFace
        receives a canonical face crop regardless of head tilt.

        Args:
            image_rgb: Full source image in RGB.
            bbox:      Face bounding box ``[x1, y1, x2, y2]``.
            landmarks: 5-point landmarks array ``(5, 2)``:
                       left_eye, right_eye, nose, left_mouth, right_mouth.

        Returns:
            Aligned face crop of shape ``(112, 112, 3)`` in RGB, or ``None``
            if alignment fails.
        """
        try:
            target_size = config.FACE_IMAGE_SIZE

            # Reference landmarks for a canonical 112x112 ArcFace crop
            # (standard InsightFace reference points)
            ref_landmarks = np.array([
                [30.29, 51.69],
                [65.53, 51.50],
                [48.02, 71.74],
                [33.55, 92.37],
                [62.27, 92.20],
            ], dtype=np.float32)

            src_pts = np.array(landmarks[:5], dtype=np.float32)
            dst_pts = ref_landmarks

            # Estimate similarity (scale + rotation + translation) transform
            transform_matrix, _ = cv2.estimateAffinePartial2D(
                src_pts, dst_pts, method=cv2.LMEDS
            )

            if transform_matrix is None:
                # Fallback: simple crop without alignment
                return self._crop_face(image_rgb, bbox, target_size)

            aligned = cv2.warpAffine(
                image_rgb,
                transform_matrix,
                (target_size, target_size),
                flags=cv2.INTER_LANCZOS4,
                borderMode=cv2.BORDER_REFLECT,
            )
            return aligned

        except Exception as exc:
            logger.debug(f"Alignment error: {exc} — falling back to crop")
            return self._crop_face(image_rgb, bbox, target_size)

    def _crop_face(
        self,
        image_rgb: np.ndarray,
        bbox: list[float],
        target_size: int,
    ) -> np.ndarray | None:
        """
        Simple bounding-box crop as alignment fallback.

        Args:
            image_rgb:   Full source image in RGB.
            bbox:        ``[x1, y1, x2, y2]`` bounding box.
            target_size: Output crop size (pixels, square).

        Returns:
            Resized face crop or ``None`` if the box is invalid.
        """
        h, w = image_rgb.shape[:2]
        x1, y1, x2, y2 = (
            max(0, int(bbox[0])),
            max(0, int(bbox[1])),
            min(w, int(bbox[2])),
            min(h, int(bbox[3])),
        )
        if x2 <= x1 or y2 <= y1:
            return None

        crop = image_rgb[y1:y2, x1:x2]
        return cv2.resize(
            crop,
            (target_size, target_size),
            interpolation=cv2.INTER_LANCZOS4,
        )


# ── Module-level FastAPI-ready entry point ────────────────────────────────────

_detector_instance: FaceDetector | None = None


def detect_faces(
    image_rgb: np.ndarray,
    image_path: Path,
) -> list[DetectedFace]:
    """
    Module-level function for detecting faces in a single image.

    Lazily initializes a singleton ``FaceDetector`` on first call.

    Args:
        image_rgb:  Input image as an RGB ``(H, W, 3)`` array.
        image_path: Source file path for traceability.

    Returns:
        List of ``DetectedFace`` results.
    """
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = FaceDetector()
    return _detector_instance.detect_faces(image_rgb, image_path)
