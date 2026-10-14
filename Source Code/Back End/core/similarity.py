"""
Mathematical similarity metrics and vector computation engine for face embeddings.
Computes pairwise cosine distances, cosine similarity matrices, and cluster centroid estimations in spherical embedding space.
Handles zero-norm safety guards, vector normalization, and intra-to-inter cluster similarity evaluations.
"""

from __future__ import annotations

from typing import Any
import numpy as np


def cosine_similarity(
    vec1: np.ndarray,
    vec2: np.ndarray,
) -> float:
    """
    Compute cosine similarity between two feature vectors.

    For vectors u and v:
        cos_sim(u, v) = (u . v) / (||u|| * ||v||)

    For pre-normalized vectors, this reduces to the inner product u . v.
    Guards against zero-magnitude vectors and clamps output to [-1.0, 1.0].

    Args:
        vec1: 1D feature vector or ArcFace embedding.
        vec2: 1D feature vector or ArcFace embedding.

    Returns:
        Float cosine similarity in [-1.0, 1.0]. Returns 0.0 if either vector is empty or zero-norm.
    """
    if vec1 is None or vec2 is None:
        return 0.0

    v1 = np.asarray(vec1, dtype=np.float32).flatten()
    v2 = np.asarray(vec2, dtype=np.float32).flatten()

    if v1.size == 0 or v2.size == 0 or v1.size != v2.size:
        return 0.0

    norm1 = float(np.linalg.norm(v1))
    norm2 = float(np.linalg.norm(v2))

    if norm1 < 1e-7 or norm2 < 1e-7:
        return 0.0

    sim = float(np.dot(v1, v2) / (norm1 * norm2))
    return max(-1.0, min(1.0, sim))


def cosine_similarity_matrix(
    a: np.ndarray,
    b: np.ndarray | None = None,
) -> np.ndarray:
    """
    Compute pairwise cosine similarity matrix between rows of A (and optionally B).

    Args:
        a: (N, D) matrix of feature vectors.
        b: Optional (M, D) matrix. If None, computes pairwise similarity of A with itself.

    Returns:
        (N, M) or (N, N) matrix with cosine similarities in [-1.0, 1.0].
    """
    mat_a = np.asarray(a, dtype=np.float32)
    if mat_a.ndim == 1:
        mat_a = mat_a.reshape(1, -1)

    if mat_a.size == 0:
        return np.empty((0, 0), dtype=np.float32)

    # Normalize rows of A
    norms_a = np.linalg.norm(mat_a, axis=1, keepdims=True)
    norms_a[norms_a < 1e-7] = 1.0
    normed_a = mat_a / norms_a

    if b is None:
        sim_mat = np.dot(normed_a, normed_a.T)
    else:
        mat_b = np.asarray(b, dtype=np.float32)
        if mat_b.ndim == 1:
            mat_b = mat_b.reshape(1, -1)
        if mat_b.size == 0:
            return np.empty((mat_a.shape[0], 0), dtype=np.float32)

        norms_b = np.linalg.norm(mat_b, axis=1, keepdims=True)
        norms_b[norms_b < 1e-7] = 1.0
        normed_b = mat_b / norms_b

        sim_mat = np.dot(normed_a, normed_b.T)

    return np.clip(sim_mat, -1.0, 1.0)


def cosine_distance(
    vec1: np.ndarray,
    vec2: np.ndarray,
) -> float:
    """
    Compute cosine distance between two feature vectors: 1.0 - cosine_similarity.

    Returns:
        Float cosine distance in [0.0, 2.0].
    """
    return max(0.0, min(2.0, 1.0 - cosine_similarity(vec1, vec2)))


def cosine_distance_matrix(
    a: np.ndarray,
    b: np.ndarray | None = None,
) -> np.ndarray:
    """
    Compute pairwise cosine distance matrix: 1.0 - cosine_similarity_matrix.

    Returns:
        (N, M) or (N, N) matrix with cosine distances in [0.0, 2.0].
    """
    sim_mat = cosine_similarity_matrix(a, b)
    dist_mat = 1.0 - sim_mat
    return np.clip(dist_mat, 0.0, 2.0)


def compute_cluster_centroid(vectors: np.ndarray) -> np.ndarray:
    """
    Compute the L2-normalized centroid (mean direction vector) of a cluster.

    Args:
        vectors: (K, D) array of member feature vectors.

    Returns:
        1D L2-normalized centroid vector of shape (D,).
    """
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.size == 0:
        return np.zeros(1, dtype=np.float32)

    mean_vec = np.mean(arr, axis=0)
    norm = float(np.linalg.norm(mean_vec))
    if norm > 1e-7:
        mean_vec = mean_vec / norm
    return mean_vec


def evaluate_identity_similarity(
    embedding_a: np.ndarray,
    embedding_b: np.ndarray,
    threshold: float = 0.58,
) -> dict[str, Any]:
    """
    Evaluate similarity between two face embeddings for identity verification.

    Args:
        embedding_a: First face embedding (e.g. 512-dim ArcFace).
        embedding_b: Second face embedding.
        threshold:   Cosine similarity threshold for same-identity decision (default 0.58).

    Returns:
        Dictionary containing:
        - similarity: float cosine similarity [-1.0, 1.0]
        - distance: float cosine distance [0.0, 2.0]
        - is_match: bool True if similarity >= threshold
        - threshold: float threshold used
        - confidence_level: str ("Identical", "Strong Match", "Probable Match", "Borderline", "Divergent")
    """
    sim = cosine_similarity(embedding_a, embedding_b)
    dist = max(0.0, 1.0 - sim)
    is_match = bool(sim >= threshold)

    if sim >= 0.90:
        conf_level = "Identical / Extremely High"
    elif sim >= 0.75:
        conf_level = "Strong Match"
    elif sim >= threshold:
        conf_level = "Probable Match"
    elif sim >= threshold - 0.10:
        conf_level = "Borderline / Ambiguous"
    else:
        conf_level = "Divergent / Different Identity"

    return {
        "similarity": round(sim, 4),
        "distance": round(dist, 4),
        "is_match": is_match,
        "threshold": round(threshold, 4),
        "confidence_level": conf_level,
    }


def compute_cluster_similarity_breakdown(
    vectors: np.ndarray,
    labels: np.ndarray,
) -> dict[str, Any]:
    """
    Compute full intra-cluster and inter-cluster cosine similarity breakdown.

    Args:
        vectors: (N, D) float array of feature vectors.
        labels:  (N,) array of integer cluster labels (-1 is noise).

    Returns:
        Dict with:
        - intra_similarities: dict[label -> mean intra-cluster similarity]
        - min_intra_similarities: dict[label -> min pairwise similarity]
        - max_intra_similarities: dict[label -> max pairwise similarity]
        - std_intra_similarities: dict[label -> standard deviation]
        - centroids: dict[label -> 1D centroid vector]
        - centroid_similarities: dict[label -> mean similarity to centroid]
        - inter_cluster_similarity: mean cosine similarity between cluster centroids
        - member_similarities_to_centroid: list of similarity to centroid for each vector index
    """
    unique_labels = sorted(set(labels) - {-1})
    intra_sims: dict[int, float] = {}
    min_intra_sims: dict[int, float] = {}
    max_intra_sims: dict[int, float] = {}
    std_intra_sims: dict[int, float] = {}
    centroids: dict[int, np.ndarray] = {}
    centroid_sims: dict[int, float] = {}

    n_samples = len(vectors)
    member_sims_to_centroid: list[float] = [1.0] * n_samples

    for lbl in unique_labels:
        mask = labels == lbl
        indices = np.where(mask)[0]
        c_vecs = vectors[mask]
        k = len(c_vecs)

        if k == 0:
            continue

        c_centroid = compute_cluster_centroid(c_vecs)
        centroids[int(lbl)] = c_centroid

        # Similarities of each cluster member to the centroid
        if k == 1:
            intra_sims[int(lbl)] = 1.0
            min_intra_sims[int(lbl)] = 1.0
            max_intra_sims[int(lbl)] = 1.0
            std_intra_sims[int(lbl)] = 0.0
            centroid_sims[int(lbl)] = 1.0
            member_sims_to_centroid[indices[0]] = 1.0
        else:
            # Pairwise similarity matrix inside cluster
            sim_mat = cosine_similarity_matrix(c_vecs)
            triu_idx = np.triu_indices(k, k=1)
            pairwise_sims = sim_mat[triu_idx]

            if len(pairwise_sims) > 0:
                intra_sims[int(lbl)] = float(np.mean(pairwise_sims))
                min_intra_sims[int(lbl)] = float(np.min(pairwise_sims))
                max_intra_sims[int(lbl)] = float(np.max(pairwise_sims))
                std_intra_sims[int(lbl)] = float(np.std(pairwise_sims))
            else:
                intra_sims[int(lbl)] = 1.0
                min_intra_sims[int(lbl)] = 1.0
                max_intra_sims[int(lbl)] = 1.0
                std_intra_sims[int(lbl)] = 0.0

            # Member-to-centroid similarities
            to_centroid = np.dot(c_vecs, c_centroid)
            to_centroid = np.clip(to_centroid, -1.0, 1.0)
            centroid_sims[int(lbl)] = float(np.mean(to_centroid))

            for local_idx, orig_idx in enumerate(indices):
                member_sims_to_centroid[orig_idx] = float(to_centroid[local_idx])

    # For noise points, similarity to nearest centroid or 0.0
    noise_indices = np.where(labels == -1)[0]
    if len(noise_indices) > 0 and len(centroids) > 0:
        all_centroids = np.vstack(list(centroids.values()))
        noise_vecs = vectors[noise_indices]
        noise_to_centroids = cosine_similarity_matrix(noise_vecs, all_centroids)
        max_sims_per_noise = np.max(noise_to_centroids, axis=1)
        for sub_i, orig_idx in enumerate(noise_indices):
            member_sims_to_centroid[orig_idx] = float(max_sims_per_noise[sub_i])

    # Inter-cluster centroid separation / similarity
    if len(centroids) >= 2:
        centroid_matrix = np.vstack(list(centroids.values()))
        c_sim_mat = cosine_similarity_matrix(centroid_matrix)
        c_triu = np.triu_indices(len(centroids), k=1)
        inter_sim = float(np.mean(c_sim_mat[c_triu]))
    else:
        inter_sim = 0.0

    return {
        "intra_similarities": intra_sims,
        "min_intra_similarities": min_intra_sims,
        "max_intra_similarities": max_intra_sims,
        "std_intra_similarities": std_intra_sims,
        "centroids": centroids,
        "centroid_similarities": centroid_sims,
        "inter_cluster_similarity": round(inter_sim, 4),
        "member_similarities_to_centroid": member_sims_to_centroid,
    }
