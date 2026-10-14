"""
Unit test suite for mathematical vector similarity calculations.
Validates 1-to-1, 1-to-N, and pairwise cosine matrix computations, zero-magnitude guards, and normalized centroid calculations.
Handles mathematical boundary conditions, L2 normalization precision, and identity comparison metric tests.
"""

import sys
import unittest
from pathlib import Path
import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.face_detector import DetectedFace
from core.similarity import (
    cosine_similarity,
    cosine_distance,
    cosine_similarity_matrix,
    cosine_distance_matrix,
    compute_cluster_centroid,
    evaluate_identity_similarity,
    compute_cluster_similarity_breakdown,
)
from core.embedder import compute_embedding_similarity, evaluate_face_pair
from core.clusterer import FaceClusterer, ClusterStats
from core.reporter import ReportGenerator
from core.organizer import OrganizationResult


class TestCosineSimilarityEngine(unittest.TestCase):
    """Test mathematical precision and boundary guards in core/similarity.py."""

    def test_identical_vectors(self):
        v1 = np.array([0.6, 0.8], dtype=np.float32)
        v2 = np.array([0.6, 0.8], dtype=np.float32)
        sim = cosine_similarity(v1, v2)
        self.assertAlmostEqual(sim, 1.0, places=5)
        dist = cosine_distance(v1, v2)
        self.assertAlmostEqual(dist, 0.0, places=5)

    def test_orthogonal_vectors(self):
        v1 = np.array([1.0, 0.0], dtype=np.float32)
        v2 = np.array([0.0, 1.0], dtype=np.float32)
        sim = cosine_similarity(v1, v2)
        self.assertAlmostEqual(sim, 0.0, places=5)
        dist = cosine_distance(v1, v2)
        self.assertAlmostEqual(dist, 1.0, places=5)

    def test_opposite_vectors(self):
        v1 = np.array([1.0, 0.0], dtype=np.float32)
        v2 = np.array([-1.0, 0.0], dtype=np.float32)
        sim = cosine_similarity(v1, v2)
        self.assertAlmostEqual(sim, -1.0, places=5)
        dist = cosine_distance(v1, v2)
        self.assertAlmostEqual(dist, 2.0, places=5)

    def test_zero_vector_handling(self):
        v1 = np.zeros(512, dtype=np.float32)
        v2 = np.random.randn(512).astype(np.float32)
        sim = cosine_similarity(v1, v2)
        self.assertEqual(sim, 0.0)

    def test_empty_or_none_vector_handling(self):
        self.assertEqual(cosine_similarity(None, np.array([1.0, 2.0])), 0.0)
        self.assertEqual(cosine_similarity(np.array([]), np.array([1.0, 2.0])), 0.0)
        self.assertEqual(cosine_similarity(np.array([1.0]), np.array([1.0, 2.0])), 0.0)

    def test_512_dim_arcface_embedding_similarity(self):
        rng = np.random.RandomState(42)
        # Create two slightly perturbed embeddings
        base = rng.randn(512).astype(np.float32)
        base /= np.linalg.norm(base)

        noise = rng.randn(512).astype(np.float32)
        noise /= np.linalg.norm(noise)
        pert = base + noise * 0.08
        pert /= np.linalg.norm(pert)

        sim = cosine_similarity(base, pert)
        self.assertGreater(sim, 0.95)
        self.assertLessEqual(sim, 1.0)

    def test_similarity_matrix(self):
        rng = np.random.RandomState(42)
        a = rng.randn(5, 512).astype(np.float32)
        a /= np.linalg.norm(a, axis=1, keepdims=True)

        sim_mat = cosine_similarity_matrix(a)
        self.assertEqual(sim_mat.shape, (5, 5))
        # Diagonal elements must be 1.0
        np.testing.assert_allclose(np.diag(sim_mat), np.ones(5), atol=1e-5)

        dist_mat = cosine_distance_matrix(a)
        np.testing.assert_allclose(dist_mat, 1.0 - sim_mat, atol=1e-5)

    def test_centroid_computation(self):
        v1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        v2 = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        vecs = np.vstack([v1, v2])
        centroid = compute_cluster_centroid(vecs)
        self.assertEqual(centroid.shape, (3,))
        self.assertAlmostEqual(float(np.linalg.norm(centroid)), 1.0, places=5)
        self.assertAlmostEqual(float(centroid[0]), float(centroid[1]), places=5)

    def test_evaluate_identity_similarity(self):
        v1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        v2 = np.array([0.9, 0.1, 0.0], dtype=np.float32)
        v2 /= np.linalg.norm(v2)

        res = evaluate_identity_similarity(v1, v2, threshold=0.58)
        self.assertTrue(res["is_match"])
        self.assertGreater(res["similarity"], 0.80)
        self.assertIn("confidence_level", res)

    def test_cluster_similarity_breakdown(self):
        rng = np.random.RandomState(123)
        # 3 clusters of 4 points each
        c1 = rng.randn(4, 32).astype(np.float32) + np.array([10.0] * 32)
        c2 = rng.randn(4, 32).astype(np.float32) + np.array([-10.0] * 32)
        c3 = rng.randn(2, 32).astype(np.float32) + np.array([0.0] * 32)

        vecs = np.vstack([c1, c2, c3])
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        labels = np.array([0, 0, 0, 0, 1, 1, 1, 1, -1, -1])

        breakdown = compute_cluster_similarity_breakdown(vecs, labels)
        self.assertIn(0, breakdown["intra_similarities"])
        self.assertIn(1, breakdown["intra_similarities"])
        self.assertGreater(breakdown["intra_similarities"][0], 0.80)
        self.assertGreater(breakdown["intra_similarities"][1], 0.80)
        self.assertIn("min_intra_similarities", breakdown)
        self.assertIn("max_intra_similarities", breakdown)
        self.assertIn("centroid_similarities", breakdown)
        self.assertEqual(len(breakdown["member_similarities_to_centroid"]), 10)


class TestClusteringIntegration(unittest.TestCase):
    """Test clustering integration with cosine similarity assignments."""

    def test_cluster_faces_assigns_similarity(self):
        rng = np.random.RandomState(42)

        faces = []
        # Person 1: 3 faces
        p1_base = rng.randn(512).astype(np.float32)
        p1_base /= np.linalg.norm(p1_base)
        for i in range(3):
            noise = rng.randn(512).astype(np.float32)
            noise /= np.linalg.norm(noise)
            v = p1_base + noise * 0.05
            v /= np.linalg.norm(v)
            face = DetectedFace(
                image_path=Path(f"test_p1_{i}.jpg"),
                face_index=0,
                bbox=[10.0, 10.0, 100.0, 100.0],
                landmarks=np.zeros((5, 2)),
                confidence=0.99,
                aligned_face=np.zeros((112, 112, 3), dtype=np.uint8),
                image_shape=(800, 600),
                fused_vector=v,
                embedding=v[:512],
            )
            faces.append(face)

        # Person 2: 3 faces
        p2_base = rng.randn(512).astype(np.float32)
        p2_base /= np.linalg.norm(p2_base)
        for i in range(3):
            noise = rng.randn(512).astype(np.float32)
            noise /= np.linalg.norm(noise)
            v = p2_base + noise * 0.05
            v /= np.linalg.norm(v)
            face = DetectedFace(
                image_path=Path(f"test_p2_{i}.jpg"),
                face_index=0,
                bbox=[20.0, 20.0, 120.0, 120.0],
                landmarks=np.zeros((5, 2)),
                confidence=0.98,
                aligned_face=np.zeros((112, 112, 3), dtype=np.uint8),
                image_shape=(800, 600),
                fused_vector=v,
                embedding=v[:512],
            )
            faces.append(face)

        clusterer = FaceClusterer(eps=0.42, min_samples=2)
        clustered_faces, stats = clusterer.cluster(faces)

        self.assertEqual(stats.n_clusters, 2)
        self.assertEqual(stats.n_noise, 0)

        # Ensure every face received a cosine similarity score
        for f in clustered_faces:
            self.assertIsNotNone(f.cosine_similarity)
            self.assertGreater(f.cosine_similarity, 0.85)
            self.assertIsNotNone(f.similarity_to_centroid)

        # Ensure ClusterStats contains similarity fields
        self.assertIn(0, stats.min_intra_similarities)
        self.assertIn(0, stats.max_intra_similarities)
        self.assertIn(0, stats.centroid_similarities)
        self.assertIsNotNone(stats.inter_cluster_similarity)


class TestReporterIntegration(unittest.TestCase):
    """Test report generation with cosine similarity metrics."""

    def test_report_generation(self, tmp_path=None):
        import tempfile
        import json

        rng = np.random.RandomState(99)
        faces = []
        p1 = rng.randn(512).astype(np.float32)
        p1 /= np.linalg.norm(p1)

        for i in range(2):
            face = DetectedFace(
                image_path=Path(f"img_{i}.jpg"),
                face_index=0,
                bbox=[0, 0, 50, 50],
                landmarks=np.zeros((5, 2)),
                confidence=0.99,
                aligned_face=np.zeros((112, 112, 3), dtype=np.uint8),
                image_shape=(400, 400),
                fused_vector=p1,
                embedding=p1,
                cluster_label=0,
                cosine_similarity=0.985,
                similarity_to_centroid=0.985,
            )
            faces.append(face)

        stats = ClusterStats(
            n_clusters=1,
            n_noise=0,
            n_total=2,
            silhouette_score=None,
            intra_similarities={0: 0.985},
            cluster_sizes={0: 2},
            clustering_time_s=0.01,
            min_intra_similarities={0: 0.985},
            max_intra_similarities={0: 0.985},
            centroid_similarities={0: 0.985},
            inter_cluster_similarity=0.0,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "clusters.json"
            org_res = OrganizationResult(
                output_root=Path(tmp_dir),
                person_folders={0: Path(tmp_dir) / "Person001"},
                copies_made=2,
                images_per_cluster={0: ["img_0.jpg", "img_1.jpg"]},
            )

            reporter = ReportGenerator()
            written = reporter.generate(
                faces=faces,
                stats=stats,
                org_result=org_res,
                total_images=2,
                total_time_s=1.0,
                output_path=out_path,
            )

            self.assertTrue(written.exists())
            with open(written, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Validate metadata
            self.assertIn("avg_intra_cluster_similarity", data["metadata"])
            self.assertEqual(data["metadata"]["avg_intra_cluster_similarity"], 0.985)

            # Validate cluster breakdown
            c0 = data["clusters"][0]
            self.assertEqual(c0["avg_intra_cluster_similarity"], 0.985)
            self.assertEqual(c0["min_intra_cluster_similarity"], 0.985)
            self.assertEqual(c0["max_intra_cluster_similarity"], 0.985)

            # Validate detection
            d0 = c0["detections"][0]
            self.assertIn("cosine_similarity", d0)
            self.assertEqual(d0["cosine_similarity"], 0.985)


if __name__ == "__main__":
    unittest.main()
