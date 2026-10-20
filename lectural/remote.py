"""Fetch a public ``http(s)`` media URL into a temporary local file.

Only public URLs are supported: no cookie file, no credentials, and no user
configuration that could add them.  Every request follows redirects only to
``http``/``https`` targets:

* LecturAL's own requests (the first request and the media download) use an
  opener that has only HTTP/HTTPS handlers and rejects other redirect targets.
* yt-dlp resolves a page URL to one progressive ``http(s)`` media URL
  in-process, with its request director limited to a urllib handler that
  speaks only HTTP/HTTPS and checks every redirect target before following it.

Fetched media and audio derived from it live only in a private temporary
directory that ``materialize`` removes after success and failure.  Errors are
bounded codes; the URL path/query and tool output are never surfaced, and the
title of a fetched source is its host.
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
from urllib.parse import urljoin, urlsplit

from .deps import DependencyError, require_binary
from .evidence import ContractError, failure
from .source import InputSource, SourceKind

_ALLOWED_SCHEMES = ("http", "https")
_ALLOWED_PROTOCOLS = ("http", "https")
_REQUEST_TIMEOUT_SEC = 60
_CHUNK_BYTES = 1024 * 1024
_MAX_REDIRECTS = 10
_REDIRECT_CODES = (301, 302, 303, 307, 308)
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
_YTDLP_HINT = 'Install run extras: `uv pip install "lectural[run]"` (a yt-dlp Python package with request handlers).'


class RemoteSourceError(ContractError):
    """A bounded remote-source failure whose message never contains the URL."""

    def __init__(self, code: str):
        super().__init__(code, failure(code)["message"])


@dataclass(frozen=True)
class FetchedMedia:
    path: str
    has_video: bool


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


def _redirect_target_allowed(req, headers) -> bool:
    location = headers.get("location") or headers.get("uri")
    return not location or _scheme(urljoin(req.full_url, location)) in _ALLOWED_SCHEMES


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


class _SilentLogger:
    """yt-dlp messages contain the URL; they are never printed."""

    def debug(self, _message: str) -> None:
        pass

    info = warning = error = debug


def _http_only_ytdlp(rejected: list[bool]):
    """Return a YoutubeDL subclass whose only request handler is HTTP(S)-only."""
    try:
        import yt_dlp
        from yt_dlp.networking._urllib import UrllibRH
    except ImportError:
        raise DependencyError(f"Required Python module `yt_dlp` not installed. {_YTDLP_HINT}") from None
    if "build_request_director" not in vars(yt_dlp.YoutubeDL):
        # Fail closed: without this hook yt-dlp would use handlers we cannot restrict.
        raise DependencyError(f"The installed yt-dlp cannot restrict request handlers. {_YTDLP_HINT}")

    class _RedirectGuard(urllib.request.BaseHandler):
        # Runs before yt-dlp's redirect handler (order 500) for every redirect.
        handler_order = 100

        def _guard(self, req, fp, code, msg, headers):
            if not _redirect_target_allowed(req, headers):
                rejected.append(True)
                raise urllib.error.HTTPError(req.full_url, code, "redirect target rejected", headers, fp)
            return None

        http_error_301 = http_error_302 = http_error_303 = http_error_307 = http_error_308 = _guard

    class HttpOnlyUrllibRH(UrllibRH):
        _SUPPORTED_URL_SCHEMES = _ALLOWED_SCHEMES
        RH_NAME = "urllib-http-only"

        def _create_instance(self, *args, **kwargs):
            opener = super()._create_instance(*args, **kwargs)
            opener.add_handler(_RedirectGuard())
            return opener

    class HttpOnlyYoutubeDL(yt_dlp.YoutubeDL):
        def build_request_director(self, handlers, preferences=None):
            return super().build_request_director([HttpOnlyUrllibRH], preferences)

    return HttpOnlyYoutubeDL


def _ytdlp_extract_info(url: str) -> dict:
    """Run yt-dlp extraction for ``url`` without cookies, config, or output."""
    rejected: list[bool] = []
    youtube_dl = _http_only_ytdlp(rejected)
    params = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "skip_download": True,
        "format": _FORMAT_SELECTOR,
        "socket_timeout": _REQUEST_TIMEOUT_SEC,
        "logger": _SilentLogger(),
        "cookiefile": None,
        "cookiesfrombrowser": None,
    }
    try:
        with youtube_dl(params) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=False))
    except Exception as exc:  # noqa: BLE001 - extractor errors embed the URL; classify only.
        if rejected:
            raise RemoteSourceError("SOURCE_REDIRECT_REJECTED") from None
        text = str(exc).lower()
        code = "SOURCE_UNAUTHORIZED" if any(hint in text for hint in _UNAUTHORIZED_HINTS) else "SOURCE_UNAVAILABLE"
        raise RemoteSourceError(code) from None
    if rejected:
        raise RemoteSourceError("SOURCE_REDIRECT_REJECTED")
    return info if isinstance(info, dict) else {}


def _resolve_with_ytdlp(url: str) -> dict:
    """Return yt-dlp's single selected progressive format for ``url``."""
    info = _ytdlp_extract_info(url)
    if info.get("entries") is not None or info.get("requested_formats"):
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
    return FetchedMedia(path=path, has_video=_has_video_stream(path))


@contextlib.contextmanager
def materialize(source: InputSource) -> Iterator[Materialized]:
    """Yield an extraction-ready source; remote media is deleted on exit.

    Non-remote sources pass through unchanged with no scratch directory.
    """
    if source.kind is not SourceKind.REMOTE:
        yield Materialized(source, None)
        return
    origin = source.origin or "url"
    scratch_dir = tempfile.mkdtemp(prefix="lectural-fetch-")
    try:
        fetched = fetch(source.locator, scratch_dir)
        yield Materialized(
            InputSource(
                argument=origin,
                kind=SourceKind.LOCAL_VIDEO if fetched.has_video else SourceKind.LOCAL_AUDIO,
                locator=fetched.path,
                # Page titles can quote the URL path or query; the host cannot.
                title_hint=origin.split("://", 1)[-1],
                video_id=None,
                origin=origin,
            ),
            scratch_dir,
        )
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)
        if os.path.exists(scratch_dir):
            print(f"lectural: could not remove temporary media directory {scratch_dir}", file=sys.stderr)


__all__ = ["FetchedMedia", "Materialized", "RemoteSourceError", "fetch", "materialize"]
