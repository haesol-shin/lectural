"""Source-specific metadata, audio, and video resolution.

The shared pipeline consumes these operations rather than deciding whether an
input is a downloaded asset or an in-place local file.  Local media is never
copied or modified; only generated ``out_dir/audio.wav`` may be written.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
import subprocess

from .deps import assert_acquisition_ready, require_binary
from .source import InputSource, SourceKind, extract_video_id


@dataclass(frozen=True)
class SourceMetadata:
    title: str
    duration: float | None = None
    video_id: str | None = None


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
            "yt-dlp", "--quiet", "--no-warnings", "--skip-download", "--dump-json",
            "--extractor-args", "youtube:player_client=android", url,
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


def _probe_youtube(source: InputSource) -> SourceMetadata:
    metadata = fetch_video_metadata(source.locator)
    return SourceMetadata(
        title=metadata.get("title") or source.video_id or "",
        duration=metadata.get("duration"),
        video_id=metadata.get("video_id") or source.video_id,
    )


def _probe_local_video(source: InputSource) -> SourceMetadata:
    return SourceMetadata(title=source.title_hint)


def _probe_local_audio(source: InputSource) -> SourceMetadata:
    return SourceMetadata(title=source.title_hint)


# Keep each SourceKind explicit: adding a source kind must update all three
# boundaries rather than silently taking a generic fallback.
_PROBE_RESOLVERS = {
    SourceKind.YOUTUBE: _probe_youtube,
    SourceKind.LOCAL_VIDEO: _probe_local_video,
    SourceKind.LOCAL_AUDIO: _probe_local_audio,
}


def probe_source(source: InputSource) -> SourceMetadata:
    """Resolve source metadata using the source-kind-specific handler."""
    resolver = _PROBE_RESOLVERS[source.kind]
    return resolver(source)


def download_audio(url: str, out_dir: str) -> str:
    """Download YouTube bestaudio as a generated WAV file."""
    assert_acquisition_ready()
    os.makedirs(out_dir, exist_ok=True)
    out_template = os.path.join(out_dir, "audio.%(ext)s")
    subprocess.run(
        [
            "yt-dlp", "--quiet", "--no-warnings", "--no-progress",
            "--extractor-args", "youtube:player_client=android",
            "-x", "--audio-format", "wav", "-o", out_template, url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wav = os.path.join(out_dir, "audio.wav")
    if not os.path.exists(wav):
        raise RuntimeError("Audio download did not produce audio.wav")
    return wav


def _resolve_audio_youtube(source: InputSource, out_dir: str) -> str:
    return download_audio(source.locator, out_dir)


def _resolve_audio_local_audio(source: InputSource, out_dir: str) -> str:
    return source.locator


def _resolve_audio_local_video(source: InputSource, out_dir: str) -> str:
    require_binary("ffmpeg")
    os.makedirs(out_dir, exist_ok=True)
    audio_path = os.path.join(out_dir, "audio.wav")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", source.locator,
            "-vn", "-acodec", "pcm_s16le", audio_path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    if not os.path.isfile(audio_path):
        raise RuntimeError("Audio extraction did not produce audio.wav")
    return audio_path


_AUDIO_RESOLVERS = {
    SourceKind.YOUTUBE: _resolve_audio_youtube,
    SourceKind.LOCAL_VIDEO: _resolve_audio_local_video,
    SourceKind.LOCAL_AUDIO: _resolve_audio_local_audio,
}


def resolve_audio(source: InputSource, out_dir: str) -> str:
    """Resolve a source to an audio path for STT."""
    return _AUDIO_RESOLVERS[source.kind](source, out_dir)


def _download_video(url: str, out_dir: str) -> str:
    """Download YouTube video for frame extraction."""
    assert_acquisition_ready()
    os.makedirs(out_dir, exist_ok=True)
    out_template = os.path.join(out_dir, "video.%(ext)s")
    subprocess.run(
        [
            "yt-dlp", "--quiet", "--no-warnings", "--no-progress",
            "--extractor-args", "youtube:player_client=android",
            "-f", "bestvideo[height<=720]+bestaudio/best",
            "-o", out_template, url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    for name in os.listdir(out_dir):
        if name.startswith("video."):
            return os.path.join(out_dir, name)
    raise RuntimeError("Video download did not produce a video file")


def _resolve_video_youtube(source: InputSource, out_dir: str) -> str:
    return _download_video(source.locator, out_dir)


def _resolve_video_local_video(source: InputSource, out_dir: str) -> str:
    return source.locator


def _resolve_video_local_audio(source: InputSource, out_dir: str) -> None:
    return None


_VIDEO_RESOLVERS = {
    SourceKind.YOUTUBE: _resolve_video_youtube,
    SourceKind.LOCAL_VIDEO: _resolve_video_local_video,
    SourceKind.LOCAL_AUDIO: _resolve_video_local_audio,
}


def resolve_video(source: InputSource, out_dir: str) -> str | None:
    """Resolve the source video path, or ``None`` for audio-only input."""
    return _VIDEO_RESOLVERS[source.kind](source, out_dir)
