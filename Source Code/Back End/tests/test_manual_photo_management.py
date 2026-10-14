"""
Integration tests for manual photo management and cluster curation.
Tests selective photo deletion from specific clusters, multi-cluster photo assignment, file relocation, and flag/unflag restoration.
Handles validation of origin tracking (flag_origins.json), disk copy persistence, and multi-folder synchronization.
"""

import json
import shutil
import tempfile
import unittest
import sys
import io
from pathlib import Path
from starlette.datastructures import UploadFile

# Add Back End root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import config
from server import (
    delete_cluster_photos,
    add_photos_to_clusters,
    upload_photos_to_clusters,
    get_event_available_photos,
    get_person_images,
    invalidate_all_caches,
)


class TestManualPhotoManagement(unittest.TestCase):
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

    def test_delete_photos_from_cluster(self):
        """Test manually deleting selected photos from a specific cluster folder without affecting others."""
        event_name = "TechConference"
        p1_dir = config.OUTPUT_FOLDER / event_name / "Person001"
        p2_dir = config.OUTPUT_FOLDER / event_name / "Person002"
        p1_dir.mkdir(parents=True, exist_ok=True)
        p2_dir.mkdir(parents=True, exist_ok=True)

        # Create photos in Person001
        (p1_dir / "photo_a.jpg").write_bytes(b"aaa")
        (p1_dir / "photo_b.jpg").write_bytes(b"bbb")
        (p1_dir / "photo_c.jpg").write_bytes(b"ccc")

        # Create photo in Person002 (should be untouched)
        (p2_dir / "photo_a.jpg").write_bytes(b"aaa_copy")

        # Mock clusters.json
        clusters_json_path = config.OUTPUT_FOLDER / event_name / config.CLUSTERS_JSON_PATH.name
        clusters_json_path.write_text(json.dumps({
            "metadata": {"total_clusters": 2, "total_faces_detected": 4},
            "clusters": [
                {
                    "cluster_id": "Person001",
                    "person_id": "Person001",
                    "image_count": 3,
                    "face_count": 3,
                    "images": ["photo_a.jpg", "photo_b.jpg", "photo_c.jpg"],
                    "detections": [{"image": "photo_a.jpg"}, {"image": "photo_b.jpg"}, {"image": "photo_c.jpg"}]
                },
                {
                    "cluster_id": "Person002",
                    "person_id": "Person002",
                    "image_count": 1,
                    "face_count": 1,
                    "images": ["photo_a.jpg"],
                    "detections": [{"image": "photo_a.jpg"}]
                }
            ]
        }))

        # Delete photo_a.jpg and photo_b.jpg from Person001
        res = delete_cluster_photos({
            "event_id": event_name,
            "person_id": "Person001",
            "filenames": ["photo_a.jpg", "photo_b.jpg"]
        })

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["deleted_count"], 2)
        self.assertEqual(res["remaining_count"], 1)

        # Verify on disk
        self.assertFalse((p1_dir / "photo_a.jpg").exists())
        self.assertFalse((p1_dir / "photo_b.jpg").exists())
        self.assertTrue((p1_dir / "photo_c.jpg").exists())

        # Verify Person002 was not affected
        self.assertTrue((p2_dir / "photo_a.jpg").exists())

        # Verify clusters.json updated
        rep_data = json.loads(clusters_json_path.read_text())
        p1_data = next(c for c in rep_data["clusters"] if c["person_id"] == "Person001")
        self.assertEqual(p1_data["images"], ["photo_c.jpg"])
        self.assertEqual(p1_data["image_count"], 1)

        # Verify Tier 3 endpoint
        t3 = get_person_images(event_name, "Person001")
        self.assertEqual(t3["total_images"], 1)

    def test_add_photos_to_multiple_clusters_simultaneously(self):
        """Test selecting a photo and adding copies to multiple cluster folders at the same time."""
        event_name = "AnnualGala"
        event_input = config.INPUT_FOLDER / event_name
        event_input.mkdir(parents=True, exist_ok=True)
        (event_input / "shared_vip.jpg").write_bytes(b"vip_image_content")

        p1_dir = config.OUTPUT_FOLDER / event_name / "VIP_Alice"
        p2_dir = config.OUTPUT_FOLDER / event_name / "VIP_Bob"
        p3_dir = config.OUTPUT_FOLDER / event_name / "VIP_Charlie"
        p1_dir.mkdir(parents=True, exist_ok=True)
        p2_dir.mkdir(parents=True, exist_ok=True)
        p3_dir.mkdir(parents=True, exist_ok=True)

        res = add_photos_to_clusters({
            "event_id": event_name,
            "target_cluster_ids": ["VIP_Alice", "VIP_Bob", "VIP_Charlie"],
            "source_filenames": ["shared_vip.jpg"]
        })

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_added"], 3)
        self.assertEqual(len(res["target_clusters"]), 3)

        # Verify image was copied to all 3 clusters
        self.assertTrue((p1_dir / "shared_vip.jpg").exists())
        self.assertTrue((p2_dir / "shared_vip.jpg").exists())
        self.assertTrue((p3_dir / "shared_vip.jpg").exists())

        # Verify Tier 3 queries
        t3_a = get_person_images(event_name, "VIP_Alice")
        self.assertEqual(t3_a["total_images"], 1)
        t3_b = get_person_images(event_name, "VIP_Bob")
        self.assertEqual(t3_b["total_images"], 1)
        t3_c = get_person_images(event_name, "VIP_Charlie")
        self.assertEqual(t3_c["total_images"], 1)

    def test_add_photos_collision_copy_names(self):
        """Test adding a photo to a cluster where a file with the same name already exists creates a non-colliding copy."""
        event_name = "Summit"
        event_input = config.INPUT_FOLDER / event_name
        event_input.mkdir(parents=True, exist_ok=True)
        (event_input / "keynote.jpg").write_bytes(b"keynote_bytes")

        p1_dir = config.OUTPUT_FOLDER / event_name / "Speaker1"
        p1_dir.mkdir(parents=True, exist_ok=True)
        (p1_dir / "keynote.jpg").write_bytes(b"existing_keynote")

        res = add_photos_to_clusters({
            "event_id": event_name,
            "target_cluster_ids": ["Speaker1"],
            "source_filenames": ["keynote.jpg"]
        })

        self.assertEqual(res["status"], "success")
        files = {f.name for f in p1_dir.iterdir()}
        self.assertIn("keynote.jpg", files)
        self.assertIn("keynote_copy1.jpg", files)
        self.assertEqual(len(files), 2)

    def test_get_event_available_photos(self):
        """Test retrieving all clustered photos belonging to an event for selection."""
        event_name = "Hackathon"
        event_input = config.INPUT_FOLDER / event_name
        event_input.mkdir(parents=True, exist_ok=True)
        (event_input / "team1.jpg").write_bytes(b"t1")
        (event_input / "team2.jpg").write_bytes(b"t2")

        res = get_event_available_photos(event_name)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["event_id"], event_name)
        filenames = {p["filename"] for p in res["photos"]}
        self.assertIn("team1.jpg", filenames)
        self.assertIn("team2.jpg", filenames)

    async def async_test_upload_photos(self):
        """Test uploading photos directly to multiple clusters."""
        event_name = "Workshop"
        f1 = UploadFile(filename="new_device_photo.jpg", file=io.BytesIO(b"device_bytes"))

        res = await upload_photos_to_clusters(
            files=[f1],
            event_name=event_name,
            target_cluster_ids='["Participant1", "Participant2"]'
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["uploaded_count"], 1)

        p1_dir = config.OUTPUT_FOLDER / event_name / "Participant1"
        p2_dir = config.OUTPUT_FOLDER / event_name / "Participant2"
        self.assertTrue((p1_dir / "new_device_photo.jpg").exists())
        self.assertTrue((p2_dir / "new_device_photo.jpg").exists())

    def test_flag_and_unflag_manually_duplicated_photo(self):
        """
        Test the workflow:
        Original cluster -> manually added to multiple clusters -> flag -> Unknown -> unflag -> correctly returns to all appropriate clusters.
        """
        from server import toggle_flag, get_person_images

        event_name = "AvengersEvent"
        p1_dir = config.OUTPUT_FOLDER / event_name / "Person001"
        p2_dir = config.OUTPUT_FOLDER / event_name / "Person002"
        p3_dir = config.OUTPUT_FOLDER / event_name / "Person003"
        p1_dir.mkdir(parents=True, exist_ok=True)
        p2_dir.mkdir(parents=True, exist_ok=True)
        p3_dir.mkdir(parents=True, exist_ok=True)

        # 1. Start with photo in Person001
        photo_name = "hero_action.jpg"
        (p1_dir / photo_name).write_bytes(b"hero_action_data")

        # Mock clusters.json
        clusters_json_path = config.OUTPUT_FOLDER / event_name / config.CLUSTERS_JSON_PATH.name
        clusters_json_path.write_text(json.dumps({
            "clusters": [
                {"cluster_id": "Person001", "person_id": "Person001", "images": [photo_name], "image_count": 1},
                {"cluster_id": "Person002", "person_id": "Person002", "images": [], "image_count": 0},
                {"cluster_id": "Person003", "person_id": "Person003", "images": [], "image_count": 0},
                {"cluster_id": "Unknown", "person_id": "Unknown", "images": [], "image_count": 0}
            ]
        }))

        # 2. Manually add to Person002 and Person003
        add_res = add_photos_to_clusters({
            "event_id": event_name,
            "target_cluster_ids": ["Person002", "Person003"],
            "source_filenames": [photo_name]
        })
        self.assertEqual(add_res["status"], "success")

        # Verify photo is present in all 3 clusters
        self.assertTrue((p1_dir / photo_name).exists())
        self.assertTrue((p2_dir / photo_name).exists())
        self.assertTrue((p3_dir / photo_name).exists())

        # 3. Flag the photo
        flag_res = toggle_flag(photo_name)
        self.assertEqual(flag_res["status"], "flagged")
        self.assertTrue(flag_res["is_flagged"])

        unknown_dir = config.OUTPUT_FOLDER / event_name / "Unknown"
        # Photo is now in Unknown folder
        self.assertTrue((unknown_dir / photo_name).exists())

        # Photo copies have been moved out of the 3 active person clusters
        self.assertFalse((p1_dir / photo_name).exists())
        self.assertFalse((p2_dir / photo_name).exists())
        self.assertFalse((p3_dir / photo_name).exists())

        # Tier 3 check for Unknown
        t3_unknown = get_person_images(event_name, "Unknown")
        self.assertEqual(t3_unknown["total_images"], 1)

        # 4. Unflag the photo
        unflag_res = toggle_flag(photo_name)
        self.assertEqual(unflag_res["status"], "unflagged")
        self.assertFalse(unflag_res["is_flagged"])
        self.assertIn("Person001", unflag_res["restored_clusters"])
        self.assertIn("Person002", unflag_res["restored_clusters"])
        self.assertIn("Person003", unflag_res["restored_clusters"])

        # Photo is removed from Unknown folder
        self.assertFalse((unknown_dir / photo_name).exists())

        # Photo is restored back to all 3 clusters
        self.assertTrue((p1_dir / photo_name).exists())
        self.assertTrue((p2_dir / photo_name).exists())
        self.assertTrue((p3_dir / photo_name).exists())

        # Tier 3 checks for all clusters
        self.assertEqual(get_person_images(event_name, "Person001")["total_images"], 1)
        self.assertEqual(get_person_images(event_name, "Person002")["total_images"], 1)
        self.assertEqual(get_person_images(event_name, "Person003")["total_images"], 1)
        self.assertEqual(get_person_images(event_name, "Unknown")["total_images"], 0)

    def test_flag_and_unflag_single_cluster_restores_exact_cluster(self):
        """Test that single cluster photo returns to its exact original cluster (not Person001)."""
        from server import toggle_flag, get_person_images

        event_name = "SoloEvent"
        p5_dir = config.OUTPUT_FOLDER / event_name / "Person005"
        p5_dir.mkdir(parents=True, exist_ok=True)
        (p5_dir / "solo_shot.jpg").write_bytes(b"solo_shot_bytes")

        # Flag
        flag_res = toggle_flag("solo_shot.jpg")
        self.assertEqual(flag_res["status"], "flagged")
        self.assertTrue((config.OUTPUT_FOLDER / event_name / "Unknown" / "solo_shot.jpg").exists())
        self.assertFalse((p5_dir / "solo_shot.jpg").exists())

        # Unflag
        unflag_res = toggle_flag("solo_shot.jpg")
        self.assertEqual(unflag_res["status"], "unflagged")
        self.assertIn("Person005", unflag_res["restored_clusters"])
        self.assertTrue((p5_dir / "solo_shot.jpg").exists())
        self.assertFalse((config.OUTPUT_FOLDER / event_name / "Unknown" / "solo_shot.jpg").exists())


if __name__ == "__main__":
    unittest.main()

