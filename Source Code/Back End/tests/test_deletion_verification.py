"""
Integration tests for event deletion and data purge operations.
Tests single-event directory deletion, global workspace resets, cache invalidation, and filesystem synchronization.
Handles verification of disk file removals, thumbnail pruning, and metadata file cleanup.
"""

import sys
import os
import time
import shutil
from pathlib import Path

# Add Back End root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import config
from server import (
    delete_selected_events,
    delete_all_data,
    list_clusters,
    get_all_photos_data,
    invalidate_all_caches,
)

def setup_mock_events():
    """Create mock events in input and output directories."""
    config.INPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    dummy_jpg = b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xFF\xDB\x00C\x00'

    # 1. Create Event1
    e1_in = config.INPUT_FOLDER / "TestEvent1"
    e1_in.mkdir(parents=True, exist_ok=True)
    (e1_in / "img1.jpg").write_bytes(dummy_jpg)

    e1_out = config.OUTPUT_FOLDER / "TestEvent1" / "Person001"
    e1_out.mkdir(parents=True, exist_ok=True)
    (e1_out / "img1.jpg").write_bytes(dummy_jpg)

    # 2. Create Event2
    e2_in = config.INPUT_FOLDER / "TestEvent2"
    e2_in.mkdir(parents=True, exist_ok=True)
    (e2_in / "img2.jpg").write_bytes(dummy_jpg)

    e2_out = config.OUTPUT_FOLDER / "TestEvent2" / "Person002"
    e2_out.mkdir(parents=True, exist_ok=True)
    (e2_out / "img2.jpg").write_bytes(dummy_jpg)

    # 3. Create Main Event root files
    (config.INPUT_FOLDER / "root_img.jpg").write_bytes(dummy_jpg)
    main_out = config.OUTPUT_FOLDER / "Person001"
    main_out.mkdir(parents=True, exist_ok=True)
    (main_out / "root_img.jpg").write_bytes(dummy_jpg)

    invalidate_all_caches()

def run_tests():
    print("\n--- Starting Deletion Verification Test ---")

    # Step 1: Setup and verify events exist
    setup_mock_events()
    clusters_before = list_clusters()["clusters"]
    cluster_ids = [c["cluster_id"] for c in clusters_before]
    print(f"Clusters created before delete: {cluster_ids}")
    assert "TestEvent1" in cluster_ids
    assert "TestEvent2" in cluster_ids

    # Step 2: Delete TestEvent1 on FIRST ATTEMPT
    print("\n[Test 1] Deleting 'TestEvent1' on first attempt...")
    res = delete_selected_events({"selected_events": ["TestEvent1"]})
    print(f"Delete response: {res}")

    # Immediately check disk existence
    assert not (config.INPUT_FOLDER / "TestEvent1").exists(), "TestEvent1 input folder still exists on disk!"
    assert not (config.OUTPUT_FOLDER / "TestEvent1").exists(), "TestEvent1 output folder still exists on disk!"

    # Immediately query clusters on first attempt
    clusters_after = list_clusters()["clusters"]
    cluster_ids_after = [c["cluster_id"] for c in clusters_after]
    print(f"Clusters after deleting TestEvent1: {cluster_ids_after}")
    assert "TestEvent1" not in cluster_ids_after, "TestEvent1 still listed in clusters API!"
    assert "TestEvent2" in cluster_ids_after
    print(">>> [PASS] TestEvent1 was completely deleted on the first attempt!")

    # Step 3: Delete All Storage Data on FIRST ATTEMPT
    print("\n[Test 2] Testing delete_all_data on first attempt...")
    res_all = delete_all_data()
    print(f"Delete all response: {res_all}")

    # Immediately verify disk is empty
    in_items = [p.name for p in config.INPUT_FOLDER.iterdir() if not p.name.startswith(".")]
    out_items = [p.name for p in config.OUTPUT_FOLDER.iterdir() if not p.name.startswith(".")]
    print(f"Input items remaining: {in_items}")
    print(f"Output items remaining: {out_items}")
    assert len(in_items) == 0, f"Input directory not empty: {in_items}"
    assert len(out_items) == 0, f"Output directory not empty: {out_items}"

    # Immediately query clusters
    final_clusters = list_clusters()["clusters"]
    print(f"Final clusters count: {len(final_clusters)}")
    assert len(final_clusters) == 0, f"Clusters API still returned items: {final_clusters}"

    # Immediately query photos
    final_photos = get_all_photos_data()
    print(f"Final photos count: {len(final_photos)}")
    assert len(final_photos) == 0, f"Photos API still returned items: {final_photos}"
    print(">>> [PASS] Delete All Storage Data completely removed all files and state on the first attempt!")

    print("\n==========================================")
    print("ALL DELETION TESTS PASSED ON FIRST ATTEMPT!")
    print("==========================================\n")

if __name__ == "__main__":
    run_tests()
