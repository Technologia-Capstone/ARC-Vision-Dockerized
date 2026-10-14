"""
Multi-modal feature fusion engine for combining heterogeneous identity signals.
Performs weighted concatenation and L2 renormalization of facial embeddings, clothing histograms, and spatial coordinates.
Handles feature weighting balance (85% facial, 10% color, 5% spatial) for unified cosine distance clustering.
"""

from __future__ import annotations

import numpy as np

import config
from core.face_detector import DetectedFace
from utils.logging_utils import get_logger

logger = get_logger(__name__)


class FeatureFusion:
    """
    Fuses face embedding, color histogram, and spatial features
    into a single weighted, L2-normalized vector.

    Weights are read from ``config`` and can be changed without
    modifying any other module.

    Usage::

        fusion = FeatureFusion()
        faces = fusion.fuse_all(faces)

    Attributes:
        face_weight:    Weight for the ArcFace 512-dim embedding.
        color_weight:   Weight for the 288-dim clothing color histogram.
        spatial_weight: Weight for the 6-dim spatial feature vector.
    """

    def __init__(
        self,
        face_weight: float = config.FACE_WEIGHT,
        color_weight: float = config.COLOR_WEIGHT,
        spatial_weight: float = config.SPATIAL_WEIGHT,
    ) -> None:
        """
        Initialize fusion weights.

        Args:
            face_weight:    Contribution of ArcFace embedding (default 0.80).
            color_weight:   Contribution of color histogram (default 0.15).
            spatial_weight: Contribution of spatial features (default 0.05).

        Raises:
            ValueError: If any weight is negative or weights don't sum to ~1.
        """
        if any(w < 0 for w in [face_weight, color_weight, spatial_weight]):
            raise ValueError("All fusion weights must be non-negative.")

        total = face_weight + color_weight + spatial_weight
        if abs(total - 1.0) > 1e-3:
            logger.warning(
                f"Fusion weights sum to {total:.4f} (expected 1.0). "
                "They will be auto-normalized."
            )
            face_weight /= total
            color_weight /= total
            spatial_weight /= total

        self.face_weight = face_weight
        self.color_weight = color_weight
        self.spatial_weight = spatial_weight

        logger.info(
            f"FeatureFusion weights — face={self.face_weight:.2f}, "
            f"color={self.color_weight:.2f}, "
            f"spatial={self.spatial_weight:.2f}"
        )

    def fuse(
        self,
        face_embedding: np.ndarray,
        color_histogram: np.ndarray,
        spatial_features: np.ndarray,
    ) -> np.ndarray:
        """
        Create a fused, L2-normalized feature vector from three sub-vectors.

        Each sub-vector is scaled by its weight before concatenation.
        The result is renormalized so cosine distance remains a valid metric.

        Args:
            face_embedding:   512-dim L2-normalized ArcFace embedding.
            color_histogram:  N-dim L2-normalized HSV histogram.
            spatial_features: 6-dim normalized spatial feature vector.

        Returns:
            Fused vector as a 1D float32 array, L2-normalized.
            Returns a zero vector if all inputs are empty.
        """
        parts: list[np.ndarray] = []

        if face_embedding.size > 0:
            parts.append(face_embedding.flatten() * self.face_weight)
        if color_histogram.size > 0:
            parts.append(color_histogram.flatten() * self.color_weight)
        if spatial_features.size > 0:
            parts.append(spatial_features.flatten() * self.spatial_weight)

        if not parts:
            logger.warning("All feature parts are empty — returning zero vector")
            return np.zeros(1, dtype=np.float32)

        fused = np.concatenate(parts).astype(np.float32)

        # L2-renormalize so cosine distance works on fused space
        norm = np.linalg.norm(fused)
        if norm > 1e-6:
            fused /= norm

        return fused

    def fuse_face(self, face: DetectedFace) -> DetectedFace:
        """
        Fuse features for a single ``DetectedFace`` and set ``fused_vector``.

        Args:
            face: ``DetectedFace`` with embedding, color_histogram, and
                  spatial_features already populated.

        Returns:
            The same ``DetectedFace`` with ``fused_vector`` set.
        """
        face.fused_vector = self.fuse(
            face.embedding,
            face.color_histogram,
            face.spatial_features,
        )
        return face

    def fuse_all(self, faces: list[DetectedFace]) -> list[DetectedFace]:
        """
        Fuse features for every face in the list.

        Skips faces where the ArcFace embedding is empty (extraction failed).

        Args:
            faces: List of ``DetectedFace`` objects with features populated.

        Returns:
            The same list with ``fused_vector`` set for each face.
        """
        skipped = 0
        for face in faces:
            if face.embedding.size == 0:
                skipped += 1
                face.fused_vector = np.zeros(1, dtype=np.float32)
                continue
            self.fuse_face(face)

        if skipped:
            logger.warning(f"Skipped {skipped} face(s) with missing embeddings")

        logger.debug(f"Fused {len(faces) - skipped}/{len(faces)} feature vectors")
        return faces


# ── Module-level FastAPI-ready entry point ────────────────────────────────────

_fusion_instance: FeatureFusion | None = None


def fuse_features(faces: list[DetectedFace]) -> list[DetectedFace]:
    """
    Module-level function for feature fusion on a list of detected faces.

    Lazily initializes a singleton ``FeatureFusion`` on first call.

    Args:
        faces: List of ``DetectedFace`` objects with all feature fields set.

    Returns:
        The same list with ``fused_vector`` populated in-place.
    """
    global _fusion_instance
    if _fusion_instance is None:
        _fusion_instance = FeatureFusion()
    return _fusion_instance.fuse_all(faces)
