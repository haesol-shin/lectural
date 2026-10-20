"""Fetch a public ``http(s)`` media URL into a temporary local file.

Only public URLs are supported: no cookie file, no credentials, and no user
configuration that could add them.  Every request follows redirects only to
``http``/``https`` targets:

* LecturAL's own requests (the first request and every media download) use an
  opener that has only HTTP/HTTPS handlers and rejects other redirect targets.
* yt-dlp resolves a page URL to ``http(s)`` media URLs in-process, with its
  request director limited to a urllib handler that speaks only HTTP/HTTPS and
  checks every redirect target before following it.  yt-dlp never downloads
  media itself.

A page resolves to one progressive file with video and audio or, failing that,
to a video-only and an audio-only ``http(s)`` stream that ffmpeg merges from
local files (no network protocols, no playlist demuxers).  HLS/DASH fragment
protocols are not fetched: yt-dlp's fragment downloaders can hand a manifest
to ffmpeg, whose network requests would bypass the redirect checks.

Fetched media and audio derived from it live only in a private temporary
directory that ``materialize`` removes after success, failure, Ctrl-C and
SIGTERM; directories left by a killed run are swept by a later URL run.
Errors are bounded codes; the URL path/query and tool output are never
surfaced, and the title of a fetched source is its host.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import date
import http.client
import json
import mimetypes
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Iterator
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

try:
    import fcntl
except ImportError:  # Windows: no advisory locks, so no stale-directory sweep.
    fcntl = None

from .deps import DependencyError, require_binary
from .evidence import ContractError, failure
from .source import InputSource, SourceKind

LOGIN_REQUIRED = "SOURCE_LOGIN_REQUIRED"
ACCESS_DENIED = "SOURCE_ACCESS_DENIED"
UNAVAILABLE = "SOURCE_UNAVAILABLE"
REDIRECT_REJECTED = "SOURCE_REDIRECT_REJECTED"

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
_HTTP_PROTOCOL = "[protocol~='^https?$']"
# Visual evidence needs video and audio: one progressive file, else a
# video-only + audio-only pair merged locally, else audio when the page has no
# video at all.  A speech-only mode (#44) would select ``ba`` first.
_FORMAT_SELECTOR = f"b{_HTTP_PROTOCOL}/bv{_HTTP_PROTOCOL}+ba{_HTTP_PROTOCOL}/ba{_HTTP_PROTOCOL}"
# Demuxers ffmpeg may use on fetched files; playlist/manifest demuxers (HLS,
# DASH, concat) are excluded because they open further URLs or files.
_FFMPEG_INPUT_GUARD = (
    "-protocol_whitelist", "file",
    "-format_whitelist", "mov,matroska,mp3,aac,ogg,wav,w64,flac,aiff,caf,mpegts,flv,avi,asf,mpeg",
)
_LOGIN_PATH = re.compile(r"/(?:login|log-in|signin|sign-in|sign_in)(?:[/.?]|$)", re.IGNORECASE)
_LOGIN_HINTS = (
    "http error 401", "http error 407", "login", "log in", "logged in", "logged-in", "sign in",
    "cookies", "authentication", "registered users", "members-only",
)
_URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S*")
_DENIED_HINTS = ("http error 403", "forbidden", "private", "access denied")
_YTDLP_MAX_AGE_DAYS = 90
_YTDLP_UPDATE_HINT = (
    "The installed yt-dlp is more than 90 days old, and an outdated yt-dlp can make public media "
    'look private; update it (for example `uv pip install -U "yt-dlp"`) and retry.'
)
_DROPPED_HEADERS = {"cookie", "authorization", "proxy-authorization"}
_YTDLP_HINT = 'Install run extras: `uv pip install "lectural[run]"` (a yt-dlp Python package with request handlers).'
_SCRATCH_PREFIX = "lectural-fetch-"
_STALE_SCRATCH_AGE_SEC = 60 * 60


def _ytdlp_outdated(version: str | None = None, today: date | None = None) -> bool:
    """Return whether the installed yt-dlp release is older than 90 days."""
    if version is None:
        try:
            from yt_dlp.version import __version__ as version
        except ImportError:
            return False
    try:
        year, month, day = (int(part) for part in str(version).split(".")[:3])
        released = date(year, month, day)
    except ValueError:
        return False
    return ((today or date.today()) - released).days > _YTDLP_MAX_AGE_DAYS


class RemoteSourceError(ContractError):
    """A bounded remote-source failure whose message never contains the URL."""

    def __init__(self, code: str):
        message = failure(code)["message"]
        if code in (LOGIN_REQUIRED, ACCESS_DENIED) and _ytdlp_outdated():
            message = f"{message} {_YTDLP_UPDATE_HINT}"
        super().__init__(code, message)


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
            raise RemoteSourceError(REDIRECT_REJECTED)
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


def _status_code(status: int) -> str:
    if status in (401, 407):
        return LOGIN_REQUIRED
    if status == 403:
        return ACCESS_DENIED
    return UNAVAILABLE


def _bounded(exc: BaseException) -> RemoteSourceError:
    if isinstance(exc, RemoteSourceError):
        return exc
    if isinstance(exc, urllib.error.HTTPError):
        exc.close()
        if 300 <= exc.code < 400 and "loop" not in str(exc.msg).lower():
            # urllib refuses non-http(s)/ftp redirect targets before our handler runs.
            return RemoteSourceError(REDIRECT_REJECTED)
        return RemoteSourceError(_status_code(exc.code))
    return RemoteSourceError(UNAVAILABLE)


def _open(url: str, headers: dict[str, str] | None = None):
    if _scheme(url) not in _ALLOWED_SCHEMES:
        raise RemoteSourceError("SOURCE_INVALID")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    try:
        return _opener().open(request, timeout=_REQUEST_TIMEOUT_SEC)
    except (OSError, http.client.HTTPException, ValueError, RemoteSourceError) as exc:
        raise _bounded(exc) from None


def _redirected_to_login(requested: str, response) -> bool:
    final = response.geturl()
    if not isinstance(final, str) or final == requested:
        return False
    try:
        return bool(_LOGIN_PATH.search(urlsplit(final).path))
    except ValueError:
        return False


def _content_type(response) -> str:
    return (response.headers.get_content_type() or "").lower()


def _is_media(content_type: str) -> bool:
    return content_type.split("/", 1)[0] in ("video", "audio")


def _media_filename(content_type: str, ext: str | None = None, stem: str = "media") -> str:
    suffix = f".{ext}" if ext and re.fullmatch(r"[A-Za-z0-9]{1,8}", ext) else None
    suffix = suffix or mimetypes.guess_extension(content_type) or ".media"
    return f"{stem}{suffix}"


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
        raise RemoteSourceError(UNAVAILABLE)


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


def _http_status(exc: BaseException) -> int | None:
    """Find an HTTP status in a yt-dlp error chain (DownloadError -> ExtractorError -> HTTPError)."""
    seen: set[int] = set()
    current: object = exc
    while isinstance(current, BaseException) and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status", None)
        if isinstance(status, int) and 100 <= status < 600:
            return status
        exc_info = getattr(current, "exc_info", None)
        nested = getattr(current, "cause", None) or (exc_info[1] if isinstance(exc_info, tuple) and len(exc_info) > 1 else None)
        current = nested or current.__cause__ or current.__context__
    return None


def _classify_ytdlp_error(exc: BaseException) -> str:
    status = _http_status(exc)
    if status in (401, 403, 407):
        return _status_code(status)
    # yt-dlp messages quote the URL, whose path may contain words like "private".
    text = _URL_IN_TEXT.sub(" ", str(exc)).lower()
    if any(hint in text for hint in _LOGIN_HINTS):
        return LOGIN_REQUIRED
    if any(hint in text for hint in _DENIED_HINTS):
        return ACCESS_DENIED
    return UNAVAILABLE


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
            raise RemoteSourceError(REDIRECT_REJECTED) from None
        raise RemoteSourceError(_classify_ytdlp_error(exc)) from None
    if rejected:
        raise RemoteSourceError(REDIRECT_REJECTED)
    return info if isinstance(info, dict) else {}


def _site_extractor_claims(url: str) -> bool:
    """Return whether a yt-dlp extractor other than the generic one matches ``url``."""
    try:
        from yt_dlp.extractor import gen_extractor_classes
    except ImportError:
        return False
    return any(ie.ie_key() != "Generic" and ie.suitable(url) for ie in gen_extractor_classes())


def _may_have_video(fmt: dict) -> bool:
    return fmt.get("vcodec") != "none"


def _selected_formats(info: dict) -> list[dict]:
    """Return the ``http(s)`` formats yt-dlp selected (one, or a video+audio pair)."""
    if info.get("entries") is not None:
        raise RemoteSourceError(UNAVAILABLE)
    selected = info.get("requested_formats") or [info]
    if not isinstance(selected, list) or not 1 <= len(selected) <= 2:
        raise RemoteSourceError(UNAVAILABLE)
    for fmt in selected:
        media_url = fmt.get("url") if isinstance(fmt, dict) else None
        if (
            not isinstance(media_url, str)
            or _scheme(media_url) not in _ALLOWED_SCHEMES
            or str(fmt.get("protocol") or "").lower() not in _ALLOWED_PROTOCOLS
        ):
            raise RemoteSourceError(UNAVAILABLE)
    if not any(_may_have_video(fmt) for fmt in selected) and any(
        isinstance(fmt, dict) and _may_have_video(fmt) for fmt in info.get("formats") or []
    ):
        # The page has video, but only in a form that is not fetched (for example
        # HLS/DASH fragments); audio alone would silently drop visual evidence.
        raise RemoteSourceError(UNAVAILABLE)
    return selected


def _probe(path: str) -> bool:
    """Return whether ``path`` has a real video stream (not cover art).

    Only local files in an allowed container are opened; a playlist or
    manifest is rejected before any other ffmpeg step sees it.
    """
    require_binary("ffprobe")
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-hide_banner", "-loglevel", "error", *_FFMPEG_INPUT_GUARD, "-show_entries",
                "stream=codec_type:stream_disposition=attached_pic", "-of", "json", path,
            ],
            check=True, capture_output=True, text=True,
        )
        streams = json.loads(proc.stdout).get("streams") or []
    except (OSError, subprocess.SubprocessError, ValueError):
        raise RemoteSourceError(UNAVAILABLE) from None
    kinds = [stream.get("codec_type") for stream in streams]
    if not any(kind in ("audio", "video") for kind in kinds):
        raise RemoteSourceError(UNAVAILABLE)
    return any(
        stream.get("codec_type") == "video" and not (stream.get("disposition") or {}).get("attached_pic")
        for stream in streams
    )


def _merge(video_path: str, audio_path: str, dest_dir: str) -> str:
    """Merge a local video-only and audio-only file without re-encoding."""
    require_binary("ffmpeg")
    merged = os.path.join(dest_dir, "media.mkv")
    try:
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                *_FFMPEG_INPUT_GUARD, "-i", video_path, *_FFMPEG_INPUT_GUARD, "-i", audio_path,
                "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-f", "matroska", "-y", merged,
            ],
            check=True, capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        raise RemoteSourceError(UNAVAILABLE) from None
    for path in (video_path, audio_path):
        os.remove(path)
    return merged


def _download_formats(formats: list[dict], dest_dir: str) -> FetchedMedia:
    """Download yt-dlp's selected formats with LecturAL's checked opener."""
    paths = []
    for index, fmt in enumerate(formats):
        headers = {
            str(key): str(value)
            for key, value in (fmt.get("http_headers") or {}).items()
            if str(key).lower() not in _DROPPED_HEADERS
        }
        response = _open(fmt["url"], headers)
        stem = "media" if len(formats) == 1 else f"stream{index}"
        path = os.path.join(dest_dir, _media_filename(_content_type(response), fmt.get("ext"), stem))
        _stream_to_file(response, path)
        paths.append(path)
    if len(paths) == 1:
        return FetchedMedia(path=paths[0], has_video=_probe(paths[0]))
    video_path, audio_path = paths
    if not _probe(video_path):
        raise RemoteSourceError(UNAVAILABLE)
    _probe(audio_path)  # an allowed local container with a media stream
    return FetchedMedia(path=_merge(video_path, audio_path, dest_dir), has_video=True)


def fetch(url: str, dest_dir: str) -> FetchedMedia:
    """Download the media behind a public ``http(s)`` URL into ``dest_dir``."""
    first_failure: RemoteSourceError | None = None
    login_wall = False
    try:
        response = _open(url)
    except RemoteSourceError as exc:
        if exc.code != ACCESS_DENIED:
            raise
        # A 403 to a plain request may be a block on non-browser clients;
        # page resolution decides between that and private media.
        first_failure, response = exc, None
    if response is not None:
        content_type = _content_type(response)
        if _is_media(content_type):
            path = os.path.join(dest_dir, _media_filename(content_type))
            _stream_to_file(response, path)
            return FetchedMedia(path=path, has_video=_probe(path))
        response.close()
        if _redirected_to_login(url, response):
            login_wall = True
    if login_wall and not _site_extractor_claims(url):
        # Generic page extraction would follow the redirect and return whatever
        # the login page embeds; only a site extractor resolves the original media.
        raise RemoteSourceError(LOGIN_REQUIRED)
    try:
        info = _ytdlp_extract_info(url)
    except RemoteSourceError as exc:
        if login_wall and exc.code != REDIRECT_REJECTED:
            raise RemoteSourceError(LOGIN_REQUIRED) from None
        if first_failure is None or exc.code in (LOGIN_REQUIRED, ACCESS_DENIED, REDIRECT_REJECTED):
            raise
        raise first_failure from None
    return _download_formats(_selected_formats(info), dest_dir)


def _owned_by_user(info: os.stat_result) -> bool:
    getuid = getattr(os, "getuid", None)
    return getuid is not None and info.st_uid == getuid()


def _lock_scratch(path: str) -> int | None:
    """Hold an exclusive lock on ``path`` while this run uses it."""
    if fcntl is None:
        return None
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Unlockable file system: the sweep cannot lock it either and skips it.
        os.close(fd)
        return None
    return fd


def sweep_stale_scratch(root: str | None = None, *, now: float | None = None) -> list[str]:
    """Remove ``lectural-fetch-*`` directories left by runs that were killed.

    A directory is removed only when it is a real directory owned by this
    user, older than one hour, and not locked by a live run (the kernel drops
    a killed run's lock).  POSIX only.
    """
    if fcntl is None:
        return []
    root = root or tempfile.gettempdir()
    cutoff = (time.time() if now is None else now) - _STALE_SCRATCH_AGE_SEC
    removed = []
    try:
        entries = list(os.scandir(root))
    except OSError:
        return []
    for entry in entries:
        if not entry.name.startswith(_SCRATCH_PREFIX):
            continue
        try:
            info = os.lstat(entry.path)
            if not stat.S_ISDIR(info.st_mode) or not _owned_by_user(info) or info.st_mtime > cutoff:
                continue
            fd = os.open(entry.path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        except OSError:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            continue  # a live run holds it
        try:
            shutil.rmtree(entry.path, ignore_errors=True)
        finally:
            os.close(fd)
        if not os.path.lexists(entry.path):
            removed.append(entry.path)
    return removed


@contextlib.contextmanager
def _terminate_as_exit() -> Iterator[None]:
    """Turn the first SIGTERM into ``SystemExit(143)`` so ``finally`` blocks run."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    received: list[int] = []

    def _handler(signum, _frame):
        if not received:
            received.append(signum)
            raise SystemExit(128 + signum)

    previous = signal.signal(signal.SIGTERM, _handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


@contextlib.contextmanager
def materialize(source: InputSource) -> Iterator[Materialized]:
    """Yield an extraction-ready source; remote media is deleted on exit.

    Non-remote sources pass through unchanged with no scratch directory.
    """
    if source.kind is not SourceKind.REMOTE:
        yield Materialized(source, None)
        return
    origin = source.origin or "url"
    sweep_stale_scratch()
    with _terminate_as_exit():
        scratch_dir = None
        lock_fd = None
        try:
            scratch_dir = tempfile.mkdtemp(prefix=_SCRATCH_PREFIX)
            lock_fd = _lock_scratch(scratch_dir)
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
            if scratch_dir is not None:
                shutil.rmtree(scratch_dir, ignore_errors=True)
            if lock_fd is not None:
                os.close(lock_fd)
            if scratch_dir is not None and os.path.exists(scratch_dir):
                print(f"lectural: could not remove temporary media directory {scratch_dir}", file=sys.stderr)


__all__ = [
    "FetchedMedia", "Materialized", "RemoteSourceError", "fetch", "materialize", "sweep_stale_scratch",
]
