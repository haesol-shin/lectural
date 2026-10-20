"""Prepare public URLs as disposable ordinary local sources."""

from contextlib import contextmanager
from dataclasses import dataclass
import os

from ..source import InputSource, SourceKind, classify_source
from ..urlpolicy import remote_url_origin
from . import assets, http, ytdlp
from .errors import RemoteSourceError, ACCESS_DENIED, LOGIN_REQUIRED, REDIRECT_REJECTED
from .scratch import scratch_space


@dataclass(frozen=True)
class PreparedSource:
    source: InputSource
    work_dir: str | None


def fetch_url(url: str, dest_dir: str) -> assets.FetchedMedia:
    denied = None
    try:
        direct = http.try_direct(url, dest_dir)
    except RemoteSourceError as exc:
        if exc.code != ACCESS_DENIED:
            raise
        denied = exc
        direct = http.PageFallback(False)
    if isinstance(direct, assets.FetchedMedia):
        return direct
    try:
        formats = ytdlp.resolve_formats(url, allow_generic=not direct.login_wall)
    except RemoteSourceError as exc:
        if direct.login_wall and exc.code != REDIRECT_REJECTED:
            raise RemoteSourceError(LOGIN_REQUIRED) from None
        if denied and exc.code not in (ACCESS_DENIED, LOGIN_REQUIRED, REDIRECT_REJECTED):
            raise denied from None
        raise
    return assets.download_formats(formats, dest_dir)


@contextmanager
def prepare_source(argument: str):
    origin = None if os.path.isfile(os.path.expanduser(argument)) else remote_url_origin(argument)
    if origin is None:
        yield PreparedSource(classify_source(argument), None)
        return
    with scratch_space() as work_dir:
        fetched = fetch_url(argument, work_dir)
        source = InputSource(
            argument=origin, kind=SourceKind.LOCAL_VIDEO if fetched.has_video else SourceKind.LOCAL_AUDIO,
            locator=fetched.path, title_hint=origin.split("://", 1)[1], video_id=None, origin=origin,
        )
        yield PreparedSource(source, work_dir)
