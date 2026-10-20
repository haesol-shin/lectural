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
from .urlpolicy import has_url_scheme, is_youtube_url, is_url_like


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


@dataclass(frozen=True)
class InputSource:
    """A classified CLI input and its normalized runtime locator.

    Per-kind facts come from ``lectural.sources``, imported lazily because the
    handlers import this module.
    """

    argument: str
    kind: SourceKind
    locator: str
    title_hint: str
    video_id: str | None
    origin: str | None = None

    @property
    def has_video(self) -> bool:
        from .sources import handler_for

        return handler_for(self).has_video

    @property
    def caption_capable(self) -> bool:
        from .sources import handler_for

        return handler_for(self).caption_capable

    @property
    def citation_kind(self) -> CitationKind:
        from .sources import handler_for

        return handler_for(self).citation_kind

    def as_dict(self) -> dict:
        """Return the JSON-safe source descriptor used by synthesis handoff."""
        citation = {"kind": self.citation_kind.value}
        if self.citation_kind is CitationKind.YOUTUBE:
            citation["video_id"] = self.video_id
        return {
            "kind": self.kind.value,
            "argument": self.origin or self.argument,
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
            argument = self.origin or Path(self.locator).name or "local-media"
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
    if not exists_as_regular_file and is_url_like(argument) and not (
        is_youtube_url(argument) and extract_video_id(argument)
    ):
        if (suffix in _SUPPORTED_SUFFIXES and not has_url_scheme(argument)
                and not argument.startswith("//") and not os.path.isdir(expanded)):
            raise FileNotFoundError("Local source does not exist")
        raise ValueError("Input must be a YouTube URL/ID or an existing supported local file")
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
    if video_id and is_youtube_url(argument):
        return InputSource(
            argument=argument,
            kind=SourceKind.YOUTUBE,
            locator=argument,
            title_hint="",
            video_id=video_id,
        )
    raise ValueError(
        "Input must be a YouTube URL/ID or an existing supported local file"
    )
