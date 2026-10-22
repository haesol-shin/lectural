"""Validate downloaded containers and assemble local split streams."""

import json
import os
import subprocess
from dataclasses import dataclass

from ..deps import require_binary
from . import http
from .errors import UNAVAILABLE, RemoteSourceError

INPUT_GUARD = (
    "-protocol_whitelist",
    "file",
    "-format_whitelist",
    "mov,matroska,mp3,aac,ogg,wav,w64,flac,aiff,caf,mpegts,flv,avi,asf,mpeg",
)


@dataclass(frozen=True)
class FetchedMedia:
    path: str
    has_video: bool


def probe(path: str) -> bool:
    require_binary("ffprobe")
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                *INPUT_GUARD,
                "-show_entries",
                "stream=codec_type:stream_disposition=attached_pic",
                "-of",
                "json",
                path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        streams = json.loads(result.stdout).get("streams") or []
        if not any(stream.get("codec_type") in ("audio", "video") for stream in streams):
            raise ValueError("no media streams")
        return any(
            stream.get("codec_type") == "video" and not (stream.get("disposition") or {}).get("attached_pic")
            for stream in streams
        )
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        raise RemoteSourceError(UNAVAILABLE) from None


def merge(video_path: str, audio_path: str, dest_dir: str) -> str:
    require_binary("ffmpeg")
    merged = os.path.join(dest_dir, "media.mkv")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                *INPUT_GUARD,
                "-i",
                video_path,
                *INPUT_GUARD,
                "-i",
                audio_path,
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c",
                "copy",
                "-f",
                "matroska",
                "-y",
                merged,
            ],
            check=True,
            capture_output=True,
        )
        for path in (video_path, audio_path):
            os.remove(path)
    except (OSError, subprocess.SubprocessError):
        raise RemoteSourceError(UNAVAILABLE) from None
    return merged


def download_formats(formats: list[dict], dest_dir: str) -> FetchedMedia:
    paths = []
    for index, fmt in enumerate(formats):
        headers = {
            str(k): str(v)
            for k, v in (fmt.get("http_headers") or {}).items()
            if str(k).lower() not in {"cookie", "authorization", "proxy-authorization"}
        }
        response = http.open_url(fmt["url"], headers)
        stem = "media" if len(formats) == 1 else f"stream{index}"
        path = os.path.join(
            dest_dir,
            http.media_filename(
                response.headers.get_content_type(),
                fmt.get("ext"),
                stem,
            ),
        )
        http.stream_to_file(response, path)
        paths.append(path)
    has_video = probe(paths[0])
    if len(paths) == 1:
        return FetchedMedia(paths[0], has_video)
    if not has_video:
        raise RemoteSourceError(UNAVAILABLE)
    probe(paths[1])
    return FetchedMedia(merge(*paths, dest_dir), True)
