"""
Central system configuration and hyperparameter definitions for A.R.C. Vision.
Defines server networking, file system directories, MTCNN thresholds, feature fusion weights, and DBSCAN clustering settings.
Handles global pipeline constants, accepted file extensions, and debug report paths.
"""

from pathlib import Path

# ============================================================
# API SERVER CONFIGURATION
# ============================================================
SERVER_HOST: str = "127.0.0.1"
SERVER_PORT: int = 8000

# ============================================================
# PATHS
# ============================================================

# Path relative to this config file
BASE_DIR: Path = Path(__file__).parent.resolve()

# Input folder containing the raw school event photos.
INPUT_FOLDER: Path = BASE_DIR / "input"

# Root output folder. Subdirectories (Person001/, Unknown/, etc.)
# will be created automatically at runtime.
OUTPUT_FOLDER: Path = BASE_DIR / "output"

# Where InsightFace will cache downloaded model weights.
# Set to None to use the system default (~/.insightface/).
INSIGHTFACE_MODEL_DIR: Path = BASE_DIR / ".models" / "insightface"


# ============================================================
# ACCEPTED IMAGE FORMATS
# ============================================================

ACCEPTED_FORMATS: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

# ============================================================
# FACE DETECTION — MTCNN
# ============================================================

# Minimum face size (pixels) to detect. Smaller faces are ignored.
MTCNN_MIN_FACE_SIZE: int = 32

# MTCNN detection confidence threshold (0.0 – 1.0).
# Detections below this value are discarded.
MTCNN_CONFIDENCE_THRESHOLD: float = 0.85

# Image size to which aligned faces are resized before embedding.
FACE_IMAGE_SIZE: int = 112

# ============================================================
# FACE EMBEDDING — ArcFace (InsightFace)
# ============================================================

# InsightFace model pack name.
# 'buffalo_l' is the large, high-accuracy pack (ArcFace R100).
INSIGHTFACE_MODEL_NAME: str = "buffalo_l"

# Detection size hint passed to InsightFace app.
INSIGHTFACE_DET_SIZE: tuple[int, int] = (640, 640)

# Batch size for parallel face embedding extraction.
EMBEDDING_BATCH_SIZE: int = 32

# Batch size for image file reading & memory gc chunks.
IMAGE_BATCH_CHUNK: int = 50

# ============================================================
# FEATURE EXTRACTION — CLOTHING COLOR
# ============================================================

# HSV histogram bins per channel (H, S, V).
# Total histogram length = H_BINS * S_BINS * V_BINS.
COLOR_H_BINS: int = 18
COLOR_S_BINS: int = 4
COLOR_V_BINS: int = 4  # Total = 288 bins

# Fraction of image height below the face bbox used as the torso region.
# 0.5 means 50% of the image height below the chin.
TORSO_HEIGHT_FRACTION: float = 0.50

# Width multiplier for the torso region relative to face width.
TORSO_WIDTH_MULTIPLIER: float = 1.5

# ============================================================
# FEATURE FUSION WEIGHTS
# ============================================================
# Must sum to 1.0. These control the contribution of each feature
# type to the final fused embedding vector.

FACE_WEIGHT: float = 0.85        # ArcFace 512-dim embedding
COLOR_WEIGHT: float = 0.10       # HSV clothing histogram
SPATIAL_WEIGHT: float = 0.05     # Bounding box spatial features

# ============================================================
# CLUSTERING — DBSCAN
# ============================================================

# Maximum cosine distance between two points to be considered neighbors.
# 0.42 gives strong identity separation while grouping expressions & lighting.
DBSCAN_EPS: float = 0.42

# Minimum number of face detections required to form a cluster (identity).
DBSCAN_MIN_SAMPLES: int = 2

# ============================================================
# OUTPUT ORGANIZATION
# ============================================================

# Prefix for generated person folder names.
PERSON_FOLDER_PREFIX: str = "Person"

# Folder name for noise / unclassified faces.
UNKNOWN_FOLDER_NAME: str = "Unknown"

# Folder name for low-confidence or misclassified photos.
FLAGGED_FOLDER_NAME: str = "Flagged"

# Folder name for images where no face was detected at all.
NO_FACE_FOLDER_NAME: str = "NoFace"

# If True, images containing multiple faces are copied into
# ALL matching person folders. If False, only the dominant face
# (highest confidence) determines the destination.
COPY_TO_ALL_MATCHED_FOLDERS: bool = True

# ============================================================
# DEBUG / LOGGING
# ============================================================

# Enable verbose debug logging.
DEBUG_MODE: bool = True

# Log file path. Set to None to disable file logging.
LOG_FILE: Path = Path("output/clustering.log")

# Output file for the cluster debug report.
CLUSTERS_JSON_PATH: Path = Path("output/clusters.json")

# Output file for the confidence test report.
CONFIDENCE_REPORT_PATH: Path = Path("output/confidence_report.json")

# t-SNE visualization output path (confidence test).
TSNE_PLOT_PATH: Path = Path("output/tsne_visualization.png")
