"""LecturAL benchmark suite: offline quality and resource metrics."""

from .metrics import (
    frame_recall_and_duplicate_rate,
    ocr_quality,
    terminology_recall,
    timestamp_error,
    voiced_recall_and_gap,
    wer_cer,
)

__all__ = [
    "frame_recall_and_duplicate_rate",
    "ocr_quality",
    "terminology_recall",
    "timestamp_error",
    "voiced_recall_and_gap",
    "wer_cer",
]
