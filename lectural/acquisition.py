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
import warnings
from dataclasses import dataclass, field

from .config import DEFAULT_STT_MODEL
from .source import InputSource, SourceKind


@dataclass
class Segment:
    """One timestamped utterance in seconds.

    `end` is None only when the source gave no end; `fill_segment_ends`
    resolves it deterministically once the media duration is known.
    """

    t: float
    text: str
    end: float | None = None

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
            stamps = _TS_RE.findall(line)
            start = _hms_to_seconds(*stamps[0]) if stamps else 0.0
            end = _hms_to_seconds(*stamps[1]) if len(stamps) > 1 else None
            i += 1
            body: list[str] = []
            while i < n and lines[i].strip() and "-->" not in lines[i]:
                body.append(lines[i].strip())
                i += 1
            cue = " ".join(body)
            cue = re.sub(r"<[^>]+>", "", cue)  # strip <c>, <00:00:00.000> tags
            cue = re.sub(r"\s+", " ", cue).strip()
            if cue:
                segments.append(Segment(t=start, text=cue, end=end))
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
        duration_ms = event.get("dDurationMs")
        body = "".join(s.get("utf8", "") for s in segs)
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            end = (start_ms + duration_ms) / 1000.0 if duration_ms is not None else None
            segments.append(Segment(t=start_ms / 1000.0, text=body, end=end))
    return _dedupe_rolling(segments)


def _dedupe_rolling(segments: list[Segment]) -> list[Segment]:
    """Merge consecutive duplicate cue text (common in auto-captions). Pure.

    The first cue keeps its start; its end extends to the last duplicate's end.
    """
    out: list[Segment] = []
    for seg in segments:
        if out and out[-1].text == seg.text:
            if seg.end is not None:
                out[-1].end = seg.end
            continue
        out.append(Segment(t=seg.t, text=seg.text, end=seg.end))
    return out


def fill_segment_ends(segments: list[Segment], duration: float) -> list[Segment]:
    """Return segments with every `end` resolved. Pure.

    A missing end becomes the next segment's start, or `duration` for the
    last segment. Ends never precede their start and never exceed `duration`.
    """
    filled: list[Segment] = []
    for index, seg in enumerate(segments):
        end = seg.end
        if end is None:
            end = segments[index + 1].t if index + 1 < len(segments) else duration
        end = min(max(end, seg.t), max(duration, seg.t))
        filled.append(Segment(t=seg.t, text=seg.text, end=end))
    return filled


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
        Segment(
            t=float(item.start),
            text=re.sub(r"\s+", " ", item.text).strip(),
            end=float(item.start) + float(item.duration) if getattr(item, "duration", None) is not None else None,
        )
        for item in fetched
        if item.text.strip()
    ]
    return _dedupe_rolling(segments)




def acquire_speech(
    source: InputSource,
    out_dir: str,
    force_stt: bool = False,
    languages: tuple[str, ...] = ("ko", "en"),
    model: str = DEFAULT_STT_MODEL,
) -> SpeechTrack:
    """Acquire captions when supported, otherwise transcribe resolved audio."""
    from . import media

    source_meta = source.as_dict()
    fallback_reason: str | None = None
    if source.kind is SourceKind.YOUTUBE and not force_stt:
        video_id = source.video_id
        if not video_id:
            raise ValueError(f"Could not extract a YouTube video id from: {source.argument!r}")
        try:
            segs = fetch_caption_segments(video_id, languages)
            if captions_are_usable(segs):
                return SpeechTrack(
                    segments=segs,
                    source="caption",
                    meta={
                        "video_id": video_id,
                        "source_kind": source.kind.value,
                        "input_source": source_meta,
                    },
                )
            fallback_reason = f"captions present but unusable ({len(segs)} cues)"
        except Exception as exc:  # noqa: BLE001
            # youtube-transcript-api raises several distinct types
            # (NoTranscriptFound, TranscriptsDisabled, network errors) that
            # cannot be imported without the optional dep, so we catch broadly
            # here -- but the reason is preserved and surfaced, never discarded.
            fallback_reason = f"caption fetch failed: {type(exc).__name__}: {exc}"
        warnings.warn(
            f"Captions unavailable; falling back to CPU STT. Reason: {fallback_reason}",
            RuntimeWarning,
            stacklevel=2,
        )
    elif source.kind not in (SourceKind.YOUTUBE, SourceKind.LOCAL_VIDEO, SourceKind.LOCAL_AUDIO):
        raise ValueError(f"Unsupported source kind: {source.kind!r}")
    elif force_stt and source.kind is SourceKind.YOUTUBE:
        fallback_reason = "force_stt requested"
        warnings.warn(
            f"Captions unavailable; falling back to CPU STT. Reason: {fallback_reason}",
            RuntimeWarning,
            stacklevel=2,
        )

    # Every STT path resolves its audio through the source-specific media
    # boundary. Local inputs never call the caption API or emit its warning.
    audio_path = media.resolve_audio(source, out_dir)
    from .speech import transcribe_audio

    track = transcribe_audio(audio_path, model_size=model)
    track.meta["audio_path"] = audio_path
    track.meta["source_kind"] = source.kind.value
    track.meta["input_source"] = source_meta
    if source.video_id:
        track.meta.setdefault("video_id", source.video_id)
    if fallback_reason is not None:
        track.meta["caption_fallback_reason"] = fallback_reason
    return track
