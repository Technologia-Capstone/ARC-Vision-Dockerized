import unittest
from pathlib import Path
import numpy as np

from core.face_detector import DetectedFace, FaceDetector
from core.clusterer import FaceClusterer


class TestTorsoArtifactFiltering(unittest.TestCase):
    def test_filter_torso_artifacts(self):
        detector = FaceDetector()
        img_path = Path("test_portrait.jpg")

        primary_face = DetectedFace(
            image_path=img_path,
            face_index=0,
            bbox=[260.0, 149.0, 484.0, 467.0],
            landmarks=np.zeros((5, 2), dtype=np.float32),
            confidence=0.998,
            aligned_face=np.zeros((112, 112, 3), dtype=np.uint8),
            image_shape=(1200, 800),
            detection_time_ms=50.0,
        )

        emblem_false_positive = DetectedFace(
            image_path=img_path,
            face_index=1,
            bbox=[134.0, 568.0, 174.0, 617.0],
            landmarks=np.zeros((5, 2), dtype=np.float32),
            confidence=0.875,
            aligned_face=np.zeros((112, 112, 3), dtype=np.uint8),
            image_shape=(1200, 800),
            detection_time_ms=50.0,
        )

        faces = [primary_face, emblem_false_positive]
        filtered = detector._filter_torso_artifacts(faces)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].face_index, 0)
        self.assertEqual(filtered[0].bbox, primary_face.bbox)

    def test_intra_photo_collision_purging(self):
        clusterer = FaceClusterer()

        # Create 4 identical vectors (2 photos, 2 faces per photo) so DBSCAN forms a cluster
        vec = np.ones(512, dtype=np.float32) / np.sqrt(512)
        vecs = np.tile(vec, (4, 1))

        faces = [
            DetectedFace(image_path=Path("photo1.jpg"), face_index=0, bbox=[0, 0, 10, 10], landmarks=np.zeros((5, 2)), confidence=0.9, aligned_face=None, image_shape=(100, 100)),
            DetectedFace(image_path=Path("photo1.jpg"), face_index=1, bbox=[20, 20, 30, 30], landmarks=np.zeros((5, 2)), confidence=0.9, aligned_face=None, image_shape=(100, 100)),
            DetectedFace(image_path=Path("photo2.jpg"), face_index=0, bbox=[0, 0, 10, 10], landmarks=np.zeros((5, 2)), confidence=0.9, aligned_face=None, image_shape=(100, 100)),
            DetectedFace(image_path=Path("photo2.jpg"), face_index=1, bbox=[20, 20, 30, 30], landmarks=np.zeros((5, 2)), confidence=0.9, aligned_face=None, image_shape=(100, 100)),
        ]
        valid_indices = [0, 1, 2, 3]

        labels = clusterer._run_dbscan(vecs, face_confidences=[0.9]*4, faces=faces, valid_indices=valid_indices)

        # Labels for intra-photo collision faces should be reset to noise -1
        self.assertTrue(all(lbl == -1 for lbl in labels))


if __name__ == "__main__":
    unittest.main()
