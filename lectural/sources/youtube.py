"""YouTube sources: metadata and media are fetched with yt-dlp."""

from __future__ import annotations

from .. import media
from ..source import InputSource


class YouTubeHandler:
    def probe(self, source: InputSource) -> media.SourceMetadata:
        metadata = media.fetch_video_metadata(source.locator)
        return media.SourceMetadata(
            title=metadata.get("title") or source.video_id or "",
            duration=metadata.get("duration"),
            video_id=metadata.get("video_id") or source.video_id,
        )

    def resolve_audio(self, source: InputSource, out_dir: str) -> str:
        return media.download_audio(source.locator, out_dir)

    def resolve_video(self, source: InputSource, out_dir: str) -> str:
        return media._download_video(source.locator, out_dir)
