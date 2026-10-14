"""
Unit tests for person cluster merging and directory consolidation.
Tests merging multiple identity clusters into a single destination folder with custom naming.
Handles file retention verification, cluster report synchronization, and Tier 3 photo gallery validation.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import server
from server import (
    merge_clusters,
    get_person_images,
    get_event_clusters,
    invalidate_all_caches,
    _find_cluster_dir,
)


class TestClusterMergeAndPhotoRetrieval(unittest.TestCase):
    """Verify cluster folder merging and image retrieval."""

    def setUp(self):
        # Create a temporary directory structure for testing
        self.test_dir = tempfile.mkdtemp()
        self.orig_input = config.INPUT_FOLDER
        self.orig_output = config.OUTPUT_FOLDER

        config.INPUT_FOLDER = Path(self.test_dir) / "input"
        config.OUTPUT_FOLDER = Path(self.test_dir) / "output"
        config.INPUT_FOLDER.mkdir(parents=True, exist_ok=True)
        config.OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

        invalidate_all_caches()

    def tearDown(self):
        config.INPUT_FOLDER = self.orig_input
        config.OUTPUT_FOLDER = self.orig_output
        shutil.rmtree(self.test_dir, ignore_errors=True)
        invalidate_all_caches()

    def test_merge_two_clusters_into_first_cluster(self):
        event_name = "Event 1"
        event_dir = config.OUTPUT_FOLDER / event_name
        event_dir.mkdir(parents=True, exist_ok=True)

        cluster1 = event_dir / "Person001"
        cluster2 = event_dir / "Person002"
        cluster1.mkdir()
        cluster2.mkdir()

        # Create sample images in cluster 1
        (cluster1 / "photo1.jpg").write_bytes(b"dummy1")
        (cluster1 / "photo2.jpg").write_bytes(b"dummy2")

        # Create sample images in cluster 2
        (cluster2 / "photo3.jpg").write_bytes(b"dummy3")
        (cluster2 / "photo4.jpg").write_bytes(b"dummy4")

        # Create clusters.json
        rep_data = {
            "metadata": {
                "total_images_processed": 4,
                "total_faces_detected": 4,
                "total_clusters": 2,
                "total_unknown_faces": 0,
                "avg_intra_cluster_similarity": 0.9,
                "total_processing_time_seconds": 1.0,
                "clustering_time_seconds": 0.1,
                "silhouette_score": 0.8
            },
            "clusters": [
                {
                    "cluster_id": "Person001",
                    "person_id": "Person001",
                    "cluster_label": 0,
                    "face_count": 2,
                    "image_count": 2,
                    "avg_intra_cluster_similarity": 0.88,
                    "images": ["photo1.jpg", "photo2.jpg"],
                    "detections": [
                        {"image": "photo1.jpg", "face_index": 0, "confidence": 0.95},
                        {"image": "photo2.jpg", "face_index": 0, "confidence": 0.96}
                    ]
                },
                {
                    "cluster_id": "Person002",
                    "person_id": "Person002",
                    "cluster_label": 1,
                    "face_count": 2,
                    "image_count": 2,
                    "avg_intra_cluster_similarity": 0.85,
                    "images": ["photo3.jpg", "photo4.jpg"],
                    "detections": [
                        {"image": "photo3.jpg", "face_index": 0, "confidence": 0.92},
                        {"image": "photo4.jpg", "face_index": 0, "confidence": 0.93}
                    ]
                }
            ]
        }
        with open(event_dir / config.CLUSTERS_JSON_PATH.name, "w", encoding="utf-8") as f:
            json.dump(rep_data, f)

        # Execute merge into Person001
        res = merge_clusters({
            "event_id": event_name,
            "target_cluster_id": "Person001",
            "source_cluster_ids": ["Person001", "Person002"]
        })

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["moved_count"], 2)

        # Verify Person002 was removed from disk
        self.assertFalse(cluster2.exists())
        self.assertTrue(cluster1.exists())

        # Verify all 4 images are in Person001
        target_files = [f.name for f in cluster1.iterdir() if f.is_file() and not f.name.startswith(".")]
        self.assertEqual(len(target_files), 4)
        self.assertIn("photo1.jpg", target_files)
        self.assertIn("photo2.jpg", target_files)
        self.assertIn("photo3.jpg", target_files)
        self.assertIn("photo4.jpg", target_files)

        # Verify get_person_images returns all 4 images
        images_res = get_person_images(event_name, "Person001")
        self.assertEqual(images_res["total_images"], 4)
        self.assertEqual(len(images_res["images"]), 4)
        returned_filenames = [img["filename"] for img in images_res["images"]]
        self.assertIn("photo1.jpg", returned_filenames)
        self.assertIn("photo2.jpg", returned_filenames)
        self.assertIn("photo3.jpg", returned_filenames)
        self.assertIn("photo4.jpg", returned_filenames)

        # Verify clusters.json was updated
        with open(event_dir / config.CLUSTERS_JSON_PATH.name, "r", encoding="utf-8") as f:
            updated_rep = json.load(f)
        self.assertEqual(len(updated_rep["clusters"]), 1)
        self.assertEqual(updated_rep["clusters"][0]["cluster_id"], "Person001")
        self.assertEqual(len(updated_rep["clusters"][0]["images"]), 4)
        self.assertEqual(len(updated_rep["clusters"][0]["detections"]), 4)

    def test_merge_two_clusters_into_new_name(self):
        event_name = "Event 2"
        event_dir = config.OUTPUT_FOLDER / event_name
        event_dir.mkdir(parents=True, exist_ok=True)

        cluster1 = event_dir / "Person001"
        cluster2 = event_dir / "Person002"
        cluster1.mkdir()
        cluster2.mkdir()

        (cluster1 / "imgA.jpg").write_bytes(b"A")
        (cluster2 / "imgB.jpg").write_bytes(b"B")

        # Execute merge into new target name "Alice"
        res = merge_clusters({
            "event_id": event_name,
            "target_cluster_id": "Alice",
            "source_cluster_ids": ["Person001", "Person002"]
        })

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["moved_count"], 2)

        # Verify Person001 and Person002 deleted, Alice created
        self.assertFalse(cluster1.exists())
        self.assertFalse(cluster2.exists())
        alice_dir = event_dir / "Alice"
        self.assertTrue(alice_dir.exists())

        # Verify get_person_images returns both images
        images_res = get_person_images(event_name, "Alice")
        self.assertEqual(images_res["total_images"], 2)
        self.assertEqual(len(images_res["images"]), 2)

    def test_merge_filename_collision_handling(self):
        event_name = "Event 3"
        event_dir = config.OUTPUT_FOLDER / event_name
        event_dir.mkdir(parents=True, exist_ok=True)

        cluster1 = event_dir / "Person001"
        cluster2 = event_dir / "Person002"
        cluster1.mkdir()
        cluster2.mkdir()

        (cluster1 / "sample.jpg").write_bytes(b"sample1")
        (cluster2 / "sample.jpg").write_bytes(b"sample2")

        res = merge_clusters({
            "event_id": event_name,
            "target_cluster_id": "Person001",
            "source_cluster_ids": ["Person001", "Person002"]
        })

        self.assertEqual(res["status"], "success")
        target_files = [f.name for f in cluster1.iterdir() if f.is_file() and not f.name.startswith(".")]
        self.assertEqual(len(target_files), 2)
        self.assertIn("sample.jpg", target_files)
        self.assertIn("sample_merged.jpg", target_files)

        images_res = get_person_images(event_name, "Person001")
        self.assertEqual(images_res["total_images"], 2)


if __name__ == "__main__":
    unittest.main()
