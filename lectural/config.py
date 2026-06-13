"""Named configuration constants for the LecturAL pipeline.

These are the tunable knobs the consensus plan required to be explicit,
named constants (not magic numbers scattered through the code).
"""

from __future__ import annotations

# --- Synthesis contract ----------------------------------------------------
# Bump when the synthesis_input.json shape changes incompatibly.
SCHEMA_VERSION: int = 1

# --- Frame dedup -----------------------------------------------------------
# Two consecutive frames are considered the SAME slide when their colour
# histogram correlation is at or above this threshold AND their structural
# similarity (SSIM) is at or above DEDUP_SSIM_THRESHOLD. Range 0..1.
DEDUP_HIST_THRESHOLD: float = 0.90
DEDUP_SSIM_THRESHOLD: float = 0.92

# --- Speech-gap coverage ---------------------------------------------------
# A completeness FAIL occurs when there is a contiguous span of *speech*
# (per the VAD/silence mask) longer than this many seconds that has no
# transcript coverage. Silence does not count against coverage.
MAX_GAP_SEC: float = 60.0
# A single caption/STT cue is assumed to cover at most this many seconds of
# speech. Beyond this, the span between cues counts as untranscribed (so a
# long cue-less stretch during speech is detected as a real gap).
CUE_MAX_COVER_SEC: float = 30.0

# --- Scene coverage --------------------------------------------------------
# The timeline is divided into this many equal bins; each bin that contains
# speech must also contain at least one extracted keyframe for scene
# coverage to pass.
SCENE_BINS_N: int = 20

# --- Visual extraction -----------------------------------------------------
# Temporal downsample cap (frames per second) before scene detection.
SAMPLE_FPS: float = 2.0

# --- Speech / STT ----------------------------------------------------------
# Default faster-whisper model + compute type (CPU-friendly).
DEFAULT_STT_MODEL: str = "medium"
STT_COMPUTE_TYPE: str = "int8"
# Warn (and let the caller decide) when a video to be transcribed by STT is
# longer than this, because CPU transcription of long videos is slow.
STT_LONG_VIDEO_WARN_SEC: float = 45 * 60.0

# --- OCR -------------------------------------------------------------------
# A frame is classified as a "slide" (and therefore expected to contain OCR
# text) when its OCR text has at least this many non-whitespace characters.
SLIDE_MIN_TEXT_CHARS: int = 12

# --- Incremental-slide re-split --------------------------------------------
# When a frame's OCR text is a superset of the previous frame's text and adds
# at least this fraction of new characters, it is treated as a NEW
# incremental slide rather than a duplicate of the previous one.
INCREMENTAL_SLIDE_MIN_GROWTH: float = 0.15
