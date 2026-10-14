"""
Facial feature embedding module for generating high-dimensional identity representations.
Extracts 512-dimensional L2-normalized ArcFace feature vectors from aligned face crops using InsightFace.
Handles model loading, batch inference, and embedding generation for downstream clustering.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import insightface
import numpy as np
from insightface.app import FaceAnalysis

import config
from core.face_detector import DetectedFace
from core.similarity import (
    cosine_similarity,
    cosine_distance,
    evaluate_identity_similarity,
)
from utils.logging_utils import get_logger

logger = get_logger(__name__)


class FaceEmbedder:
    """
    Extracts 512-dimensional L2-normalized ArcFace embeddings.

    The InsightFace ``FaceAnalysis`` app is initialized once and reused
    for all images. The model weights are downloaded automatically on
    first run (~700 MB) to ``config.INSIGHTFACE_MODEL_DIR``.

    Usage::

        embedder = FaceEmbedder()
        embedding = embedder.extract_embedding(aligned_face_rgb)

    Attributes:
        app: InsightFace FaceAnalysis application instance.
    """

    def __init__(self) -> None:
        """Load InsightFace ArcFace model from pretrained weights."""
        model_dir = str(config.INSIGHTFACE_MODEL_DIR)
        logger.info(
            f"Loading InsightFace model '{config.INSIGHTFACE_MODEL_NAME}' "
            f"(cache: {model_dir})"
        )

        # Determine provider based on CUDA availability
        try:
            import torch
            providers = (
                ["CUDAExecutionProvider", "CPUExecutionProvider"]
                if torch.cuda.is_available()
                else ["CPUExecutionProvider"]
            )
        except ImportError:
            providers = ["CPUExecutionProvider"]

        self.app = FaceAnalysis(
            name=config.INSIGHTFACE_MODEL_NAME,
            root=model_dir,
            providers=providers,
        )
        self.app.prepare(
            ctx_id=0 if "CUDA" in providers[0] else -1,
            det_size=config.INSIGHTFACE_DET_SIZE,
        )
        logger.info("InsightFace ArcFace model loaded successfully.")

    def extract_embedding(self, aligned_face_rgb: np.ndarray) -> np.ndarray | None:
        """
        Extract a 512-dimensional L2-normalized ArcFace embedding.

        We bypass InsightFace's internal detector by passing the
        pre-aligned 112x112 crop directly to the recognition model.

        Args:
            aligned_face_rgb: Aligned face crop as ``(112, 112, 3)`` RGB array.

        Returns:
            L2-normalized 512-dim embedding vector, or ``None`` on failure.
        """
        try:
            # Access the recognition model directly (bypasses re-detection)
            # rec_model.get_feat uses cv2.dnn.blobFromImages with swapRB=True,
            # so it expects RGB input.
            rec_model = self._get_recognition_model()
            if rec_model is None:
                face_bgr = cv2.cvtColor(aligned_face_rgb, cv2.COLOR_RGB2BGR)
                return self._fallback_extract(face_bgr)

            embedding = rec_model.get_feat(aligned_face_rgb)
            if embedding is None or embedding.size == 0:
                return None

            # Flatten and L2-normalize
            embedding = embedding.flatten().astype(np.float32)
            norm = np.linalg.norm(embedding)
            if norm > 1e-6:
                embedding /= norm

            return embedding

        except Exception as exc:
            logger.warning(f"Embedding extraction failed: {exc}")
            return None

    def _get_recognition_model(self):
        """
        Access the ArcFace recognition model from the InsightFace app.

        Returns:
            The recognition model object, or None if not found.
        """
        for model in self.app.models.values():
            if hasattr(model, "get_feat"):
                return model
        return None

    def _fallback_extract(self, face_bgr: np.ndarray) -> np.ndarray | None:
        """
        Fallback: Run full InsightFace pipeline on the face crop.

        Used when the recognition model cannot be accessed directly.

        Args:
            face_bgr: Face image in BGR format.

        Returns:
            512-dim embedding or None.
        """
        try:
            faces = self.app.get(face_bgr)
            if not faces:
                return None
            emb = faces[0].embedding.flatten().astype(np.float32)
            norm = np.linalg.norm(emb)
            if norm > 1e-6:
                emb /= norm
            return emb
        except Exception as exc:
            logger.warning(f"Fallback embedding failed: {exc}")
            return None

    def extract_batch(
        self,
        faces: list[DetectedFace],
    ) -> list[DetectedFace]:
        """
        Extract embeddings for a batch of detected faces using vectorized batch inference.

        Modifies each ``DetectedFace`` in-place by setting its
        ``embedding`` field.

        Args:
            faces: List of ``DetectedFace`` objects with ``aligned_face`` set.

        Returns:
            The same list with ``embedding`` fields populated.
            Faces where extraction fails retain an empty array.
        """
        if not faces:
            return faces

        t_start = time.perf_counter()
        rec_model = self._get_recognition_model()
        batch_size = getattr(config, 'EMBEDDING_BATCH_SIZE', 64)
        success_count = 0

        for i in range(0, len(faces), batch_size):
            chunk = faces[i:i + batch_size]
            rgb_crops = []
            valid_indices = []

            for idx, face in enumerate(chunk):
                if face.aligned_face is not None and face.aligned_face.size > 0:
                    rgb_crops.append(face.aligned_face)
                    valid_indices.append(idx)

            if not rgb_crops:
                continue

            try:
                if rec_model is not None:
                    batch_feats = rec_model.get_feat(rgb_crops)
                    norms = np.linalg.norm(batch_feats, axis=1, keepdims=True)
                    norms[norms < 1e-6] = 1.0
                    batch_embs = (batch_feats / norms).astype(np.float32)

                    for local_idx, emb in zip(valid_indices, batch_embs):
                        chunk[local_idx].embedding = emb
                        success_count += 1
                else:
                    # Fallback
                    for local_idx, rgb in zip(valid_indices, rgb_crops):
                        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                        emb = self._fallback_extract(bgr)
                        if emb is not None:
                            chunk[local_idx].embedding = emb
                            success_count += 1
            except Exception as exc:
                logger.warning(f"Batch embedding pass failed, falling back to sequential: {exc}")
                for local_idx, rgb in zip(valid_indices, rgb_crops):
                    emb = self.extract_embedding(chunk[local_idx].aligned_face)
                    if emb is not None:
                        chunk[local_idx].embedding = emb
                        success_count += 1

        elapsed = time.perf_counter() - t_start
        logger.info(
            f"Embedded {success_count}/{len(faces)} faces "
            f"in {elapsed:.3f}s "
            f"({(elapsed/max(len(faces),1))*1000:.2f} ms/face)"
        )
        return faces

    def compute_similarity(
        self,
        emb1: np.ndarray,
        emb2: np.ndarray,
    ) -> float:
        """
        Compute cosine similarity between two ArcFace embeddings.

        Args:
            emb1: 512-dim ArcFace embedding vector.
            emb2: 512-dim ArcFace embedding vector.

        Returns:
            Cosine similarity in [-1.0, 1.0].
        """
        return cosine_similarity(emb1, emb2)

    def evaluate_similarity(
        self,
        emb1: np.ndarray,
        emb2: np.ndarray,
        threshold: float = 0.58,
    ) -> dict:
        """
        Evaluate identity similarity between two face embeddings.

        Args:
            emb1:      First face embedding.
            emb2:      Second face embedding.
            threshold: Same-identity cosine similarity threshold.

        Returns:
            Evaluation summary dictionary.
        """
        return evaluate_identity_similarity(emb1, emb2, threshold=threshold)


# ── Module-level FastAPI-ready entry point ────────────────────────────────────

_embedder_instance: FaceEmbedder | None = None


def extract_embeddings(faces: list[DetectedFace]) -> list[DetectedFace]:
    """
    Module-level function for batch embedding extraction.

    Lazily initializes a singleton ``FaceEmbedder`` on first call.

    Args:
        faces: List of ``DetectedFace`` objects with aligned face crops.

    Returns:
        The same list with ``embedding`` fields populated in-place.
    """
    global _embedder_instance
    if _embedder_instance is None:
        _embedder_instance = FaceEmbedder()
    return _embedder_instance.extract_batch(faces)


def compute_embedding_similarity(emb1: np.ndarray, emb2: np.ndarray) -> float:
    """Compute cosine similarity between two embedding vectors."""
    return cosine_similarity(emb1, emb2)


def evaluate_face_pair(
    face1: DetectedFace,
    face2: DetectedFace,
    threshold: float = 0.58,
) -> dict:
    """Evaluate whether two DetectedFace instances represent the same identity."""
    vec1 = face1.fused_vector if face1.fused_vector.size > 1 else face1.embedding
    vec2 = face2.fused_vector if face2.fused_vector.size > 1 else face2.embedding
    return evaluate_identity_similarity(vec1, vec2, threshold=threshold)

