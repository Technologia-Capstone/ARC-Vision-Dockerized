"""
Standalone command-line pipeline orchestrator for A.R.C. Vision.
Executes end-to-end photo clustering workflow including detection, embedding extraction, fusion, DBSCAN, and folder organization.
Handles CLI argument parsing, progress bar rendering, and summary telemetry reporting.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from tqdm import tqdm

import config
from core.face_detector import FaceDetector, DetectedFace, detect_faces
from core.embedder import FaceEmbedder, extract_embeddings
from core.feature_extractor import FeatureExtractor, extract_features
from core.feature_fusion import FeatureFusion, fuse_features
from core.clusterer import FaceClusterer, ClusterStats, cluster_faces
from core.organizer import ImageOrganizer, OrganizationResult, organize_output
from core.reporter import ReportGenerator, generate_report
from utils.image_utils import get_image_files, load_image_rgb
from utils.logging_utils import setup_logging, get_logger


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Automated School Event Photo Clustering System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=config.INPUT_FOLDER,
        help=f"Input folder containing photos (default: {config.INPUT_FOLDER})",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=config.OUTPUT_FOLDER,
        help=f"Output folder for clustered images (default: {config.OUTPUT_FOLDER})",
    )
    parser.add_argument(
        "--eps",
        type=float,
        default=config.DBSCAN_EPS,
        help=f"DBSCAN epsilon (cosine distance, default: {config.DBSCAN_EPS})",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=config.DBSCAN_MIN_SAMPLES,
        help=f"DBSCAN min_samples (default: {config.DBSCAN_MIN_SAMPLES})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=config.DEBUG_MODE,
        help="Enable verbose debug logging",
    )
    return parser.parse_args()


def run_pipeline(
    input_folder: Path,
    output_folder: Path,
    dbscan_eps: float = config.DBSCAN_EPS,
    dbscan_min_samples: int = config.DBSCAN_MIN_SAMPLES,
) -> dict:
    """
    Execute the full photo clustering pipeline end-to-end.

    This function is the FastAPI-ready entry point for the pipeline.
    All side-effects (folder creation, file copying, JSON writing) are
    driven by configuration and the ``output_folder`` argument.

    Args:
        input_folder:        Directory containing input photos.
        output_folder:       Root directory for clustered output.
        dbscan_eps:          DBSCAN epsilon parameter (cosine distance).
        dbscan_min_samples:  DBSCAN min_samples parameter.

    Returns:
        Summary dict with counts and output paths.

    Raises:
        FileNotFoundError: If ``input_folder`` does not exist.
        RuntimeError:      If no faces are detected in any image.
    """
    logger = get_logger(__name__)
    pipeline_start = time.perf_counter()

    # ── Step 1: Collect image files ──────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 1/7 — Scanning input folder for images")
    logger.info("=" * 60)

    image_paths = get_image_files(input_folder)
    if not image_paths:
        raise RuntimeError(
            f"No images found in '{input_folder}'. "
            f"Accepted formats: {config.ACCEPTED_FORMATS}"
        )
    logger.info(f"Found {len(image_paths)} image(s) to process")

    # ── Step 2: Initialize models (load once) ────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 2/7 — Loading pretrained models")
    logger.info("=" * 60)

    detector = FaceDetector()
    embedder = FaceEmbedder()
    extractor = FeatureExtractor()
    fusion = FeatureFusion(
        face_weight=config.FACE_WEIGHT,
        color_weight=config.COLOR_WEIGHT,
        spatial_weight=config.SPATIAL_WEIGHT,
    )
    clusterer = FaceClusterer(eps=dbscan_eps, min_samples=dbscan_min_samples)

    # ── Step 3: Detect faces + extract embeddings + features ─────────────────
    logger.info("=" * 60)
    logger.info("STEP 3/7 — Detecting faces, extracting embeddings & features")
    logger.info("=" * 60)

    all_faces: list[DetectedFace] = []
    no_face_images: list[Path] = []

    for image_path in tqdm(image_paths, desc="Processing images", unit="img"):
        image_rgb = load_image_rgb(image_path)
        if image_rgb is None:
            logger.warning(f"Skipping unreadable image: {image_path.name}")
            continue

        # 3a. Detect faces
        faces = detector.detect_faces(image_rgb, image_path)

        if not faces:
            no_face_images.append(image_path)
            logger.debug(f"No faces in: {image_path.name} — queued for NoFace/")
            continue

        # 3b. Extract ArcFace embeddings
        faces = embedder.extract_batch(faces)

        # 3c. Extract clothing + spatial features
        faces = extractor.extract_all(faces, image_rgb)

        # 3d. Fuse features into one vector
        faces = fusion.fuse_all(faces)

        all_faces.extend(faces)

    logger.info(
        f"Detection complete — {len(all_faces)} face(s) found across "
        f"{len(image_paths) - len(no_face_images)} image(s) "
        f"({len(no_face_images)} image(s) had no detectable faces — "
        f"will be copied to {config.NO_FACE_FOLDER_NAME}/)"
    )

    if not all_faces:
        raise RuntimeError(
            "No faces were detected in any of the input images. "
            "Check MTCNN_MIN_FACE_SIZE and MTCNN_CONFIDENCE_THRESHOLD in config.py."
        )

    # ── Step 4: Cluster identities ───────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 4/7 — Clustering identities with DBSCAN")
    logger.info("=" * 60)

    all_faces, cluster_stats = clusterer.cluster(all_faces)

    # ── Step 5: Organize output folders ──────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 5/7 — Organizing images into person folders")
    logger.info("=" * 60)

    organizer = ImageOrganizer(output_folder)
    org_result = organizer.organize(all_faces, no_face_images=no_face_images)

    # ── Step 6: Generate JSON report ─────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 6/7 — Generating clusters.json report")
    logger.info("=" * 60)

    # Resolve report path relative to output folder
    report_path = output_folder / config.CLUSTERS_JSON_PATH.name
    total_time = time.perf_counter() - pipeline_start

    reporter = ReportGenerator()
    reporter.generate(
        faces=all_faces,
        stats=cluster_stats,
        org_result=org_result,
        total_images=len(image_paths),
        total_time_s=total_time,
        output_path=report_path,
    )

    # ── Step 7: Final summary ─────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 7/7 — Pipeline complete!")
    logger.info("=" * 60)
    logger.info(f"  Input images    : {len(image_paths)}")
    logger.info(f"  Faces detected  : {len(all_faces)}")
    logger.info(f"  Persons found   : {cluster_stats.n_clusters}")
    logger.info(f"  Unknown faces   : {cluster_stats.n_noise}")
    logger.info(f"  No-face images  : {len(no_face_images)} → {config.NO_FACE_FOLDER_NAME}/")
    logger.info(f"  Files copied    : {org_result.copies_made}")
    logger.info(f"  Output folder   : {output_folder.resolve()}")
    logger.info(f"  Report          : {report_path}")
    logger.info(f"  Total time      : {total_time:.2f}s")
    logger.info("=" * 60)

    return {
        "total_images": len(image_paths),
        "total_faces": len(all_faces),
        "n_clusters": cluster_stats.n_clusters,
        "n_noise": cluster_stats.n_noise,
        "n_no_face_images": len(no_face_images),
        "files_copied": org_result.copies_made,
        "output_folder": str(output_folder.resolve()),
        "report_path": str(report_path),
        "total_time_s": round(total_time, 3),
        "silhouette_score": cluster_stats.silhouette_score,
    }


def main() -> None:
    """Parse arguments, set up logging, and run the pipeline."""
    args = parse_args()

    # Initialize logging before anything else
    log_file = args.output / config.LOG_FILE.name if config.LOG_FILE else None
    setup_logging(log_file=log_file, debug=args.debug)

    logger = get_logger(__name__)
    logger.info("=" * 60)
    logger.info("Automated School Event Photo Clustering System")
    logger.info("=" * 60)
    logger.info(f"Input  : {args.input}")
    logger.info(f"Output : {args.output}")
    logger.info(f"DBSCAN : eps={args.eps}, min_samples={args.min_samples}")

    try:
        summary = run_pipeline(
            input_folder=args.input,
            output_folder=args.output,
            dbscan_eps=args.eps,
            dbscan_min_samples=args.min_samples,
        )
        print("\n[OK] Clustering complete!")
        print(f"   Persons identified : {summary['n_clusters']}")
        print(f"   Faces detected     : {summary['total_faces']}")
        print(f"   No-face images     : {summary['n_no_face_images']} → {config.NO_FACE_FOLDER_NAME}/")
        print(f"   Files organized    : {summary['files_copied']}")
        print(f"   Output folder      : {summary['output_folder']}")
        print(f"   Report             : {summary['report_path']}")
        print(f"   Time elapsed       : {summary['total_time_s']:.1f}s")

    except FileNotFoundError as exc:
        logger.error(f"Input folder error: {exc}")
        sys.exit(1)
    except RuntimeError as exc:
        logger.error(f"Pipeline error: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        logger.exception(f"Unexpected error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
