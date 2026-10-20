"""Local media files: read in place, never copied or modified."""

from __future__ import annotations

from .. import media
from ..source import CitationKind, InputSource

# Local files carry no captions, so STT is their only speech source.
_STT_FALLBACK_CODE = "local_source"


def _probe(source: InputSource) -> media.SourceMetadata:
    # Duration comes from the decoded speech track; the file name is the title.
    return media.SourceMetadata(title=source.title_hint)


class LocalVideoHandler:
    has_video = True
    caption_capable = False
    citation_kind = CitationKind.TRANSCRIPT
    stt_fallback_code = _STT_FALLBACK_CODE

    def probe(self, source: InputSource) -> media.SourceMetadata:
        return _probe(source)

    def resolve_audio(self, source: InputSource, out_dir: str) -> str:
        return media.extract_audio(source.locator, out_dir)

    def resolve_video(self, source: InputSource, out_dir: str) -> str:
        return source.locator


class LocalAudioHandler:
    has_video = False
    caption_capable = False
    citation_kind = CitationKind.TRANSCRIPT
    stt_fallback_code = _STT_FALLBACK_CODE

    def probe(self, source: InputSource) -> media.SourceMetadata:
        return _probe(source)

    def resolve_audio(self, source: InputSource, out_dir: str) -> str:
        return source.locator

    def resolve_video(self, source: InputSource, out_dir: str) -> None:
        return None
