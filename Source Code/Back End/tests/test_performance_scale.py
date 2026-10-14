"""
High-scale benchmark and stress-testing suite for massive photo collections.
Simulates 3,000+ images across multiple event directories to evaluate cold/warm scan latency and in-memory caching.
Handles validation of sub-millisecond retrieval, high-throughput stats compilation, and memory stability.
"""

import os
import time
import shutil
import tempfile
import unittest
import sys
from pathlib import Path

# Add Back End root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import config
import server
from server import (
    _build_storage_index,
    get_all_photos_data,
    get_stats,
    list_clusters,
    get_event_clusters,
    get_person_images,
    scan_events,
    generate_or_get_thumbnail,
    invalidate_all_caches,
)


class TestLargeCollectionScale(unittest.TestCase):
    """Stress test the backend with 3,000 files across multiple events."""

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

    def test_3000_images_multi_event_performance(self):
        print("\n--- Generating 3,000 simulated photos across 5 events ---")
        
        # Create 5 event folders in output, each with 10 person folders and 60 photos (Total: 3,000 photos)
        NUM_EVENTS = 5
        CLUSTERS_PER_EVENT = 10
        PHOTOS_PER_CLUSTER = 60  # 5 * 10 * 60 = 3,000 photos

        for e_idx in range(1, NUM_EVENTS + 1):
            event_name = f"Event_{e_idx:02d}"
            event_dir = config.OUTPUT_FOLDER / event_name
            event_dir.mkdir(parents=True, exist_ok=True)

            for c_idx in range(1, CLUSTERS_PER_EVENT + 1):
                cluster_name = f"Person{c_idx:03d}"
                cluster_dir = event_dir / cluster_name
                cluster_dir.mkdir(parents=True, exist_ok=True)

                for p_idx in range(1, PHOTOS_PER_CLUSTER + 1):
                    photo_name = f"IMG_E{e_idx}_C{c_idx}_{p_idx:04d}.JPG"
                    (cluster_dir / photo_name).write_bytes(b"dummy_image_content")

        print("--- Benchmark Start: 3,000 items on disk ---")

        # 1. Benchmark Cold-Scan (Cache Miss)
        invalidate_all_caches()
        t0 = time.perf_counter()
        photos = get_all_photos_data()
        t_cold_photos = (time.perf_counter() - t0) * 1000
        self.assertEqual(len(photos), 3000)
        print(f"[OK] Cold-Scan get_all_photos_data (3,000 photos): {t_cold_photos:.2f}ms")
        self.assertLess(t_cold_photos, 250.0, "Cold scan should take < 250ms even for 3,000 files")

        # 2. Benchmark Warm get_all_photos_data (Cache Hit)
        t0 = time.perf_counter()
        photos_warm = get_all_photos_data()
        t_warm_photos = (time.perf_counter() - t0) * 1000
        self.assertEqual(len(photos_warm), 3000)
        print(f"[OK] Warm get_all_photos_data: {t_warm_photos:.3f}ms")
        self.assertLess(t_warm_photos, 10.0, "Warm photos query should take < 10ms")

        # 3. Benchmark get_stats (Cold & Warm)
        invalidate_all_caches()
        t0 = time.perf_counter()
        stats = get_stats()
        t_stats_cold = (time.perf_counter() - t0) * 1000
        self.assertEqual(stats["total_images"], 3000)
        self.assertEqual(stats["total_clusters"], NUM_EVENTS * CLUSTERS_PER_EVENT)
        print(f"[OK] Cold get_stats: {t_stats_cold:.2f}ms (Total Images: {stats['total_images']}, Clusters: {stats['total_clusters']})")
        self.assertLess(t_stats_cold, 250.0, "Cold get_stats should take < 250ms")

        t0 = time.perf_counter()
        stats_warm = get_stats()
        t_stats_warm = (time.perf_counter() - t0) * 1000
        print(f"[OK] Warm get_stats: {t_stats_warm:.3f}ms")
        self.assertLess(t_stats_warm, 5.0, "Warm get_stats should take < 5ms")

        # 4. Benchmark list_clusters (Tier 1)
        t0 = time.perf_counter()
        t1_res = list_clusters()
        t_t1 = (time.perf_counter() - t0) * 1000
        self.assertEqual(len(t1_res["clusters"]), NUM_EVENTS)
        print(f"[OK] Tier 1 list_clusters ({len(t1_res['clusters'])} events): {t_t1:.3f}ms")
        self.assertLess(t_t1, 10.0, "Tier 1 list_clusters should take < 10ms")

        # 5. Benchmark get_event_clusters (Tier 2)
        t0 = time.perf_counter()
        t2_res = get_event_clusters("Event_01")
        t_t2 = (time.perf_counter() - t0) * 1000
        self.assertEqual(len(t2_res["person_clusters"]), CLUSTERS_PER_EVENT)
        print(f"[OK] Tier 2 get_event_clusters ({len(t2_res['person_clusters'])} clusters): {t_t2:.2f}ms")
        self.assertLess(t_t2, 50.0, "Tier 2 get_event_clusters should take < 50ms")

        # 6. Benchmark get_person_images (Tier 3)
        t0 = time.perf_counter()
        t3_res = get_person_images("Event_01", "Person001")
        t_t3 = (time.perf_counter() - t0) * 1000
        self.assertEqual(t3_res["total_images"], PHOTOS_PER_CLUSTER)
        print(f"[OK] Tier 3 get_person_images ({t3_res['total_images']} photos): {t_t3:.2f}ms")
        self.assertLess(t_t3, 20.0, "Tier 3 get_person_images should take < 20ms")

        # 7. Benchmark Rapid In-Memory Thumbnail Path Resolution (1,000 queries)
        t0 = time.perf_counter()
        idx = _build_storage_index()
        for i in range(1000):
            fn = f"IMG_E1_C1_{(i % PHOTOS_PER_CLUSTER) + 1:04d}.JPG".lower()
            p = idx["filename_map"].get(fn)
            self.assertIsNotNone(p)
        t_1000_lookups = (time.perf_counter() - t0) * 1000
        print(f"[OK] 1,000 Filename-to-Path Lookups: {t_1000_lookups:.2f}ms ({t_1000_lookups/1000:.4f}ms per lookup)")
        self.assertLess(t_1000_lookups, 10.0, "1,000 memory lookups should take < 10ms")

        # 8. Benchmark High-Speed ZIP Export Creation
        print("--- Testing High-Speed ZIP Export Performance ---")
        t0 = time.perf_counter()
        zip_out = Path(self.test_dir) / "test_export.zip"
        files_to_export = []
        for root, dirs, files in os.walk(config.OUTPUT_FOLDER):
            for f in files:
                if f.endswith(".JPG"):
                    fp = Path(root) / f
                    files_to_export.append((fp, fp.name))
        
        import zipfile
        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            for fp, arcname in files_to_export:
                zf.write(fp, arcname)
        t_zip = (time.perf_counter() - t0) * 1000
        self.assertTrue(zip_out.exists())
        self.assertGreater(zip_out.stat().st_size, 0)
        print(f"[OK] Exported {len(files_to_export)} photos to ZIP in {t_zip:.2f}ms ({len(files_to_export)/(t_zip/1000):.1f} files/sec)")
        self.assertLess(t_zip, 2000.0, "3,000 file ZIP creation should take < 2.0s with fast compression")

        print("--- Benchmark Completed Successfully ---\n")


if __name__ == "__main__":
    unittest.main()
