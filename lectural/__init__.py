"""LecturAL: deterministic evidence extraction for video-based work.

The package is import-safe without heavy runtime dependencies (faster-whisper,
opencv, paddleocr, yt-dlp). Those are imported lazily inside the functions that
need them, so deterministic logic can be unit-tested offline.
"""

from .config import (
    DEDUP_HIST_THRESHOLD,
    DEDUP_SSIM_THRESHOLD,
    MAX_GAP_SEC,
    SCENE_BINS_N,
    SCHEMA_VERSION,
    EXTRACTION_CONTRACT_VERSION,
    EXTRACTION_SCHEMA_VERSION,
)

__all__ = [
    "DEDUP_HIST_THRESHOLD",
    "DEDUP_SSIM_THRESHOLD",
    "MAX_GAP_SEC",
    "SCENE_BINS_N",
    "SCHEMA_VERSION",
    "EXTRACTION_CONTRACT_VERSION",
    "EXTRACTION_SCHEMA_VERSION",
]

__version__ = "0.3.1"
