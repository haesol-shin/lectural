"""The per-kind questions the shared pipeline asks about a source."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..media import SourceMetadata
    from ..source import CitationKind, InputSource


class SourceHandler(Protocol):
    has_video: bool  # frames, OCR, and visual gates apply
    caption_capable: bool  # captions may replace STT
    citation_kind: CitationKind
    # Recorded when speech is STT and captions were never attempted.
    stt_fallback_code: str | None

    def probe(self, source: InputSource) -> SourceMetadata:
        """Return title, duration, and video id for the source."""

    def resolve_audio(self, source: InputSource, out_dir: str) -> str:
        """Return the audio path used for STT and speech detection."""

    def resolve_video(self, source: InputSource, out_dir: str) -> str | None:
        """Return the video path used for frames, or ``None`` without video."""
