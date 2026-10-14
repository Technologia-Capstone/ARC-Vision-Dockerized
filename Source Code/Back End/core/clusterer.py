"""
Unsupervised identity clustering module based on density-based spatial clustering (DBSCAN).
Groups multi-modal fused feature vectors into distinct person identity clusters using pairwise cosine distance metrics.
Handles automatic identity discovery, noise classification for unclustered faces, and cluster quality metrics evaluation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize

import config
from core.face_detector import DetectedFace
from core.similarity import (
    cosine_similarity,
    cosine_distance,
    cosine_similarity_matrix,
    cosine_distance_matrix,
    compute_cluster_centroid,
    compute_cluster_similarity_breakdown,
)
from utils.logging_utils import get_logger

logger = get_logger(__name__)


@dataclass
class ClusterStats:
    """
    Summary statistics for the clustering result.

    Attributes:
        n_clusters:               Number of valid clusters (excludes noise).
        n_noise:                  Number of noise points (label == -1).
        n_total:                  Total number of faces clustered.
        silhouette_score:         Silhouette score [-1, 1]. Higher is better.
                                  None if fewer than 2 clusters.
        intra_similarities:       Dict mapping cluster label → mean cosine similarity.
        cluster_sizes:            Dict mapping cluster label → member count.
        clustering_time_s:        Wall-clock time to run DBSCAN.
        min_intra_similarities:   Dict mapping cluster label → min cosine similarity.
        max_intra_similarities:   Dict mapping cluster label → max cosine similarity.
        std_intra_similarities:   Dict mapping cluster label → std dev of similarity.
        centroid_similarities:    Dict mapping cluster label → mean member similarity to centroid.
        inter_cluster_similarity: Mean cosine similarity between cluster centroids.
        centroids:                Dict mapping cluster label → L2-normalized centroid vector.
    """

    n_clusters: int
    n_noise: int
    n_total: int
    silhouette_score: float | None
    intra_similarities: dict[int, float]
    cluster_sizes: dict[int, int]
    clustering_time_s: float
    min_intra_similarities: dict[int, float] = field(default_factory=dict)
    max_intra_similarities: dict[int, float] = field(default_factory=dict)
    std_intra_similarities: dict[int, float] = field(default_factory=dict)
    centroid_similarities: dict[int, float] = field(default_factory=dict)
    inter_cluster_similarity: float = 0.0
    centroids: dict[int, np.ndarray] = field(default_factory=dict)


class FaceClusterer:
    """
    Clusters detected faces into person identities using DBSCAN.

    Each cluster represents one unique person identity. Noise points
    (faces too dissimilar to form a cluster) are assigned label -1.

    Usage::

        clusterer = FaceClusterer()
        faces, stats = clusterer.cluster(faces)

    Attributes:
        eps:         DBSCAN neighborhood radius in cosine distance space.
        min_samples: Minimum neighbors to form a core point.
    """

    def __init__(
        self,
        eps: float = config.DBSCAN_EPS,
        min_samples: int = config.DBSCAN_MIN_SAMPLES,
    ) -> None:
        """
        Initialize DBSCAN parameters.

        Args:
            eps:         Max cosine distance between two points to be neighbors.
            min_samples: Min samples to define a core point (cluster seed).
        """
        self.eps = eps
        self.min_samples = min_samples
        logger.info(
            f"FaceClusterer — DBSCAN(eps={eps}, min_samples={min_samples}, "
            "metric=cosine)"
        )

    def cluster(
        self,
        faces: list[DetectedFace],
    ) -> tuple[list[DetectedFace], ClusterStats]:
        """
        Assign cluster labels to every face in the list.

        Only faces with a valid (non-zero, correctly dimensioned) fused vector
        are clustered. Faces with empty vectors receive label -1 (noise).

        Args:
            faces: List of ``DetectedFace`` with ``fused_vector`` set.

        Returns:
            - The same list with ``cluster_label`` set on each face.
            - A ``ClusterStats`` object with summary metrics.

        Raises:
            ValueError: If no face has a valid embedding.
        """
        valid_indices, vectors, confidences = self._collect_valid_vectors(faces)

        if len(valid_indices) == 0:
            raise ValueError(
                "No valid fused vectors found. "
                "Check that embedding and feature extraction succeeded."
            )

        logger.info(
            f"Clustering {len(valid_indices)} faces "
            f"({len(faces) - len(valid_indices)} skipped) "
            f"with DBSCAN(eps={self.eps}, min_samples={self.min_samples})"
        )

        t_start = time.perf_counter()
        labels = self._run_dbscan(vectors, face_confidences=confidences, faces=faces, valid_indices=valid_indices)
        elapsed = time.perf_counter() - t_start

        # Write labels back to DetectedFace objects
        for idx, label in zip(valid_indices, labels):
            faces[idx].cluster_label = int(label)

        # Faces with no valid embedding stay at default -2
        # Remap them to -1 so they go to Unknown/
        for face in faces:
            if face.cluster_label == -2:
                face.cluster_label = -1

        stats, member_sims = self._compute_stats(faces, valid_indices, vectors, labels, elapsed)

        # Assign per-face cosine similarity values to DetectedFace objects
        for local_idx, orig_idx in enumerate(valid_indices):
            sim_val = float(member_sims[local_idx]) if local_idx < len(member_sims) else 1.0
            faces[orig_idx].similarity_to_centroid = sim_val
            faces[orig_idx].cosine_similarity = sim_val

        # Low-confidence thresholding: Route faces with detection confidence < 0.86
        # or centroid similarity < 0.60 to cluster_label -3 (Flagged) instead of Person001 or Person folders
        for orig_idx in valid_indices:
            f = faces[orig_idx]
            if f.cluster_label >= 0:
                if f.confidence < 0.86 or f.cosine_similarity < 0.60:
                    f.cluster_label = -3
            elif f.cluster_label == -1 and f.confidence < 0.86:
                f.cluster_label = -3

        self._log_stats(stats)

        return faces, stats

    def _collect_valid_vectors(
        self,
        faces: list[DetectedFace],
    ) -> tuple[list[int], np.ndarray, list[float]]:
        """
        Collect valid fused vectors, their indices, and detection confidences.

        A vector is valid if it is non-empty, 1-D, and has more than one
        element (excludes the placeholder zero vector of size 1).

        Args:
            faces: All detected faces.

        Returns:
            - List of integer indices into ``faces`` with valid vectors.
            - 2D array of shape ``(n_valid, dim)`` containing the vectors.
            - List of float confidence scores.
        """
        valid_indices: list[int] = []
        vectors: list[np.ndarray] = []
        confidences: list[float] = []

        for i, face in enumerate(faces):
            v = face.fused_vector
            if v is not None and v.ndim == 1 and v.size > 1:
                valid_indices.append(i)
                vectors.append(v)
                confidences.append(float(getattr(face, "confidence", 1.0)))

        if vectors:
            arr = np.vstack(vectors).astype(np.float32)
            # Re-normalize rows in-place (important for cosine metric)
            arr = normalize(arr, norm="l2", copy=False)
            return valid_indices, arr, confidences

        return valid_indices, np.array([], dtype=np.float32), confidences

    def _run_dbscan(
        self,
        vectors: np.ndarray,
        face_confidences: list[float] | None = None,
        faces: list[DetectedFace] | None = None,
        valid_indices: list[int] | None = None,
    ) -> np.ndarray:
        """
        Run DBSCAN with multi-pass centroid re-assignment and singleton promotion.
        Optimized for high-dimensional face feature vectors (3,000+ faces).

        Args:
            vectors:          ``(N, D)`` float32 array of L2-normalized fused vectors.
            face_confidences: Optional list of detection confidence scores for noise filtering.

        Returns:
            Integer label array of length N. -1 = noise.
        """
        if len(vectors) == 0:
            return np.array([], dtype=int)

        # Precompute L2-normalized cosine distance matrix (32-bit for memory efficiency)
        dist_matrix = cosine_distance_matrix(vectors).astype(np.float32)

        dbscan = DBSCAN(
            eps=self.eps,
            min_samples=self.min_samples,
            metric="precomputed",
            n_jobs=-1,
        )
        labels = dbscan.fit_predict(dist_matrix)

        # Post-processing 1: Check intra-cluster cosine similarity to purge extreme outliers
        unique_labels = set(labels) - {-1}
        for lbl in unique_labels:
            member_indices = np.where(labels == lbl)[0]
            if len(member_indices) > 2:
                sub_matrix = dist_matrix[np.ix_(member_indices, member_indices)]
                mean_dists = np.mean(sub_matrix, axis=1)
                max_allowed_dist = self.eps * 1.35
                outliers = member_indices[mean_dists > max_allowed_dist]
                labels[outliers] = -1

        # Post-processing 2: Centroid Re-assignment for unassigned noise points using cosine similarity
        unique_labels = set(labels) - {-1}
        centroids: dict[int, np.ndarray] = {}
        for lbl in unique_labels:
            indices = np.where(labels == lbl)[0]
            cluster_vecs = vectors[indices]
            centroids[lbl] = compute_cluster_centroid(cluster_vecs)

        noise_indices = np.where(labels == -1)[0]
        for idx in noise_indices:
            v = vectors[idx]
            best_lbl = -1
            max_sim = -1.0
            second_max_sim = -1.0
            for lbl, c_vec in centroids.items():
                sim = float(np.dot(v, c_vec))
                if sim > max_sim:
                    second_max_sim = max_sim
                    max_sim = sim
                    best_lbl = lbl
                elif sim > second_max_sim:
                    second_max_sim = sim
            # Cosine similarity >= 0.62 and margin check ensure ambiguous noise faces are not forced into cluster 0
            if max_sim >= 0.62 and (max_sim - second_max_sim >= 0.02) and best_lbl != -1:
                labels[idx] = best_lbl

        # Post-processing 3: Group unassigned noise points with pairwise similarity
        noise_indices = np.where(labels == -1)[0]
        if len(noise_indices) > 1:
            noise_sub_dist = dist_matrix[np.ix_(noise_indices, noise_indices)]
            sub_db = DBSCAN(eps=0.38, min_samples=2, metric="precomputed").fit_predict(noise_sub_dist)
            next_label = (max(labels) + 1) if len(set(labels) - {-1}) > 0 else 0
            sub_clusters: dict[int, int] = {}
            for sub_i, sub_lbl in enumerate(sub_db):
                if sub_lbl != -1:
                    if sub_lbl not in sub_clusters:
                        sub_clusters[sub_lbl] = next_label
                        next_label += 1
                    labels[noise_indices[sub_i]] = sub_clusters[sub_lbl]

        # Post-processing 4: Promote high-confidence singleton noise faces to individual person identities
        noise_indices = np.where(labels == -1)[0]
        next_label = (max(labels) + 1) if len(set(labels) - {-1}) > 0 else 0
        for idx in noise_indices:
            conf = face_confidences[idx] if (face_confidences and idx < len(face_confidences)) else 1.0
            if conf >= 0.85:
                labels[idx] = next_label
                next_label += 1

        # Post-processing 5: Intra-photo collision check (Must-Not-Link constraint)
        # Faces appearing in the exact same photo cannot belong to the same person.
        unique_labels = set(labels) - {-1}
        for lbl in unique_labels:
            indices = np.where(labels == lbl)[0]
            if faces and valid_indices and len(indices) > 2:
                member_photos = [faces[valid_indices[i]].image_path.name for i in indices if i < len(valid_indices)]
                if len(member_photos) != len(set(member_photos)):
                    duplicate_count = len(member_photos) - len(set(member_photos))
                    collision_ratio = duplicate_count / len(member_photos)
                    if collision_ratio > 0.25:
                        labels[indices] = -1

        return labels

    def _compute_stats(
        self,
        faces: list[DetectedFace],
        valid_indices: list[int],
        vectors: np.ndarray,
        labels: np.ndarray,
        elapsed: float,
    ) -> tuple[ClusterStats, list[float]]:
        """
        Compute summary statistics and similarity breakdown from DBSCAN output.

        Args:
            faces:         All detected faces (with labels set).
            valid_indices: Indices of valid-vector faces in ``faces``.
            vectors:       ``(N, D)`` matrix used for clustering.
            labels:        DBSCAN label array.
            elapsed:       Wall-clock seconds for DBSCAN.

        Returns:
            Tuple of (ClusterStats object, member_similarities list).
        """
        unique_labels = set(labels)
        n_clusters = len(unique_labels - {-1})
        n_noise = int(np.sum(labels == -1))

        # Per-cluster member counts
        cluster_sizes: dict[int, int] = {}
        for lbl in labels:
            lbl = int(lbl)
            cluster_sizes[lbl] = cluster_sizes.get(lbl, 0) + 1

        # Comprehensive similarity telemetry via similarity engine
        sim_data = compute_cluster_similarity_breakdown(vectors, labels)
        intra_sims = sim_data["intra_similarities"]
        min_intra_sims = sim_data["min_intra_similarities"]
        max_intra_sims = sim_data["max_intra_similarities"]
        std_intra_sims = sim_data["std_intra_similarities"]
        centroid_sims = sim_data["centroid_similarities"]
        centroids = sim_data["centroids"]
        inter_sim = sim_data["inter_cluster_similarity"]
        member_sims = sim_data["member_similarities_to_centroid"]

        # Silhouette score (sampled for large datasets to guarantee < 50ms execution)
        sil_score: float | None = None
        if n_clusters >= 2 and len(valid_indices) - n_noise >= 2:
            try:
                non_noise_mask = labels != -1
                valid_count = int(np.sum(non_noise_mask))
                if valid_count > 1000:
                    sil_score = float(
                        silhouette_score(
                            vectors[non_noise_mask],
                            labels[non_noise_mask],
                            metric="cosine",
                            sample_size=min(1200, valid_count),
                            random_state=42
                        )
                    )
                else:
                    sil_score = float(
                        silhouette_score(
                            vectors[non_noise_mask],
                            labels[non_noise_mask],
                            metric="cosine",
                        )
                    )
            except Exception as exc:
                logger.warning(f"Silhouette score failed: {exc}")

        stats = ClusterStats(
            n_clusters=n_clusters,
            n_noise=n_noise,
            n_total=len(valid_indices),
            silhouette_score=sil_score,
            intra_similarities=intra_sims,
            cluster_sizes=cluster_sizes,
            clustering_time_s=elapsed,
            min_intra_similarities=min_intra_sims,
            max_intra_similarities=max_intra_sims,
            std_intra_similarities=std_intra_sims,
            centroid_similarities=centroid_sims,
            inter_cluster_similarity=inter_sim,
            centroids=centroids,
        )

        return stats, member_sims

    def _log_stats(self, stats: ClusterStats) -> None:
        """Log a human-readable summary of the clustering result."""
        logger.info("=" * 60)
        logger.info(f"CLUSTERING COMPLETE")
        logger.info(f"  Faces processed : {stats.n_total}")
        logger.info(f"  Clusters found  : {stats.n_clusters} person(s)")
        logger.info(f"  Noise (Unknown) : {stats.n_noise} face(s)")
        if stats.silhouette_score is not None:
            logger.info(f"  Silhouette score: {stats.silhouette_score:.4f}")
        if stats.inter_cluster_similarity is not None and stats.n_clusters > 1:
            logger.info(f"  Inter-cluster sim: {stats.inter_cluster_similarity:.4f}")
        for lbl, size in sorted(stats.cluster_sizes.items()):
            if lbl == -1:
                continue
            sim = stats.intra_similarities.get(lbl, 0.0)
            min_s = stats.min_intra_similarities.get(lbl, sim)
            max_s = stats.max_intra_similarities.get(lbl, sim)
            logger.info(f"  Cluster {lbl:3d}: {size:3d} face(s), "
                        f"avg_similarity={sim:.3f} (min={min_s:.3f}, max={max_s:.3f})")
        logger.info("=" * 60)


# ── Module-level FastAPI-ready entry point ────────────────────────────────────

_clusterer_instance: FaceClusterer | None = None


def cluster_faces(
    faces: list[DetectedFace],
) -> tuple[list[DetectedFace], ClusterStats]:
    """
    Module-level function for DBSCAN clustering on detected faces.

    Lazily initializes a singleton ``FaceClusterer`` on first call.

    Args:
        faces: List of ``DetectedFace`` with ``fused_vector`` set.

    Returns:
        - The same list with ``cluster_label`` assigned to each face.
        - A ``ClusterStats`` summary object.
    """
    global _clusterer_instance
    if _clusterer_instance is None:
        _clusterer_instance = FaceClusterer()
    return _clusterer_instance.cluster(faces)
