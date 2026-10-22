"""External media tools (yt-dlp, ffmpeg, ffprobe) and the source asset seam.

``probe_source``, ``resolve_audio``, and ``resolve_video`` are what the shared
pipeline calls and tests patch; they delegate to the per-kind handlers in
``lectural.sources``, imported lazily because those handlers call back into the
tool wrappers here.  Local media is never copied or modified; only generated
``out_dir/audio.wav`` may be written.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
import subprocess
import sys

from .deps import assert_acquisition_ready, require_binary
from .source import InputSource, extract_video_id


@dataclass(frozen=True)
class SourceMetadata:
    title: str
    duration: float | None = None
    video_id: str | None = None
    width: int | None = None
    height: int | None = None


def _metadata_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _positive_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def parse_ytdlp_metadata(text: str) -> dict:
    """Parse ``yt-dlp --dump-json`` output into LecturAL metadata."""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("yt-dlp metadata JSON must be an object")

    metadata: dict = {}
    title = _metadata_text(data.get("title"))
    if title:
        metadata["title"] = title
    duration = _positive_float(data.get("duration"))
    if duration is not None:
        metadata["duration"] = duration
    video_id = _metadata_text(data.get("id") or data.get("display_id"))
    if video_id:
        metadata["video_id"] = video_id
    return metadata


def fetch_video_metadata(url: str) -> dict:
    """Fetch YouTube title/duration/video ID without downloading media."""
    require_binary("yt-dlp")
    proc = subprocess.run(
        [
            "yt-dlp",
            "--quiet",
            "--no-warnings",
            "--skip-download",
            "--dump-json",
            "--extractor-args",
            "youtube:player_client=android",
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    metadata = parse_ytdlp_metadata(proc.stdout)
    fallback_id = extract_video_id(url)
    if fallback_id:
        metadata.setdefault("video_id", fallback_id)
    return metadata


def probe_source(source: InputSource) -> SourceMetadata:
    """Resolve source metadata through the source's handler."""
    from .sources import handler_for

    return handler_for(source).probe(source)


def download_audio(url: str, out_dir: str) -> str:
    """Download YouTube bestaudio as a generated WAV file."""
    assert_acquisition_ready()
    os.makedirs(out_dir, exist_ok=True)
    out_template = os.path.join(out_dir, "audio.%(ext)s")
    subprocess.run(
        [
            "yt-dlp",
            "--quiet",
            "--no-warnings",
            "--no-progress",
            "--extractor-args",
            "youtube:player_client=android",
            "-x",
            "--audio-format",
            "wav",
            "-o",
            out_template,
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wav = os.path.join(out_dir, "audio.wav")
    if not os.path.exists(wav):
        raise RuntimeError("Audio download did not produce audio.wav")
    return wav


def extract_audio(path: str, out_dir: str) -> str:
    """Extract the audio track of a local video into a generated WAV file."""
    require_binary("ffmpeg")
    os.makedirs(out_dir, exist_ok=True)
    audio_path = os.path.join(out_dir, "audio.wav")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostats",
            "-y",
            "-i",
            path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            audio_path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    if not os.path.isfile(audio_path):
        raise RuntimeError("Audio extraction did not produce audio.wav")
    return audio_path


def resolve_audio(source: InputSource, out_dir: str) -> str:
    """Resolve a source to an audio path for STT."""
    from .sources import handler_for

    return handler_for(source).resolve_audio(source, out_dir)


def download_video(url: str, out_dir: str) -> str:
    """Download YouTube video for frame extraction."""
    assert_acquisition_ready()
    os.makedirs(out_dir, exist_ok=True)
    out_template = os.path.join(out_dir, "video.%(ext)s")
    subprocess.run(
        [
            "yt-dlp",
            "--quiet",
            "--no-warnings",
            "--no-progress",
            "--extractor-args",
            "youtube:player_client=android",
            "-f",
            "bestvideo[height<=720]+bestaudio/best",
            "-o",
            out_template,
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    for name in os.listdir(out_dir):
        if name.startswith("video."):
            return os.path.join(out_dir, name)
    raise RuntimeError("Video download did not produce a video file")


def resolve_video(source: InputSource, out_dir: str) -> str | None:
    """Resolve the source video path, or ``None`` for audio-only input."""
    from .sources import handler_for

    return handler_for(source).resolve_video(source, out_dir)


def probe_video_resolution(video_path: str) -> tuple[int | None, int | None]:
    """Read dimensions from the exact video file used for frame extraction."""
    require_binary("ffprobe")
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                video_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        if isinstance(exc.stderr, str) and exc.stderr.strip():
            print(exc.stderr.strip()[-500:], file=sys.stderr)
        return None, None
    streams = json.loads(proc.stdout).get("streams", [])
    stream = streams[0] if streams else {}
    width, height = stream.get("width"), stream.get("height")
    return (
        int(width) if isinstance(width, int) and width > 0 else None,
        int(height) if isinstance(height, int) and height > 0 else None,
    )
