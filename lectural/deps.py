"""External dependency preflight.

LecturAL relies on external binaries (ffmpeg, yt-dlp) and optional Python
packages (faster-whisper, paddleocr, opencv). None are imported at module
load time. These helpers detect what is available and raise clear, actionable
errors when a required dependency is missing, so failures point at the fix
instead of a deep ImportError/FileNotFoundError stack.
"""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass


class DependencyError(RuntimeError):
    """Raised when a required external dependency is missing."""


@dataclass(frozen=True)
class DepStatus:
    name: str
    kind: str  # "binary" | "python"
    available: bool
    detail: str = ""


# Human-facing install hints (kept English per project convention).
_BINARY_HINTS = {
    "ffmpeg": "Install ffmpeg and put it on PATH. win: winget install Gyan.FFmpeg | linux: apt install ffmpeg (or dnf install ffmpeg) | macos: brew install ffmpeg",
    "yt-dlp": "Install yt-dlp on PATH. win: winget install yt-dlp.yt-dlp (or uv tool install yt-dlp) | linux: uv tool install yt-dlp (or apt install yt-dlp) | macos: brew install yt-dlp",
    "tesseract": "Optional OCR fallback on PATH. win: winget install UB-Mannheim.TesseractOCR | linux: apt install tesseract-ocr (or dnf install tesseract) | macos: brew install tesseract",
}
_PYTHON_HINTS = {
    "faster_whisper": 'Install run extras: `uv pip install "lectural[run]"`.',
    "paddleocr": 'Install run extras: `uv pip install "lectural[run]"`.',
    "cv2": 'Install OpenCV: `uv pip install "lectural[run]"` (provides opencv-python).',
    "youtube_transcript_api": 'Install run extras: `uv pip install "lectural[run]"`.',
    "webrtcvad": 'Optional VAD backend: `uv pip install webrtcvad`.',
}


def has_binary(name: str) -> bool:
    """True when an executable named `name` is resolvable on PATH."""
    return shutil.which(name) is not None


def has_python_module(module: str) -> bool:
    """True when a Python module can be imported without importing it."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def binary_status(name: str) -> DepStatus:
    ok = has_binary(name)
    return DepStatus(
        name=name,
        kind="binary",
        available=ok,
        detail="" if ok else _BINARY_HINTS.get(name, f"Install `{name}` and add it to PATH."),
    )


def python_status(module: str) -> DepStatus:
    ok = has_python_module(module)
    return DepStatus(
        name=module,
        kind="python",
        available=ok,
        detail="" if ok else _PYTHON_HINTS.get(module, f"Install the `{module}` package."),
    )


def require_binary(name: str) -> None:
    """Raise DependencyError with an install hint if `name` is not on PATH."""
    st = binary_status(name)
    if not st.available:
        raise DependencyError(f"Required binary `{name}` not found. {st.detail}")


def require_python_module(module: str) -> None:
    """Raise DependencyError with an install hint if `module` is unimportable."""
    st = python_status(module)
    if not st.available:
        raise DependencyError(f"Required Python module `{module}` not installed. {st.detail}")


def preflight(require_stt: bool = False, require_ocr: bool = False) -> list[DepStatus]:
    """Return the status of every dependency LecturAL may use.

    This never raises; the caller decides which missing pieces are fatal for
    the requested run (e.g. captions-only runs do not need faster-whisper).
    """
    statuses = [
        binary_status("ffmpeg"),
        binary_status("yt-dlp"),
        binary_status("tesseract"),
        python_status("youtube_transcript_api"),
        python_status("faster_whisper"),
        python_status("paddleocr"),
        python_status("cv2"),
        python_status("webrtcvad"),
    ]
    return statuses


def assert_acquisition_ready() -> None:
    """ffmpeg + yt-dlp are the hard requirement for fetching from YouTube."""
    require_binary("yt-dlp")
    require_binary("ffmpeg")
