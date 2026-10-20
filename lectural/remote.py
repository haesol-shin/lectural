"""Fetch a public ``http(s)`` media URL into a temporary local file.

Only public URLs are supported: no cookie jar, no credentials, and no
configuration that could add them.  Every request LecturAL makes itself goes
through an opener that speaks only HTTP/HTTPS and refuses redirects to any
other scheme.  yt-dlp is used only to resolve a page URL to one progressive
``http(s)`` media URL; LecturAL downloads that URL itself.

Fetched media and audio derived from it live only in a private temporary
directory that ``materialize`` removes after success and failure.  Errors are
bounded codes; neither the URL path/query nor tool output is ever surfaced.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import http.client
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Iterator
import urllib.error
import urllib.request
from urllib.parse import unquote, urljoin, urlsplit

from .deps import require_binary
from .evidence import ContractError, failure
from .source import InputSource, SourceKind

_ALLOWED_SCHEMES = ("http", "https")
_ALLOWED_PROTOCOLS = ("http", "https")
_REQUEST_TIMEOUT_SEC = 60
_RESOLVE_TIMEOUT_SEC = 300
_CHUNK_BYTES = 1024 * 1024
_MAX_REDIRECTS = 10
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# Single progressive files only: no merge, no HLS/DASH fragments.
_FORMAT_SELECTOR = "b[protocol=https]/b[protocol=http]/ba[protocol=https]/ba[protocol=http]"
_UNAUTHORIZED_HINTS = (
    "http error 401", "http error 403", "http error 407", "login", "log in",
    "sign in", "cookies", "private", "authentication", "members-only",
)
_DROPPED_HEADERS = {"cookie", "authorization", "proxy-authorization"}
_TOKEN_MIN_LENGTH = 6
_WORD_TOKEN_MIN_LENGTH = 3


class RemoteSourceError(ContractError):
    """A bounded remote-source failure whose message never contains the URL."""

    def __init__(self, code: str):
        super().__init__(code, failure(code)["message"])


@dataclass(frozen=True)
class FetchedMedia:
    path: str
    has_video: bool
    title: str


@dataclass(frozen=True)
class Materialized:
    """A source ready for extraction plus the scratch directory it owns."""

    source: InputSource
    scratch_dir: str | None


def _scheme(url: str) -> str:
    try:
        return (urlsplit(url).scheme or "").lower()
    except ValueError:
        return ""


class _HttpOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = _MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _scheme(urljoin(req.full_url, newurl)) not in _ALLOWED_SCHEMES:
            raise RemoteSourceError("SOURCE_REDIRECT_REJECTED")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    # Built by hand so no file:, data:, ftp: handler or cookie processor exists.
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler(),
        urllib.request.UnknownHandler(),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        _HttpOnlyRedirectHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def _bounded(exc: BaseException) -> RemoteSourceError:
    if isinstance(exc, RemoteSourceError):
        return exc
    if isinstance(exc, urllib.error.HTTPError):
        exc.close()
        if exc.code in (401, 403, 407):
            return RemoteSourceError("SOURCE_UNAUTHORIZED")
        if 300 <= exc.code < 400 and "loop" not in str(exc.msg).lower():
            # urllib refuses non-http(s)/ftp redirect targets before our handler runs.
            return RemoteSourceError("SOURCE_REDIRECT_REJECTED")
    return RemoteSourceError("SOURCE_UNAVAILABLE")


def _open(url: str, headers: dict[str, str] | None = None):
    if _scheme(url) not in _ALLOWED_SCHEMES:
        raise RemoteSourceError("SOURCE_INVALID")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    try:
        return _opener().open(request, timeout=_REQUEST_TIMEOUT_SEC)
    except (OSError, http.client.HTTPException, ValueError, RemoteSourceError) as exc:
        raise _bounded(exc) from None


def _content_type(response) -> str:
    return (response.headers.get_content_type() or "").lower()


def _media_filename(content_type: str, ext: str | None = None) -> str:
    suffix = f".{ext}" if ext and re.fullmatch(r"[A-Za-z0-9]{1,8}", ext) else None
    suffix = suffix or mimetypes.guess_extension(content_type) or ".media"
    return f"media{suffix}"


def _stream_to_file(response, path: str) -> None:
    declared = response.headers.get("Content-Length")
    try:
        with response, open(path, "wb") as out:
            while chunk := response.read(_CHUNK_BYTES):
                out.write(chunk)
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise _bounded(exc) from None
    size = os.path.getsize(path)
    # http.client returns a short body silently when the peer closes early.
    if size == 0 or (declared and declared.strip().isdigit() and size != int(declared)):
        raise RemoteSourceError("SOURCE_UNAVAILABLE")


def _url_tokens(url: str) -> set[str]:
    parts = urlsplit(url)
    text = unquote("/".join((parts.path, parts.query, parts.fragment)))
    return {piece.lower() for piece in re.split(r"[^0-9A-Za-z]+", text) if len(piece) >= _WORD_TOKEN_MIN_LENGTH}


def _echoes_token(title: str, token: str) -> bool:
    # Long pieces (IDs, signatures) must not appear anywhere; short path words
    # such as a file stem must not appear as a whole word.
    if len(token) >= _TOKEN_MIN_LENGTH:
        return token in title
    return re.search(rf"(?<![0-9a-z]){re.escape(token)}(?![0-9a-z])", title) is not None


def _host_label(url: str) -> str:
    return (urlsplit(url).hostname or "media").rstrip(".")


def _safe_title(info: dict, url: str) -> str:
    """Keep an extractor title only when it cannot echo the URL path/query."""
    title = re.sub(r"\s+", " ", str(info.get("title") or "")).strip()
    if not title or str(info.get("extractor_key") or "").lower() == "generic":
        return _host_label(url)
    lowered = title.lower()
    if any(_echoes_token(lowered, token) for token in _url_tokens(url)):
        return _host_label(url)
    return title[:200]


def _resolve_with_ytdlp(url: str) -> dict:
    """Return yt-dlp's single selected progressive format for ``url``."""
    require_binary("yt-dlp")
    try:
        proc = subprocess.run(
            [
                "yt-dlp", "--ignore-config", "--no-cookies", "--no-cookies-from-browser",
                "--no-playlist", "--quiet", "--no-warnings", "--no-progress",
                "--skip-download", "--dump-single-json", "-f", _FORMAT_SELECTOR, "--", url,
            ],
            capture_output=True, text=True, timeout=_RESOLVE_TIMEOUT_SEC,
        )
    except (OSError, subprocess.SubprocessError):
        raise RemoteSourceError("SOURCE_UNAVAILABLE") from None
    if proc.returncode != 0:
        # yt-dlp messages contain the URL; classify them, never print them.
        stderr = (proc.stderr or "").lower()
        code = "SOURCE_UNAUTHORIZED" if any(hint in stderr for hint in _UNAUTHORIZED_HINTS) else "SOURCE_UNAVAILABLE"
        raise RemoteSourceError(code)
    try:
        info = json.loads(proc.stdout)
    except ValueError:
        raise RemoteSourceError("SOURCE_UNAVAILABLE") from None
    if not isinstance(info, dict) or info.get("entries") is not None or info.get("requested_formats"):
        raise RemoteSourceError("SOURCE_UNAVAILABLE")
    media_url = info.get("url")
    if (
        not isinstance(media_url, str)
        or _scheme(media_url) not in _ALLOWED_SCHEMES
        or str(info.get("protocol") or "").lower() not in _ALLOWED_PROTOCOLS
    ):
        raise RemoteSourceError("SOURCE_UNAVAILABLE")
    return info


def _has_video_stream(path: str) -> bool:
    """Return whether ``path`` has a real video stream (not cover art)."""
    require_binary("ffprobe")
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-hide_banner", "-loglevel", "error", "-show_entries",
                "stream=codec_type:stream_disposition=attached_pic", "-of", "json", path,
            ],
            check=True, capture_output=True, text=True,
        )
        streams = json.loads(proc.stdout).get("streams") or []
    except (OSError, subprocess.SubprocessError, ValueError):
        raise RemoteSourceError("SOURCE_UNAVAILABLE") from None
    kinds = [stream.get("codec_type") for stream in streams]
    if not any(kind in ("audio", "video") for kind in kinds):
        raise RemoteSourceError("SOURCE_UNAVAILABLE")
    return any(
        stream.get("codec_type") == "video" and not (stream.get("disposition") or {}).get("attached_pic")
        for stream in streams
    )


def fetch(url: str, dest_dir: str) -> FetchedMedia:
    """Download the media behind a public ``http(s)`` URL into ``dest_dir``."""
    response = _open(url)
    content_type = _content_type(response)
    if content_type.split("/", 1)[0] in ("video", "audio"):
        path = os.path.join(dest_dir, _media_filename(content_type))
        _stream_to_file(response, path)
        title = _host_label(url)
    else:
        response.close()
        info = _resolve_with_ytdlp(url)
        headers = {
            str(key): str(value)
            for key, value in (info.get("http_headers") or {}).items()
            if str(key).lower() not in _DROPPED_HEADERS
        }
        media_response = _open(info["url"], headers)
        path = os.path.join(dest_dir, _media_filename(_content_type(media_response), info.get("ext")))
        _stream_to_file(media_response, path)
        title = _safe_title(info, url)
    return FetchedMedia(path=path, has_video=_has_video_stream(path), title=title)


@contextlib.contextmanager
def materialize(source: InputSource) -> Iterator[Materialized]:
    """Yield an extraction-ready source; remote media is deleted on exit.

    Non-remote sources pass through unchanged with no scratch directory.
    """
    if source.kind is not SourceKind.REMOTE:
        yield Materialized(source, None)
        return
    scratch_dir = tempfile.mkdtemp(prefix="lectural-fetch-")
    try:
        fetched = fetch(source.locator, scratch_dir)
        yield Materialized(
            InputSource(
                argument=source.origin or "url",
                kind=SourceKind.LOCAL_VIDEO if fetched.has_video else SourceKind.LOCAL_AUDIO,
                locator=fetched.path,
                title_hint=fetched.title,
                video_id=None,
                origin=source.origin,
            ),
            scratch_dir,
        )
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)
        if os.path.exists(scratch_dir):
            print(f"lectural: could not remove temporary media directory {scratch_dir}", file=sys.stderr)


__all__ = ["FetchedMedia", "Materialized", "RemoteSourceError", "fetch", "materialize"]
