"""
Filesystem organization engine for sorted photo distribution.
Creates person identity directories and safely routes clustered event photos, unknown detections, and no-face images.
Handles multi-face group photo copying, folder sorting by cluster frequency, and conflict-free file placement.
"""

from __future__ import annotations

import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import config
from core.face_detector import DetectedFace
from utils.logging_utils import get_logger

logger = get_logger(__name__)


@dataclass
class OrganizationResult:
    """
    Summary of the folder organization step.

    Attributes:
        output_root:     Root output directory.
        person_folders:  Dict mapping cluster label → folder Path.
        copies_made:     Total number of image files copied.
        images_per_cluster: Dict mapping cluster label → set of image names.
    """

    output_root: Path
    person_folders: dict[int, Path]
    copies_made: int
    images_per_cluster: dict[int, list[str]]


class ImageOrganizer:
    """
    Copies clustered images into organized person identity folders.

    Usage::

        organizer = ImageOrganizer()
        result = organizer.organize(faces, output_dir)

    Attributes:
        output_root: The root output directory (``config.OUTPUT_FOLDER``).
    """

    def __init__(self, output_root: Path = config.OUTPUT_FOLDER) -> None:
        """
        Initialize the organizer with the output root directory.

        Args:
            output_root: Where to create person folders. Created if absent.
        """
        self.output_root = output_root
        self.output_root.mkdir(parents=True, exist_ok=True)
        logger.info(f"ImageOrganizer — output root: {self.output_root.resolve()}")

    def organize(
        self,
        faces: list[DetectedFace],
        no_face_images: list[Path] | None = None,
    ) -> OrganizationResult:
        """
        Copy images into person identity folders based on cluster labels.

        Args:
            faces:          All detected faces with ``cluster_label`` and
                            ``image_path`` set.
            no_face_images: Optional list of image paths where no face was
                            detected. These are copied into ``NoFace/``.

        Returns:
            ``OrganizationResult`` with folder paths and copy counts.
        """
        label_to_images = self._map_labels_to_images(faces)
        label_to_folder = self._create_folders(label_to_images, faces=faces)
        copies = self._copy_images(faces, label_to_folder)

        # Copy images with no detected faces into NoFace/
        if no_face_images:
            copies += self._copy_no_face_images(no_face_images)

        images_per_cluster: dict[int, list[str]] = {
            lbl: sorted(img.name for img in imgs)
            for lbl, imgs in label_to_images.items()
        }

        result = OrganizationResult(
            output_root=self.output_root,
            person_folders=label_to_folder,
            copies_made=copies,
            images_per_cluster=images_per_cluster,
        )

        logger.info(
            f"Organization complete — {copies} file(s) copied to "
            f"{len(label_to_folder)} folder(s)"
        )
        return result

    def _map_labels_to_images(
        self,
        faces: list[DetectedFace],
    ) -> dict[int, set[Path]]:
        """
        Build a mapping of cluster label → set of source image paths.

        If ``COPY_TO_ALL_MATCHED_FOLDERS`` is False, each image is only
        mapped to the cluster of its highest-confidence face.

        Args:
            faces: All detected faces.

        Returns:
            Dict mapping cluster label → set of unique image Paths.
        """
        mapping: dict[int, set[Path]] = defaultdict(set)

        if config.COPY_TO_ALL_MATCHED_FOLDERS:
            # Map image to ALL clusters it appears in
            for face in faces:
                mapping[face.cluster_label].add(face.image_path)
        else:
            # Map image to the cluster of its highest-confidence face only
            best: dict[Path, tuple[int, float]] = {}  # path → (label, confidence)
            for face in faces:
                path = face.image_path
                if path not in best or face.confidence > best[path][1]:
                    best[path] = (face.cluster_label, face.confidence)
            for path, (label, _) in best.items():
                mapping[label].add(path)

        return dict(mapping)

    def _create_folders(
        self,
        label_to_images: dict[int, set[Path]],
        faces: list[DetectedFace] | None = None,
    ) -> dict[int, Path]:
        """
        Create output subdirectories for each cluster.

        Clusters are sorted by size (descending) so the most-populated
        cluster becomes Person001. Noise (label -1) → Unknown/.

        Args:
            label_to_images: Mapping of cluster label → image paths.
            faces:           Optional list of detected faces for face count tie-breaking.

        Returns:
            Dict mapping cluster label → created directory Path.
        """
        face_counts: dict[int, int] = defaultdict(int)
        if faces:
            for f in faces:
                if f.cluster_label >= 0:
                    face_counts[f.cluster_label] += 1

        # Sort valid clusters deterministically: image count DESC, face count DESC, label ASC
        valid_labels = sorted(
            [lbl for lbl in label_to_images if lbl >= 0],
            key=lambda lbl: (len(label_to_images[lbl]), face_counts.get(lbl, 0), -lbl),
            reverse=True,
        )

        label_to_folder: dict[int, Path] = {}

        for rank, lbl in enumerate(valid_labels, start=1):
            folder_name = f"{config.PERSON_FOLDER_PREFIX}{rank:03d}"
            folder_path = self.output_root / folder_name
            folder_path.mkdir(parents=True, exist_ok=True)
            label_to_folder[lbl] = folder_path
            logger.debug(
                f"Created folder: {folder_name}/ "
                f"({len(label_to_images[lbl])} image(s))"
            )

        # Flagged folder for low-confidence / misclassified images
        flagged_path = self.output_root / config.FLAGGED_FOLDER_NAME
        flagged_path.mkdir(parents=True, exist_ok=True)
        if -3 in label_to_images:
            label_to_folder[-3] = flagged_path

        # Unknown folder for unassigned / noise images
        unknown_path = self.output_root / config.UNKNOWN_FOLDER_NAME
        unknown_path.mkdir(parents=True, exist_ok=True)
        if -1 in label_to_images:
            label_to_folder[-1] = unknown_path

        return label_to_folder



    def _copy_images(
        self,
        faces: list[DetectedFace],
        label_to_folder: dict[int, Path],
    ) -> int:
        """
        Copy source images to their designated output folders.

        Handles filename collisions by appending ``_faceN`` when multiple
        faces from the same image map to the same destination.

        Args:
            faces:           All detected faces.
            label_to_folder: Cluster label → destination folder.

        Returns:
            Total number of successful file copies.
        """
        copies = 0
        # Track which (folder, stem) pairs have been used to avoid overwrites
        used_names: dict[Path, dict[str, int]] = defaultdict(dict)

        # Build (image_path, label) pairs, deduplicated
        pairs: set[tuple[Path, int]] = set()
        for face in faces:
            if face.cluster_label in label_to_folder:
                pairs.add((face.image_path, face.cluster_label))

        for src_path, label in sorted(pairs):
            dest_folder = label_to_folder[label]
            stem = src_path.stem
            suffix = src_path.suffix

            # Resolve filename collisions
            if stem in used_names[dest_folder]:
                count = used_names[dest_folder][stem] + 1
                used_names[dest_folder][stem] = count
                dest_name = f"{stem}_face{count}{suffix}"
            else:
                used_names[dest_folder][stem] = 0
                dest_name = f"{stem}{suffix}"

            dest_path = dest_folder / dest_name

            try:
                try:
                    import os
                    os.link(str(src_path), str(dest_path))
                except Exception:
                    shutil.copyfile(str(src_path), str(dest_path))
                copies += 1
                logger.debug(f"Copied: {src_path.name} -> {dest_folder.name}/{dest_name}")
            except Exception as exc:
                logger.error(f"Failed to copy '{src_path}' -> '{dest_path}': {exc}")

        return copies

    def _copy_no_face_images(self, no_face_images: list[Path]) -> int:
        """
        Copy images with no detected face into the ``NoFace/`` folder.

        Args:
            no_face_images: List of source image paths with no detected face.

        Returns:
            Number of successful file copies.
        """
        no_face_folder = self.output_root / config.NO_FACE_FOLDER_NAME
        no_face_folder.mkdir(parents=True, exist_ok=True)
        logger.debug(
            f"Created folder: {config.NO_FACE_FOLDER_NAME}/ "
            f"({len(no_face_images)} image(s))"
        )

        copies = 0
        used_stems: dict[str, int] = {}

        for src_path in sorted(no_face_images):
            stem = src_path.stem
            suffix = src_path.suffix

            if stem in used_stems:
                count = used_stems[stem] + 1
                used_stems[stem] = count
                dest_name = f"{stem}_copy{count}{suffix}"
            else:
                used_stems[stem] = 0
                dest_name = f"{stem}{suffix}"

            dest_path = no_face_folder / dest_name
            try:
                shutil.copy2(str(src_path), str(dest_path))
                copies += 1
                logger.debug(
                    f"Copied (no-face): {src_path.name} → "
                    f"{config.NO_FACE_FOLDER_NAME}/{dest_name}"
                )
            except Exception as exc:
                logger.error(
                    f"Failed to copy no-face image '{src_path}' → '{dest_path}': {exc}"
                )

        logger.info(
            f"NoFace/: {copies}/{len(no_face_images)} image(s) copied"
        )
        return copies


# ── Module-level FastAPI-ready entry point ────────────────────────────────────

_organizer_instance: ImageOrganizer | None = None


def organize_output(
    faces: list[DetectedFace],
    output_dir: Path = config.OUTPUT_FOLDER,
) -> OrganizationResult:
    """
    Module-level function for organizing clustered images into folders.

    Lazily initializes a singleton ``ImageOrganizer`` on first call.

    Args:
        faces:      List of detected faces with ``cluster_label`` set.
        output_dir: Root output directory path.

    Returns:
        ``OrganizationResult`` describing what was created and copied.
    """
    global _organizer_instance
    if _organizer_instance is None or _organizer_instance.output_root != output_dir:
        _organizer_instance = ImageOrganizer(output_dir)
    return _organizer_instance.organize(faces)
