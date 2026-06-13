"""Speech-to-text via faster-whisper (CPU, int8).

Used only when captions are unavailable/poor or --force-stt is set.
faster-whisper is imported lazily so the package stays import-safe offline.
"""

from __future__ import annotations

import re

from .acquisition import Segment, SpeechTrack
from .config import (
    DEFAULT_STT_MODEL,
    STT_COMPUTE_TYPE,
    STT_LONG_VIDEO_WARN_SEC,
)


def should_warn_long_video(duration_sec: float, threshold: float = STT_LONG_VIDEO_WARN_SEC) -> bool:
    """Pure: True when CPU STT on this video is expected to be slow."""
    return duration_sec > threshold


def transcribe_audio(
    audio_path: str,
    model_size: str = DEFAULT_STT_MODEL,
    language: str | None = None,
    compute_type: str = STT_COMPUTE_TYPE,
) -> SpeechTrack:
    """Transcribe a local audio file with faster-whisper. Lazy import.

    Returns a SpeechTrack with timestamped segments. `language=None` lets
    faster-whisper auto-detect (ko/en covered).
    """
    from faster_whisper import WhisperModel  # lazy

    model = WhisperModel(model_size, device="cpu", compute_type=compute_type)
    segments_iter, info = model.transcribe(
        audio_path,
        language=language,
        vad_filter=False,  # we run our own VAD/coverage separately
        word_timestamps=False,
    )
    segments: list[Segment] = []
    for seg in segments_iter:
        text = re.sub(r"\s+", " ", seg.text).strip()
        if text:
            segments.append(Segment(t=float(seg.start), text=text))

    return SpeechTrack(
        segments=segments,
        source="stt",
        language=getattr(info, "language", None) or language,
        meta={
            "model": model_size,
            "compute_type": compute_type,
            "duration": float(getattr(info, "duration", 0.0) or 0.0),
        },
    )
