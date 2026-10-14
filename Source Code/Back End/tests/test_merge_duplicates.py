"""
Unit tests for duplicate resolution strategies during cluster merging.
Tests 'Keep Duplicates' and 'Deduplicate by Original Filename' modes during cluster consolidation.
Handles base filename extraction, collision prevention, and file preservation verification.
"""

import shutil
import tempfile
import unittest
import sys
from pathlib import Path

# Add Back End root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import config
from server import (
    merge_clusters,
    get_person_images,
    get_event_clusters,
    invalidate_all_caches,
    get_original_file_identifier,
)


class TestMergeDuplicates(unittest.TestCase):
    def setUp(self):
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

    def test_original_file_identifier_extraction(self):
        """Verify that duplicate/merge/copy suffixes are cleanly stripped to reveal the original identifier."""
        self.assertEqual(get_original_file_identifier("IMG_001.JPG"), "img_001.jpg")
        self.assertEqual(get_original_file_identifier("IMG_001_merged.JPG"), "img_001.jpg")
        self.assertEqual(get_original_file_identifier("IMG_001_merged2.JPG"), "img_001.jpg")
        self.assertEqual(get_original_file_identifier("IMG_001_face1.JPG"), "img_001.jpg")
        self.assertEqual(get_original_file_identifier("IMG_001_face2.JPG"), "img_001.jpg")
        self.assertEqual(get_original_file_identifier("IMG_001_face2_merged.JPG"), "img_001.jpg")
        self.assertEqual(get_original_file_identifier("IMG_001_copy1.JPG"), "img_001.jpg")
        self.assertEqual(get_original_file_identifier("IMG_001 (1).JPG"), "img_001.jpg")
        self.assertEqual(get_original_file_identifier("IMG_001 - Copy.JPG"), "img_001.jpg")
        self.assertEqual(get_original_file_identifier("IMG_002.JPG"), "img_002.jpg")
        self.assertNotEqual(get_original_file_identifier("IMG_001.JPG"), get_original_file_identifier("IMG_002.JPG"))

    def test_merge_keep_duplicates_true(self):
        """
        1 photo with 3 people -> 3 clusters -> merge with keep_duplicates=True -> 1 folder with 3 copies.
        """
        event_name = "Conference2026"
        p1 = config.OUTPUT_FOLDER / event_name / "Person001"
        p2 = config.OUTPUT_FOLDER / event_name / "Person002"
        p3 = config.OUTPUT_FOLDER / event_name / "Person003"
        p1.mkdir(parents=True, exist_ok=True)
        p2.mkdir(parents=True, exist_ok=True)
        p3.mkdir(parents=True, exist_ok=True)

        (p1 / "group_photo.jpg").write_bytes(b"content_1")
        (p2 / "group_photo.jpg").write_bytes(b"content_2")
        (p3 / "group_photo.jpg").write_bytes(b"content_3")

        res = merge_clusters({
            "target_cluster_id": "Person001",
            "source_cluster_ids": ["Person001", "Person002", "Person003"],
            "event_id": event_name,
            "keep_duplicates": True
        })
        self.assertEqual(res["status"], "success")

        # Destination folder must have 3 copies
        files = list(p1.iterdir())
        file_names = {f.name for f in files}
        self.assertEqual(len(files), 3)
        self.assertIn("group_photo.jpg", file_names)
        self.assertTrue(any("merged" in fn for fn in file_names))

        # Source folders must be cleaned up
        self.assertFalse(p2.exists())
        self.assertFalse(p3.exists())

        # Tier 3 query returns 3 photos
        t3 = get_person_images(event_name, "Person001")
        self.assertEqual(t3["total_images"], 3)

    def test_merge_keep_duplicates_false(self):
        """
        1 photo with 3 people + unique photos -> merge with keep_duplicates=False -> 1 copy of duplicate photo, unique photos kept.
        """
        event_name = "Festival2026"
        p1 = config.OUTPUT_FOLDER / event_name / "Person001"
        p2 = config.OUTPUT_FOLDER / event_name / "Person002"
        p3 = config.OUTPUT_FOLDER / event_name / "Person003"
        p1.mkdir(parents=True, exist_ok=True)
        p2.mkdir(parents=True, exist_ok=True)
        p3.mkdir(parents=True, exist_ok=True)

        # Same photo in all 3 folders
        (p1 / "shared_photo.jpg").write_bytes(b"content_1")
        (p2 / "shared_photo.jpg").write_bytes(b"content_2")
        (p3 / "shared_photo.jpg").write_bytes(b"content_3")

        # Distinct unique photos
        (p1 / "p1_solo.jpg").write_bytes(b"solo_1")
        (p2 / "p2_solo.jpg").write_bytes(b"solo_2")
        (p3 / "p3_solo.jpg").write_bytes(b"solo_3")

        res = merge_clusters({
            "target_cluster_id": "Person001",
            "source_cluster_ids": ["Person001", "Person002", "Person003"],
            "event_id": event_name,
            "keep_duplicates": False
        })
        self.assertEqual(res["status"], "success")

        # Destination folder must have exactly 4 unique photos (1 shared + 3 solo)
        files = list(p1.iterdir())
        file_names = {f.name for f in files}
        self.assertEqual(len(files), 4)
        self.assertIn("shared_photo.jpg", file_names)
        self.assertIn("p1_solo.jpg", file_names)
        self.assertIn("p2_solo.jpg", file_names)
        self.assertIn("p3_solo.jpg", file_names)
        # Verify no _merged copy was created
        self.assertFalse(any("merged" in fn for fn in file_names))

        # Tier 3 query returns exactly 4 photos
        t3 = get_person_images(event_name, "Person001")
        self.assertEqual(t3["total_images"], 4)

    def test_merge_preexisting_duplicates_in_target_cleaned(self):
        """
        If the target folder already contained duplicate copies from prior operations,
        merging with keep_duplicates=False cleans up those duplicates as well.
        """
        event_name = "Seminar2026"
        p1 = config.OUTPUT_FOLDER / event_name / "Person001"
        p2 = config.OUTPUT_FOLDER / event_name / "Person002"
        p1.mkdir(parents=True, exist_ok=True)
        p2.mkdir(parents=True, exist_ok=True)

        # p1 already has 2 copies of same image
        (p1 / "shared_photo.jpg").write_bytes(b"content_1")
        (p1 / "shared_photo_merged.jpg").write_bytes(b"content_1_dup")

        # p2 has another copy plus a unique photo
        (p2 / "shared_photo.jpg").write_bytes(b"content_2")
        (p2 / "unique_photo.jpg").write_bytes(b"content_unique")

        res = merge_clusters({
            "target_cluster_id": "Person001",
            "source_cluster_ids": ["Person001", "Person002"],
            "event_id": event_name,
            "keep_duplicates": False
        })
        self.assertEqual(res["status"], "success")

        files = list(p1.iterdir())
        file_names = {f.name for f in files}
        self.assertEqual(len(files), 2)
        self.assertIn("shared_photo.jpg", file_names)
        self.assertIn("unique_photo.jpg", file_names)
        self.assertNotIn("shared_photo_merged.jpg", file_names)

        t3 = get_person_images(event_name, "Person001")
        self.assertEqual(t3["total_images"], 2)

    def test_merge_into_new_name_deduplication(self):
        """Merging into a new destination cluster name with deduplication."""
        event_name = "Main Event"
        p1 = config.OUTPUT_FOLDER / "Person001"
        p2 = config.OUTPUT_FOLDER / "Person002"
        p1.mkdir(parents=True, exist_ok=True)
        p2.mkdir(parents=True, exist_ok=True)

        (p1 / "img_a.png").write_bytes(b"img_a")
        (p2 / "img_a.png").write_bytes(b"img_a_copy")
        (p2 / "img_b.png").write_bytes(b"img_b")

        res = merge_clusters({
            "target_cluster_id": "Alice",
            "source_cluster_ids": ["Person001", "Person002"],
            "event_id": event_name,
            "keep_duplicates": False
        })
        self.assertEqual(res["status"], "success")

        target_dir = config.OUTPUT_FOLDER / "Alice"
        self.assertTrue(target_dir.exists())
        files = list(target_dir.iterdir())
        file_names = {f.name for f in files}
        self.assertEqual(len(files), 2)
        self.assertIn("img_a.png", file_names)
        self.assertIn("img_b.png", file_names)

        t3 = get_person_images(event_name, "Alice")
        self.assertEqual(t3["total_images"], 2)


if __name__ == "__main__":
    unittest.main()
