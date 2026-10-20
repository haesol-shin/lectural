"""Pure source classification and source-aware citation metadata.

The CLI accepts a YouTube URL/ID, a public ``http(s)`` media URL, or one of the
supported local media files.  This module deliberately contains no network,
subprocess, or media processing code; it is the boundary shared by
acquisition and orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import os
import re
from urllib.parse import urlparse, urlsplit


class SourceKind(str, Enum):
    YOUTUBE = "youtube"
    LOCAL_VIDEO = "local_video"
    LOCAL_AUDIO = "local_audio"
    # Internal only: a remote URL is fetched into a temporary local file
    # before extraction, so evidence records it as local_video/local_audio.
    REMOTE = "remote"


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
_REMOTE_SCHEMES = ("http", "https")
# A URL scheme: any scheme followed by ``//``, a dot-free scheme of two or more
# characters (``data:``, ``javascript:``), or one letter not followed by a path
# separator (``x:v=...``).  ``C:\`` / ``C:/`` is a Windows drive, and a dotted
# name without ``//`` is a ``host:port`` form.
_SCHEME_RE = re.compile(
    r"^(?:([A-Za-z][A-Za-z0-9+.-]*):(?=//)|([A-Za-z][A-Za-z0-9+-]+):|([A-Za-z]):(?![/\\]))"
)
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
_INVALID_SOURCE_MESSAGE = (
    "Input must be a YouTube URL/ID, a public http(s) media URL, "
    "or an existing supported local file"
)


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
    return host in _YOUTUBE_HOSTS


def _url_scheme(value: str) -> str | None:
    match = _SCHEME_RE.match(value.strip())
    return next(group for group in match.groups() if group).lower() if match else None


def url_origin(value: str) -> str:
    """Return only ``scheme://host`` (or ``scheme:``) of a URL-like value.

    Path, query, fragment, port, and user information are dropped because
    signed tokens can appear in any of them.
    """
    scheme = _url_scheme(value) or ""
    try:
        host = (urlsplit(value.strip()).hostname or "").rstrip(".")
    except ValueError:
        host = ""
    if not scheme:
        return "url"
    if not host:
        return f"{scheme}:"
    if ":" in host:
        host = f"[{host}]"
    return f"{scheme}://{host}"


def remote_url_origin(value: str) -> str | None:
    """Return the origin of an accepted remote (non-YouTube) URL, else None."""
    if _url_scheme(value) not in _REMOTE_SCHEMES:
        return None
    try:
        host = (urlsplit(value.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if not host or host in _YOUTUBE_HOSTS:
        return None
    return url_origin(value)


# ``host.tld[:port]`` followed by a path, query, or fragment: a URL typed
# without a scheme.  It is never accepted, but must not be echoed either.
_SCHEMELESS_URL_RE = re.compile(r"^([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)(?::\d+)?[/?#]")


def _url_label(value: str) -> str | None:
    """Return a token-free label for a URL-like value, or None for other text."""
    if _url_scheme(value) is not None:
        return url_origin(value)
    match = _SCHEMELESS_URL_RE.match(value.strip())
    if match:
        return match.group(1).lower().rstrip(".")
    if any(mark in value for mark in "?#&="):
        return "url"
    return None


def _echo_safe(argument: str) -> str:
    label = _url_label(argument)
    return f"({label})" if label is not None else repr(argument)


def public_source_label(argument: str) -> str:
    """Return a CLI argument as it may appear in logs and run state.

    Local paths and YouTube inputs keep their existing form; any other
    URL-like value is reduced to its origin.
    """
    if not isinstance(argument, str) or os.path.exists(os.path.expanduser(argument)):
        return argument
    if extract_video_id(argument) and _is_youtube_url(argument) and _url_scheme(argument) in (None, *_REMOTE_SCHEMES):
        return argument
    label = _url_label(argument)
    return argument if label is None else label


@dataclass(frozen=True)
class InputSource:
    """A classified CLI input and its normalized runtime locator."""

    argument: str
    kind: SourceKind
    locator: str
    title_hint: str
    video_id: str | None
    # ``scheme://host`` for URL inputs fetched by LecturAL; never the full URL.
    origin: str | None = None

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
            "argument": self.origin or self.argument,
            "has_video": self.has_video,
            "citation": citation,
        }

    def safe_as_dict(self) -> dict:
        """Return a portable source descriptor without private input paths.

        The legacy ``as_dict`` shape remains available to callers that already
        own the raw CLI argument.  Public extraction artifacts use this bounded
        descriptor instead: local inputs retain only their filename, fetched
        URLs only their origin, and YouTube inputs only the canonical video ID.
        """
        citation = {"kind": self.citation_kind.value}
        if self.citation_kind is CitationKind.YOUTUBE:
            citation["video_id"] = self.video_id
            argument = f"https://youtu.be/{self.video_id}" if self.video_id else "youtube"
        elif self.origin:
            argument = self.origin
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
        raise ValueError(_INVALID_SOURCE_MESSAGE)

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
        raise ValueError(f"{_INVALID_SOURCE_MESSAGE}: {argument!r}")

    video_id = extract_video_id(argument)
    is_youtube = bool(video_id) and _is_youtube_url(argument)
    scheme = _url_scheme(argument)
    # Never echo a URL in these errors: its path or query may carry tokens.
    if scheme is not None and scheme not in _REMOTE_SCHEMES:
        raise ValueError(
            f"{_INVALID_SOURCE_MESSAGE}; only http and https URLs are accepted ({url_origin(argument)})"
        )
    if scheme is not None and not is_youtube:
        origin = remote_url_origin(argument)
        if origin is None:
            raise ValueError(f"{_INVALID_SOURCE_MESSAGE} ({url_origin(argument)})")
        return InputSource(
            argument=argument,
            kind=SourceKind.REMOTE,
            locator=argument.strip(),
            title_hint="",
            video_id=None,
            origin=origin,
        )

    if suffix in _SUPPORTED_SUFFIXES:
        raise FileNotFoundError(f"Local source does not exist: {_echo_safe(argument)}")

    if is_youtube:
        return InputSource(
            argument=argument,
            kind=SourceKind.YOUTUBE,
            locator=argument,
            title_hint="",
            video_id=video_id,
        )
    raise ValueError(f"{_INVALID_SOURCE_MESSAGE}: {_echo_safe(argument)}")
