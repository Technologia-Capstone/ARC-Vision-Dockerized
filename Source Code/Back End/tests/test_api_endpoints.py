"""
Integration test suite for FastAPI REST API endpoints.
Validates system status, health checks, event queries, cluster detail endpoints, and identity similarity evaluations.
Handles HTTP response code assertions, payload integrity tests, and API error response verification.
"""

import sys
import unittest
from pathlib import Path
import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server
from server import (
    api_health,
    evaluate_similarity_endpoint,
    list_reports,
    export_reports_download,
    get_event_clusters,
    get_cluster_similarity,
)


class TestApiSimilarityEndpoints(unittest.TestCase):
    """Test REST API similarity endpoints and report integration."""

    def test_api_health(self):
        data = api_health()
        self.assertEqual(data["status"], "ok")

    def test_evaluate_similarity_identical_vectors(self):
        vec = [0.6, 0.8] + [0.0] * 510
        payload = {
            "vector_a": vec,
            "vector_b": vec,
            "threshold": 0.58
        }
        data = evaluate_similarity_endpoint(payload)
        self.assertEqual(data["status"], "success")
        eval_res = data["evaluation"]
        self.assertAlmostEqual(eval_res["similarity"], 1.0, places=4)
        self.assertAlmostEqual(eval_res["distance"], 0.0, places=4)
        self.assertTrue(eval_res["is_match"])
        self.assertIn("Identical", eval_res["confidence_level"])

    def test_evaluate_similarity_orthogonal_vectors(self):
        vec_a = [1.0, 0.0] + [0.0] * 510
        vec_b = [0.0, 1.0] + [0.0] * 510
        payload = {
            "vector_a": vec_a,
            "vector_b": vec_b,
            "threshold": 0.58
        }
        data = evaluate_similarity_endpoint(payload)
        self.assertEqual(data["status"], "success")
        eval_res = data["evaluation"]
        self.assertAlmostEqual(eval_res["similarity"], 0.0, places=4)
        self.assertAlmostEqual(eval_res["distance"], 1.0, places=4)
        self.assertFalse(eval_res["is_match"])
        self.assertIn("Divergent", eval_res["confidence_level"])

    def test_evaluate_similarity_threshold_decision(self):
        v1 = [1.0, 0.0] + [0.0] * 510
        v2 = [0.7071, 0.7071] + [0.0] * 510
        res_strict = evaluate_similarity_endpoint({"vector_a": v1, "vector_b": v2, "threshold": 0.80})
        self.assertFalse(res_strict["evaluation"]["is_match"])

        res_lenient = evaluate_similarity_endpoint({"vector_a": v1, "vector_b": v2, "threshold": 0.60})
        self.assertTrue(res_lenient["evaluation"]["is_match"])

    def test_list_reports(self):
        data = list_reports()
        self.assertEqual(data["status"], "success")
        self.assertIn("reports", data)

    def test_export_reports_json(self):
        response = export_reports_download(format="json")
        self.assertEqual(response.media_type, "application/json")

    def test_export_reports_csv(self):
        response = export_reports_download(format="csv")
        self.assertEqual(response.media_type, "text/csv")
        body_text = response.body.decode("utf-8")
        self.assertIn("Intra-Cluster Similarity", body_text)

    def test_get_event_clusters_similarity(self):
        data = get_event_clusters("Main Event")
        self.assertIn("person_clusters", data)
        for c in data.get("person_clusters", []):
            self.assertIn("similarity", c)
            self.assertIn("avg_intra_cluster_similarity", c)

    def test_serve_root_and_loading_html(self):
        from server import serve_root, serve_loading
        root_res = serve_root()
        self.assertTrue(str(root_res.path).endswith("loading.html"))
        loading_res = serve_loading()
        self.assertTrue(str(loading_res.path).endswith("loading.html"))

    def test_empty_stats_zero_clusters(self):
        import tempfile
        import config
        from server import get_stats, count_total_face_clusters, scan_events, invalidate_all_caches
        
        orig_in = config.INPUT_FOLDER
        orig_out = config.OUTPUT_FOLDER
        with tempfile.TemporaryDirectory() as tmp_dir:
            config.INPUT_FOLDER = Path(tmp_dir) / "input"
            config.OUTPUT_FOLDER = Path(tmp_dir) / "output"
            config.INPUT_FOLDER.mkdir()
            config.OUTPUT_FOLDER.mkdir()
            try:
                invalidate_all_caches()
                stats = get_stats()
                self.assertEqual(stats["total_images"], 0)
                self.assertEqual(stats["total_clusters"], 0)
                self.assertEqual(stats["new_images_indicator"], "+0")
                self.assertEqual(stats["new_clusters_indicator"], "+0")
                self.assertEqual(len(stats["events"]), 0)
                self.assertEqual(count_total_face_clusters(), 0)
                events_info = scan_events()
                self.assertEqual(len(events_info["events"]), 0)
            finally:
                config.INPUT_FOLDER = orig_in
                config.OUTPUT_FOLDER = orig_out
                invalidate_all_caches()


    def test_save_reports_to_downloads_single_file(self):
        import tempfile
        from server import save_reports_to_downloads
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            orig_home = Path.home
            Path.home = lambda: Path(tmp_dir)
            try:
                res = save_reports_to_downloads(format="csv", event_id="all")
                self.assertEqual(res["status"], "saved")
                downloads_files = list((Path(tmp_dir) / "Downloads").glob("*"))
                self.assertEqual(len(downloads_files), 1, "Exactly one CSV file should be created per export click")
                self.assertTrue(downloads_files[0].name.endswith(".csv"))

                # Test JSON export single file
                res_json = save_reports_to_downloads(format="json", event_id="all")
                self.assertEqual(res_json["status"], "saved")
                all_files = list((Path(tmp_dir) / "Downloads").glob("*"))
                self.assertEqual(len(all_files), 2, "Exactly two files (1 CSV + 1 JSON) in total after 2 distinct export clicks")
            finally:
                Path.home = orig_home


if __name__ == "__main__":
    unittest.main()
