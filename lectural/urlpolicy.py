"""Pure URL recognition and safe display labels."""

import os
import re
from urllib.parse import urlsplit

HTTP_SCHEMES = ("http", "https")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_DRIVE = re.compile(r"^[A-Za-z]:(?:\\|/(?!/))")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}


def _parts(value: str):
    try:
        parsed = urlsplit(value)
        if parsed.hostname and not any(c.isspace() for c in parsed.netloc):
            parsed.port
            return parsed
    except ValueError:
        pass
    return None


def is_http_url(value: str) -> bool:
    parts = _parts(value)
    return parts is not None and parts.scheme.lower() in HTTP_SCHEMES


def url_origin(value: str) -> str | None:
    parts = _parts(value)
    if parts is None or not _SCHEME.match(value) or _DRIVE.match(value):
        return None
    host = parts.hostname.lower().rstrip(".")
    if ":" in host:
        host = f"[{host}]"
    return f"{parts.scheme.lower()}://{host}" if host else None


def is_youtube_url(value: str) -> bool:
    candidate = value if "://" in value else f"//{value}" if "/" in value or "." in value else ""
    try:
        parts = urlsplit(candidate)
        if parts.scheme and (parts.scheme.lower() not in HTTP_SCHEMES or not parts.hostname):
            return False
        if not candidate and _SCHEME.match(value):
            return False
        if parts.netloc:
            parts.port
            if any(c.isspace() for c in parts.netloc):
                return False
        return not parts.netloc or (parts.hostname or "").lower().rstrip(".") in _YOUTUBE_HOSTS
    except ValueError:
        return False


def remote_url_origin(value: str) -> str | None:
    return url_origin(value) if is_http_url(value) and not is_youtube_url(value) else None


def has_url_scheme(value: str) -> bool:
    return bool(_SCHEME.match(value) and not _DRIVE.match(value))

def is_url_like(value: str) -> bool:
    if _DRIVE.match(value):
        return False
    head = value.split("/", 1)[0]
    return bool(_SCHEME.match(value) or value.startswith("//") or (
        "." in head and "/" in value and not value.startswith(("/", "./", "../", "~"))
    ))



def public_source_label(value: str) -> str:
    if os.path.isfile(os.path.expanduser(value)) or _DRIVE.match(value):
        return value
    from .source import extract_video_id

    if is_youtube_url(value) and extract_video_id(value):
        return value
    origin = url_origin(value)
    if origin:
        return origin
    if is_url_like(value):
        match = _SCHEME.match(value)
        if match:
            return match.group(0).lower()
        head = value.lstrip("/").split("/", 1)[0]
        return head if "." in head and not any(c in head for c in "@?#") else "url"
    return value
