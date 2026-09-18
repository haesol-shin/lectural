"""Pure source classification and source-aware citation metadata.

The CLI accepts either a YouTube URL/ID or one of the supported local media
files.  This module deliberately contains no network, subprocess, or media
processing code; it is the boundary shared by acquisition and orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import os
import re
from urllib.parse import urlparse


class SourceKind(str, Enum):
    YOUTUBE = "youtube"
    LOCAL_VIDEO = "local_video"
    LOCAL_AUDIO = "local_audio"


class CitationKind(str, Enum):
    YOUTUBE = "youtube"
    TRANSCRIPT = "transcript"


_URL_ID_PATTERNS = [
    re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/)([0-9A-Za-z_-]{11})"),
    re.compile(r"^([0-9A-Za-z_-]{11})$"),
]
_SUPPORTED_VIDEO_SUFFIXES = (".mp4", ".webm", ".mkv")
_SUPPORTED_AUDIO_SUFFIXES = (".wav",)
_SUPPORTED_SUFFIXES = _SUPPORTED_VIDEO_SUFFIXES + _SUPPORTED_AUDIO_SUFFIXES


def extract_video_id(url: str) -> str | None:
    """Pull the 11-character video ID from a YouTube URL or bare ID."""
    value = url.strip()
    for pattern in _URL_ID_PATTERNS:
        match = pattern.search(value)
        if match:
            return match.group(1)
    return None

def _is_youtube_url(value: str) -> bool:
    # Bare IDs (and the existing scheme-less ``v=...`` form) have no host.
    candidate = value if "://" in value else f"//{value}" if "/" in value or "." in value else ""
    parsed = urlparse(candidate)
    if not parsed.netloc:
        return True
    host = (parsed.hostname or "").lower().rstrip(".")
    return host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}

@dataclass(frozen=True)
class InputSource:
    """A classified CLI input and its normalized runtime locator."""

    argument: str
    kind: SourceKind
    locator: str
    title_hint: str
    video_id: str | None

    @property
    def has_video(self) -> bool:
        return self.kind in (SourceKind.YOUTUBE, SourceKind.LOCAL_VIDEO)

    @property
    def caption_capable(self) -> bool:
        return self.kind is SourceKind.YOUTUBE

    @property
    def citation_kind(self) -> CitationKind:
        return CitationKind.YOUTUBE if self.kind is SourceKind.YOUTUBE else CitationKind.TRANSCRIPT

    def as_dict(self) -> dict:
        """Return the JSON-safe source descriptor used by synthesis handoff."""
        citation = {"kind": self.citation_kind.value}
        if self.citation_kind is CitationKind.YOUTUBE:
            citation["video_id"] = self.video_id
        return {
            "kind": self.kind.value,
            "argument": self.argument,
            "has_video": self.has_video,
            "citation": citation,
        }

    def safe_as_dict(self) -> dict:
        """Return a portable source descriptor without private input paths.

        The legacy ``as_dict`` shape remains available to callers that already
        own the raw CLI argument.  Public extraction artifacts use this bounded
        descriptor instead: local inputs retain only their filename and YouTube
        inputs retain only the canonical video ID.
        """
        citation = {"kind": self.citation_kind.value}
        if self.citation_kind is CitationKind.YOUTUBE:
            citation["video_id"] = self.video_id
            argument = f"https://youtu.be/{self.video_id}" if self.video_id else "youtube"
        else:
            argument = Path(self.locator).name or "local-media"
        return {
            "kind": self.kind.value,
            "argument": argument,
            "has_video": self.has_video,
            "citation": citation,
        }


def _normalized_local_path(argument: str) -> str:
    # realpath both resolves symlinks and normalizes the absolute runtime path.
    return os.path.realpath(os.path.abspath(os.path.expanduser(argument)))


def _unsupported_local_type(argument: str) -> ValueError:
    accepted = ", ".join(_SUPPORTED_SUFFIXES)
    return ValueError(f"Unsupported local file type for {argument!r}; accepted suffixes: {accepted}")


def classify_source(argument: str) -> InputSource:
    """Classify one CLI argument without touching or mutating local media."""
    if not isinstance(argument, str):
        raise ValueError("Input must be a YouTube URL/ID or an existing supported local file")

    expanded = os.path.expanduser(argument)
    suffix = Path(expanded).suffix.lower()
    exists_as_regular_file = os.path.isfile(expanded)
    if exists_as_regular_file:
        locator = _normalized_local_path(argument)
        if suffix in _SUPPORTED_VIDEO_SUFFIXES:
            kind = SourceKind.LOCAL_VIDEO
        elif suffix in _SUPPORTED_AUDIO_SUFFIXES:
            kind = SourceKind.LOCAL_AUDIO
        else:
            raise _unsupported_local_type(argument)
        return InputSource(
            argument=argument,
            kind=kind,
            locator=locator,
            title_hint=Path(locator).stem,
            video_id=None,
        )

    if os.path.isdir(expanded):
        raise ValueError(
            f"Input must be a YouTube URL/ID or an existing supported local file: {argument!r}"
        )
    if suffix in _SUPPORTED_SUFFIXES:
        raise FileNotFoundError(f"Local source does not exist: {argument!r}")

    video_id = extract_video_id(argument)
    if video_id and _is_youtube_url(argument):
        return InputSource(
            argument=argument,
            kind=SourceKind.YOUTUBE,
            locator=argument,
            title_hint="",
            video_id=video_id,
        )
    raise ValueError(
        f"Input must be a YouTube URL/ID or an existing supported local file: {argument!r}"
    )
