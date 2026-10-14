"""
Clustering confidence evaluation and cluster quality validation test module.
Runs the complete vision pipeline on photo sets to compute Silhouette scores, Davies-Bouldin metrics, and centroid distances.
Handles mathematical cluster quality evaluation, intra-to-inter identity separation metrics, and t-SNE projection generation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Add project root to path so imports work when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend (safe for all environments)
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from sklearn.manifold import TSNE
from sklearn.metrics import (
    silhouette_score,
    davies_bouldin_score,
    calinski_harabasz_score,
)
from sklearn.preprocessing import normalize

import config
from app import run_pipeline
from core.face_detector import FaceDetector, DetectedFace
from core.embedder import FaceEmbedder
from core.feature_extractor import FeatureExtractor
from core.feature_fusion import FeatureFusion
from core.clusterer import FaceClusterer, ClusterStats
from core.similarity import (
    cosine_similarity,
    cosine_distance,
    cosine_similarity_matrix,
    compute_cluster_centroid,
    compute_cluster_similarity_breakdown,
)
from utils.image_utils import get_image_files, load_image_rgb
from utils.logging_utils import setup_logging, get_logger

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse arguments for the confidence test script."""
    parser = argparse.ArgumentParser(
        description="Confidence & quality testing for Photo Clustering System",
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=config.INPUT_FOLDER,
        help="Input folder with photos",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=config.OUTPUT_FOLDER,
        help="Output folder",
    )
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="Skip t-SNE visualization (faster for large datasets)",
    )
    parser.add_argument(
        "--tsne-perplexity",
        type=float,
        default=30.0,
        help="t-SNE perplexity (default: 30)",
    )
    return parser.parse_args()


class ConfidenceTester:
    """
    Evaluates the quality and confidence of the clustering pipeline.

    Runs the pipeline, collects all embeddings and cluster labels,
    then computes multiple quality metrics and generates visualizations.

    Usage::

        tester = ConfidenceTester()
        report = tester.run(input_folder, output_folder)
    """

    def run(
        self,
        input_folder: Path,
        output_folder: Path,
        generate_plot: bool = True,
        tsne_perplexity: float = 30.0,
    ) -> dict:
        """
        Execute the confidence test.

        Args:
            input_folder:    Input photo directory.
            output_folder:   Output directory (will be created).
            generate_plot:   Whether to generate the t-SNE plot.
            tsne_perplexity: t-SNE perplexity parameter.

        Returns:
            Full confidence report as a dict.
        """
        logger.info("=" * 60)
        logger.info("CONFIDENCE TEST — Starting pipeline")
        logger.info("=" * 60)

        t_start = time.perf_counter()

        # ── Run pipeline to get cluster data ─────────────────────────────────
        all_faces = self._run_pipeline_internal(input_folder, output_folder)

        if not all_faces:
            logger.error("No faces detected. Cannot compute confidence metrics.")
            return {"error": "No faces detected"}

        # Filter faces with valid embeddings and cluster labels
        valid_faces = [
            f for f in all_faces
            if f.fused_vector.size > 1 and f.cluster_label != -2
        ]

        if len(valid_faces) < 2:
            logger.error("Too few valid faces for confidence metrics.")
            return {"error": "Too few valid faces"}

        vectors = normalize(
            np.vstack([f.fused_vector for f in valid_faces]),
            norm="l2"
        ).astype(np.float64)
        labels = np.array([f.cluster_label for f in valid_faces])

        # ── Compute metrics ───────────────────────────────────────────────────
        logger.info("Computing cluster quality metrics...")
        metrics = self._compute_metrics(vectors, labels)

        # ── Per-cluster analysis ──────────────────────────────────────────────
        per_cluster = self._per_cluster_analysis(valid_faces, vectors, labels)

        # ── t-SNE visualization ───────────────────────────────────────────────
        plot_path: str | None = None
        if generate_plot and len(valid_faces) >= 4:
            plot_path = self._generate_tsne_plot(
                vectors, labels, valid_faces, tsne_perplexity, output_folder
            )

        total_time = time.perf_counter() - t_start

        # ── Assemble report ───────────────────────────────────────────────────
        report = self._build_report(
            all_faces, valid_faces, metrics, per_cluster,
            total_time, plot_path
        )

        # ── Write report ──────────────────────────────────────────────────────
        report_path = output_folder / config.CONFIDENCE_REPORT_PATH.name
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"Confidence report written → {report_path}")
        self._print_summary(report)

        return report

    def _run_pipeline_internal(
        self,
        input_folder: Path,
        output_folder: Path,
    ) -> list[DetectedFace]:
        """
        Run the detection + embedding + feature + clustering steps
        and return all DetectedFace objects with labels set.

        This replicates the pipeline but returns internal state
        instead of just file system outputs.
        """
        image_paths = get_image_files(input_folder)
        if not image_paths:
            return []

        detector = FaceDetector()
        embedder = FaceEmbedder()
        extractor = FeatureExtractor()
        fusion = FeatureFusion()
        clusterer = FaceClusterer()

        all_faces: list[DetectedFace] = []

        from tqdm import tqdm
        for image_path in tqdm(image_paths, desc="Processing (confidence test)", unit="img"):
            image_rgb = load_image_rgb(image_path)
            if image_rgb is None:
                continue
            faces = detector.detect_faces(image_rgb, image_path)
            if not faces:
                continue
            faces = embedder.extract_batch(faces)
            faces = extractor.extract_all(faces, image_rgb)
            faces = fusion.fuse_all(faces)
            all_faces.extend(faces)

        if not all_faces:
            return []

        all_faces, _ = clusterer.cluster(all_faces)
        return all_faces

    def _compute_metrics(
        self,
        vectors: np.ndarray,
        labels: np.ndarray,
    ) -> dict:
        """
        Compute global cluster quality metrics.

        Args:
            vectors: ``(N, D)`` L2-normalized fused vectors.
            labels:  Cluster labels for each vector.

        Returns:
            Dict of metric name → value.
        """
        metrics: dict[str, float | None] = {}

        unique_labels = set(labels)
        n_clusters = len(unique_labels - {-1})
        n_noise = int(np.sum(labels == -1))

        metrics["n_faces_total"] = float(len(labels))
        metrics["n_clusters"] = float(n_clusters)
        metrics["n_noise_faces"] = float(n_noise)
        metrics["noise_ratio"] = round(n_noise / max(len(labels), 1), 4)

        # Non-noise subset
        mask = labels != -1
        non_noise_vectors = vectors[mask]
        non_noise_labels = labels[mask]

        if n_clusters >= 2 and len(non_noise_vectors) >= 2:
            try:
                metrics["silhouette_score"] = round(
                    float(silhouette_score(non_noise_vectors, non_noise_labels, metric="cosine")),
                    4,
                )
            except Exception as e:
                logger.warning(f"Silhouette failed: {e}")
                metrics["silhouette_score"] = None

            try:
                metrics["davies_bouldin_index"] = round(
                    float(davies_bouldin_score(non_noise_vectors, non_noise_labels)),
                    4,
                )
            except Exception as e:
                logger.warning(f"Davies-Bouldin failed: {e}")
                metrics["davies_bouldin_index"] = None

            try:
                metrics["calinski_harabasz_score"] = round(
                    float(calinski_harabasz_score(non_noise_vectors, non_noise_labels)),
                    4,
                )
            except Exception as e:
                logger.warning(f"Calinski-Harabasz failed: {e}")
                metrics["calinski_harabasz_score"] = None

            # Inter-cluster centroid separation and similarity
            inter_dist, inter_sim = self._compute_inter_cluster_separation_and_sim(
                non_noise_vectors, non_noise_labels
            )
            metrics["avg_inter_cluster_separation"] = round(float(inter_dist), 4)
            metrics["avg_inter_cluster_similarity"] = round(float(inter_sim), 4)

            # Intra-cluster cosine similarity summary
            sim_data = compute_cluster_similarity_breakdown(vectors, labels)
            intra_sims = list(sim_data["intra_similarities"].values())
            metrics["avg_intra_cluster_similarity"] = (
                round(float(np.mean(intra_sims)), 4) if intra_sims else 1.0
            )
        else:
            sim_data = compute_cluster_similarity_breakdown(vectors, labels)
            intra_sims = list(sim_data["intra_similarities"].values())
            metrics["avg_intra_cluster_similarity"] = (
                round(float(np.mean(intra_sims)), 4) if intra_sims else 1.0
            )
            metrics["avg_inter_cluster_similarity"] = None
            for key in [
                "silhouette_score", "davies_bouldin_index",
                "calinski_harabasz_score", "avg_inter_cluster_separation"
            ]:
                metrics[key] = None

        return metrics

    def _compute_inter_cluster_separation_and_sim(
        self,
        vectors: np.ndarray,
        labels: np.ndarray,
    ) -> tuple[float, float]:
        """
        Compute mean cosine distance and mean cosine similarity between cluster centroids.

        Args:
            vectors: Non-noise fused vectors.
            labels:  Corresponding cluster labels.

        Returns:
            Tuple of (mean inter-centroid cosine distance, mean inter-centroid cosine similarity).
        """
        unique_labels = sorted(set(labels))
        if len(unique_labels) < 2:
            return 0.0, 0.0

        centroids = []
        for lbl in unique_labels:
            mask = labels == lbl
            centroids.append(compute_cluster_centroid(vectors[mask]))

        centroid_matrix = np.vstack(centroids)
        sim_mat = cosine_similarity_matrix(centroid_matrix)
        triu_idx = np.triu_indices(len(centroids), k=1)
        sims = sim_mat[triu_idx]

        inter_sim = float(np.mean(sims)) if len(sims) > 0 else 0.0
        inter_dist = float(np.mean(1.0 - sims)) if len(sims) > 0 else 0.0
        return inter_dist, inter_sim

    def _per_cluster_analysis(
        self,
        faces: list[DetectedFace],
        vectors: np.ndarray,
        labels: np.ndarray,
    ) -> list[dict]:
        """
        Compute per-cluster quality and cosine similarity metrics.

        Args:
            faces:   Valid faces with cluster labels.
            vectors: Fused vector matrix.
            labels:  Label array.

        Returns:
            List of per-cluster metric dicts.
        """
        sim_breakdown = compute_cluster_similarity_breakdown(vectors, labels)
        intra_sims = sim_breakdown["intra_similarities"]
        min_sims = sim_breakdown["min_intra_similarities"]
        max_sims = sim_breakdown["max_intra_similarities"]
        std_sims = sim_breakdown["std_intra_similarities"]
        centroid_sims = sim_breakdown["centroid_similarities"]

        per_cluster = []
        unique_labels = sorted(set(labels))

        for lbl in unique_labels:
            mask = labels == lbl
            cluster_faces = [f for f in faces if f.cluster_label == lbl]

            unique_images = list(set(f.image_path.name for f in cluster_faces))
            avg_confidence = float(np.mean([f.confidence for f in cluster_faces])) if cluster_faces else 1.0

            intra_sim_mean = round(float(intra_sims.get(int(lbl), 1.0)), 4)
            intra_sim_min = round(float(min_sims.get(int(lbl), intra_sim_mean)), 4)
            intra_sim_max = round(float(max_sims.get(int(lbl), intra_sim_mean)), 4)
            intra_sim_std = round(float(std_sims.get(int(lbl), 0.0)), 4)
            c_sim = round(float(centroid_sims.get(int(lbl), intra_sim_mean)), 4)

            label_name = (
                f"{config.PERSON_FOLDER_PREFIX}{lbl + 1:03d}"
                if lbl >= 0
                else config.UNKNOWN_FOLDER_NAME
            )

            per_cluster.append({
                "cluster_id": label_name,
                "cluster_label": int(lbl),
                "face_count": int(mask.sum()),
                "image_count": len(unique_images),
                "images": sorted(unique_images),
                "avg_detection_confidence": round(avg_confidence, 4),
                "avg_intra_cluster_similarity": intra_sim_mean,
                "centroid_similarity": c_sim,
                "intra_cluster_similarity": {
                    "mean": intra_sim_mean,
                    "min": intra_sim_min,
                    "max": intra_sim_max,
                    "std": intra_sim_std,
                },
            })

        return sorted(per_cluster, key=lambda c: c["face_count"], reverse=True)

    def _generate_tsne_plot(
        self,
        vectors: np.ndarray,
        labels: np.ndarray,
        faces: list[DetectedFace],
        perplexity: float,
        output_folder: Path,
    ) -> str | None:
        """
        Generate a t-SNE 2D visualization of the fused embeddings.

        Each point is a detected face. Color = cluster label.
        Unknown faces (label -1) are shown as grey ×.

        Args:
            vectors:       ``(N, D)`` L2-normalized vectors.
            labels:        Cluster label array.
            faces:         Face list for filename labels.
            perplexity:    t-SNE perplexity.
            output_folder: Where to save the PNG.

        Returns:
            Absolute path to the saved plot, or None on failure.
        """
        try:
            logger.info("Generating t-SNE visualization (this may take a minute)...")

            # Adjust perplexity for small datasets
            n_samples = len(vectors)
            actual_perplexity = min(perplexity, max(2.0, n_samples / 4))

            tsne = TSNE(
                n_components=2,
                perplexity=actual_perplexity,
                random_state=42,
                n_iter=1000,
                metric="cosine",
            )
            coords_2d = tsne.fit_transform(vectors.astype(np.float32))

            unique_labels = sorted(set(labels))
            n_real_clusters = len([l for l in unique_labels if l >= 0])

            # Color palette
            cmap = plt.cm.get_cmap("tab20", max(n_real_clusters, 1))
            color_map = {lbl: cmap(i) for i, lbl in enumerate(l for l in unique_labels if l >= 0)}
            color_map[-1] = (0.5, 0.5, 0.5, 0.6)  # grey for unknown

            fig, ax = plt.subplots(figsize=(14, 10))
            ax.set_facecolor("#1a1a2e")
            fig.patch.set_facecolor("#16213e")

            # Plot each cluster
            for lbl in unique_labels:
                mask = labels == lbl
                pts = coords_2d[mask]
                color = color_map[lbl]

                if lbl == -1:
                    ax.scatter(
                        pts[:, 0], pts[:, 1],
                        c=[color], marker="x", s=60, linewidths=1.5,
                        label=f"Unknown ({mask.sum()})", zorder=2,
                        alpha=0.7,
                    )
                else:
                    label_name = f"Person{lbl + 1:03d} ({mask.sum()})"
                    ax.scatter(
                        pts[:, 0], pts[:, 1],
                        c=[color], s=80, edgecolors="white",
                        linewidths=0.5, label=label_name, zorder=3, alpha=0.9,
                    )
                    # Cluster centroid marker
                    centroid = pts.mean(axis=0)
                    ax.scatter(
                        [centroid[0]], [centroid[1]],
                        c=[color], s=250, marker="*",
                        edgecolors="white", linewidths=1.5, zorder=5,
                    )

            ax.set_title(
                "t-SNE Visualization — Face Identity Clusters",
                color="white", fontsize=16, fontweight="bold", pad=20,
            )
            ax.set_xlabel("t-SNE Dimension 1", color="#aaaaaa", fontsize=12)
            ax.set_ylabel("t-SNE Dimension 2", color="#aaaaaa", fontsize=12)
            ax.tick_params(colors="#aaaaaa")
            for spine in ax.spines.values():
                spine.set_edgecolor("#444466")

            legend = ax.legend(
                loc="upper right", framealpha=0.3,
                labelcolor="white", fontsize=9,
                facecolor="#2a2a4a",
            )

            # Metrics annotation
            sil_str = "N/A"
            try:
                mask_non_noise = labels != -1
                if mask_non_noise.sum() >= 2 and len(set(labels[mask_non_noise])) >= 2:
                    sil = silhouette_score(
                        vectors[mask_non_noise], labels[mask_non_noise], metric="cosine"
                    )
                    sil_str = f"{sil:.3f}"
            except Exception:
                pass

            annotation = (
                f"Faces: {len(labels)} | "
                f"Clusters: {n_real_clusters} | "
                f"Silhouette: {sil_str}"
            )
            ax.text(
                0.02, 0.02, annotation,
                transform=ax.transAxes,
                color="#cccccc", fontsize=10,
                bbox=dict(boxstyle="round,pad=0.4", facecolor="#2a2a4a", alpha=0.6),
            )

            plt.tight_layout()

            plot_path = output_folder / config.TSNE_PLOT_PATH.name
            plot_path.parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(str(plot_path), dpi=150, bbox_inches="tight")
            plt.close(fig)

            logger.info(f"t-SNE plot saved → {plot_path}")
            return str(plot_path)

        except Exception as exc:
            logger.warning(f"t-SNE plot generation failed: {exc}")
            return None

    def _build_report(
        self,
        all_faces: list[DetectedFace],
        valid_faces: list[DetectedFace],
        metrics: dict,
        per_cluster: list[dict],
        total_time: float,
        plot_path: str | None,
    ) -> dict:
        """Assemble the final confidence report dictionary."""
        from datetime import datetime

        return {
            "test_metadata": {
                "timestamp": datetime.now().isoformat(),
                "total_faces_detected": len(all_faces),
                "valid_faces_evaluated": len(valid_faces),
                "test_duration_seconds": round(total_time, 3),
                "tsne_plot": plot_path,
            },
            "global_metrics": metrics,
            "interpretation": self._interpret_metrics(metrics),
            "per_cluster_analysis": per_cluster,
        }

    def _interpret_metrics(self, metrics: dict) -> dict:
        """
        Provide human-readable interpretation of the quality metrics.

        Args:
            metrics: Global metrics dict.

        Returns:
            Dict with qualitative interpretation strings.
        """
        interpretation = {}

        sil = metrics.get("silhouette_score")
        if sil is not None:
            if sil >= 0.7:
                interpretation["silhouette"] = "Excellent — clusters are very well separated"
            elif sil >= 0.5:
                interpretation["silhouette"] = "Good — clusters are reasonably separated"
            elif sil >= 0.25:
                interpretation["silhouette"] = "Fair — some overlap between identities"
            else:
                interpretation["silhouette"] = (
                    "Poor — consider adjusting DBSCAN_EPS or face image quality"
                )

        db = metrics.get("davies_bouldin_index")
        if db is not None:
            if db <= 0.5:
                interpretation["davies_bouldin"] = "Excellent — low scatter relative to separation"
            elif db <= 1.0:
                interpretation["davies_bouldin"] = "Good — acceptable cluster structure"
            else:
                interpretation["davies_bouldin"] = (
                    "Poor — clusters have high intra-scatter or low inter-separation"
                )

        noise_ratio = metrics.get("noise_ratio", 0)
        if noise_ratio > 0.3:
            interpretation["noise_ratio"] = (
                f"High noise rate ({noise_ratio:.1%}) — "
                "try lowering DBSCAN_EPS or DBSCAN_MIN_SAMPLES"
            )
        elif noise_ratio > 0.1:
            interpretation["noise_ratio"] = (
                f"Moderate noise rate ({noise_ratio:.1%}) — acceptable"
            )
        else:
            interpretation["noise_ratio"] = (
                f"Low noise rate ({noise_ratio:.1%}) — good"
            )

        return interpretation

    def _print_summary(self, report: dict) -> None:
        """Print a formatted confidence test summary to stdout."""
        g = report.get("global_metrics", {})
        interp = report.get("interpretation", {})

        print("\n" + "=" * 60)
        print("  CONFIDENCE TEST RESULTS")
        print("=" * 60)
        print(f"  Faces detected       : {int(g.get('n_faces_total', 0))}")
        print(f"  Clusters found       : {int(g.get('n_clusters', 0))}")
        print(f"  Noise faces          : {int(g.get('n_noise_faces', 0))}")

        sil = g.get("silhouette_score")
        db = g.get("davies_bouldin_index")
        ch = g.get("calinski_harabasz_score")
        sep = g.get("avg_inter_cluster_separation")
        intra_sim = g.get("avg_intra_cluster_similarity")
        inter_sim = g.get("avg_inter_cluster_similarity")

        print(f"\n  QUALITY METRICS:")
        print(f"  Intra-Cluster Sim.   : {intra_sim if intra_sim is not None else 'N/A'}")
        print(f"  Inter-Cluster Sim.   : {inter_sim if inter_sim is not None else 'N/A'}")
        print(f"  Silhouette Score     : {sil if sil is not None else 'N/A (need 2+ clusters)'}")
        print(f"  Davies-Bouldin Index : {db if db is not None else 'N/A'}")
        print(f"  Calinski-Harabasz    : {ch if ch is not None else 'N/A'}")
        print(f"  Inter-cluster Sep.   : {sep if sep is not None else 'N/A'}")

        if interp:
            print(f"\n  INTERPRETATION:")
            for key, msg in interp.items():
                print(f"  [{key}] {msg}")

        plot = report.get("test_metadata", {}).get("tsne_plot")
        if plot:
            print(f"\n  t-SNE Plot           : {plot}")

        print("=" * 60)


def main() -> None:
    """Parse arguments and run the confidence test."""
    args = parse_args()

    log_file = args.output / "confidence_test.log"
    setup_logging(log_file=log_file, debug=True)

    logger.info("Confidence Test — School Event Photo Clustering System")

    tester = ConfidenceTester()
    tester.run(
        input_folder=args.input,
        output_folder=args.output,
        generate_plot=not args.no_plot,
        tsne_perplexity=args.tsne_perplexity,
    )


if __name__ == "__main__":
    main()
