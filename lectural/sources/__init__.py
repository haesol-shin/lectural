"""Per-kind source handlers: the one place a ``SourceKind`` maps to behavior."""

from __future__ import annotations

from ..source import InputSource, SourceKind
from .base import SourceHandler
from .local import LocalAudioHandler, LocalVideoHandler
from .youtube import YouTubeHandler

_HANDLERS: dict[SourceKind, SourceHandler] = {
    SourceKind.YOUTUBE: YouTubeHandler(),
    SourceKind.LOCAL_VIDEO: LocalVideoHandler(),
    SourceKind.LOCAL_AUDIO: LocalAudioHandler(),
}


def handler_for(source: InputSource) -> SourceHandler:
    try:
        return _HANDLERS[source.kind]
    except KeyError:
        raise ValueError(f"Unsupported source kind: {source.kind!r}") from None


__all__ = ["SourceHandler", "handler_for"]
