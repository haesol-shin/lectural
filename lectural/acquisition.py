"""Acquire the speech track for a YouTube video.

Strategy (captions-first, token-zero):
  1. Try captions via youtube-transcript-api / yt-dlp (manual then auto).
  2. If captions are absent/poor OR --force-stt, download audio for STT.

The network/binary calls are isolated; the subtitle PARSERS below are pure
functions over text and are unit-tested offline.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field


@dataclass
class Segment:
    """One timestamped utterance. `t` is the start time in seconds."""

    t: float
    text: str

    def as_dict(self) -> dict:
        return {"t": round(self.t, 3), "text": self.text}


@dataclass
class SpeechTrack:
    segments: list[Segment]
    source: str  # "caption" | "stt"
    language: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.segments


_URL_ID_PATTERNS = [
    re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/)([0-9A-Za-z_-]{11})"),
    re.compile(r"^([0-9A-Za-z_-]{11})$"),
]


def extract_video_id(url: str) -> str | None:
    """Pull the 11-char video id out of a URL or bare id. Pure."""
    url = url.strip()
    for pat in _URL_ID_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


# --- Pure subtitle parsers --------------------------------------------------

_TS_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})")


def _hms_to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def parse_vtt(text: str) -> list[Segment]:
    """Parse WebVTT / SRT-ish caption text into ordered Segments. Pure.

    Handles `HH:MM:SS.mmm --> HH:MM:SS.mmm` cue headers, strips inline tags
    like <c> and positioning, and collapses blank-separated cue bodies.
    """
    segments: list[Segment] = []
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if "-->" in line:
            m = _TS_RE.search(line)
            start = _hms_to_seconds(*m.groups()) if m else 0.0
            i += 1
            body: list[str] = []
            while i < n and lines[i].strip() and "-->" not in lines[i]:
                body.append(lines[i].strip())
                i += 1
            cue = " ".join(body)
            cue = re.sub(r"<[^>]+>", "", cue)  # strip <c>, <00:00:00.000> tags
            cue = re.sub(r"\s+", " ", cue).strip()
            if cue:
                segments.append(Segment(t=start, text=cue))
        else:
            i += 1
    return _dedupe_rolling(segments)


def parse_json3(text: str) -> list[Segment]:
    """Parse YouTube `json3` caption payload into Segments. Pure."""
    data = json.loads(text)
    segments: list[Segment] = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        start_ms = event.get("tStartMs", 0)
        body = "".join(s.get("utf8", "") for s in segs)
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            segments.append(Segment(t=start_ms / 1000.0, text=body))
    return _dedupe_rolling(segments)


def _dedupe_rolling(segments: list[Segment]) -> list[Segment]:
    """Drop consecutive duplicate cue text (common in auto-captions). Pure."""
    out: list[Segment] = []
    for seg in segments:
        if out and out[-1].text == seg.text:
            continue
        out.append(seg)
    return out


def captions_are_usable(segments: list[Segment], min_segments: int = 3) -> bool:
    """Heuristic for "captions present and not garbage". Pure."""
    if len(segments) < min_segments:
        return False
    total_chars = sum(len(s.text) for s in segments)
    return total_chars >= 20


# --- Network/binary-backed acquisition (lazy) ------------------------------

def fetch_caption_segments(video_id: str, languages: tuple[str, ...] = ("ko", "en")) -> list[Segment]:
    """Fetch captions via youtube-transcript-api. Lazy import; may raise."""
    from youtube_transcript_api import YouTubeTranscriptApi  # lazy

    api = YouTubeTranscriptApi()
    fetched = api.fetch(video_id, languages=list(languages))
    segments = [
        Segment(t=float(item.start), text=re.sub(r"\s+", " ", item.text).strip())
        for item in fetched
        if item.text.strip()
    ]
    return _dedupe_rolling(segments)


def download_audio(url: str, out_dir: str) -> str:
    """Download bestaudio as wav via yt-dlp+ffmpeg for STT. Returns path."""
    from .deps import assert_acquisition_ready

    assert_acquisition_ready()
    import os

    os.makedirs(out_dir, exist_ok=True)
    out_template = os.path.join(out_dir, "audio.%(ext)s")
    subprocess.run(
        [
            "yt-dlp", "-x", "--audio-format", "wav",
            "-o", out_template, url,
        ],
        check=True,
    )
    wav = os.path.join(out_dir, "audio.wav")
    if not os.path.exists(wav):
        raise RuntimeError("Audio download did not produce audio.wav")
    return wav


def acquire_speech(
    url: str,
    out_dir: str,
    force_stt: bool = False,
    languages: tuple[str, ...] = ("ko", "en"),
) -> SpeechTrack:
    """Captions-first acquisition with STT fallback. Orchestration only."""
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError(f"Could not extract a YouTube video id from: {url!r}")

    if not force_stt:
        try:
            segs = fetch_caption_segments(video_id, languages)
            if captions_are_usable(segs):
                return SpeechTrack(segments=segs, source="caption", meta={"video_id": video_id})
        except Exception as exc:  # noqa: BLE001 - fall through to STT
            # Captions unavailable/blocked -> STT path.
            _ = exc

    # STT fallback (heavy; delegated to speech.py).
    from .speech import transcribe_audio

    audio_path = download_audio(url, out_dir)
    track = transcribe_audio(audio_path)
    track.meta.setdefault("video_id", video_id)
    return track
