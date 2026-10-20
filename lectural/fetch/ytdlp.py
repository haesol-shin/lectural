"""Resolve pages to HTTP formats without downloading media."""

import urllib.error
import urllib.request
from urllib.parse import urljoin

from ..urlpolicy import HTTP_SCHEMES, is_http_url
from .errors import DependencyError, RemoteSourceError, REDIRECT_REJECTED, UNAVAILABLE
from .errors import YTDLP_HINT, classify_ytdlp_error
from .http import TIMEOUT

_PROTOCOL_FILTER = "[protocol~='^(" + "|".join(HTTP_SCHEMES) + ")$']"
FORMAT_SELECTOR = "/".join((
    f"b{_PROTOCOL_FILTER}", f"bv{_PROTOCOL_FILTER}+ba{_PROTOCOL_FILTER}", f"ba{_PROTOCOL_FILTER}",
))


class SilentLogger:
    def debug(self, _message):
        pass

    info = warning = error = debug


def http_only_ytdlp(rejected: list):
    try:
        import yt_dlp
        from yt_dlp.networking._urllib import UrllibRH
    except ImportError:
        raise DependencyError(f"Required Python module `yt_dlp` not installed. {YTDLP_HINT}") from None
    if "build_request_director" not in vars(yt_dlp.YoutubeDL):
        raise DependencyError(f"The installed yt-dlp cannot restrict request handlers. {YTDLP_HINT}")

    class RedirectGuard(urllib.request.BaseHandler):
        # Run before the resolver's own redirect handler.
        handler_order = 100

        def guard(self, req, fp, code, msg, headers):
            location = headers.get("location") or headers.get("uri")
            if location and not is_http_url(urljoin(req.full_url, location)):
                rejected.append(True)
                raise urllib.error.HTTPError(req.full_url, code, "redirect target rejected", headers, fp)

        http_error_301 = http_error_302 = http_error_303 = http_error_307 = http_error_308 = guard

    class HttpOnlyUrllibRH(UrllibRH):
        _SUPPORTED_URL_SCHEMES = HTTP_SCHEMES
        RH_NAME = "urllib-http-only"

        def _create_instance(self, *args, **kwargs):
            opener = super()._create_instance(*args, **kwargs)
            opener.add_handler(RedirectGuard())
            return opener

    class HttpOnlyYoutubeDL(yt_dlp.YoutubeDL):
        def build_request_director(self, handlers, preferences=None):
            return super().build_request_director([HttpOnlyUrllibRH], preferences)

    return HttpOnlyYoutubeDL


def resolve_formats(url: str, *, allow_generic: bool = True) -> list[dict]:
    rejected = []
    youtube_dl = http_only_ytdlp(rejected)
    params = {
        "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
        "skip_download": True, "format": FORMAT_SELECTOR, "socket_timeout": TIMEOUT,
        "logger": SilentLogger(), "cookiefile": None, "cookiesfrombrowser": None,
    }
    if not allow_generic:
        params["allowed_extractors"] = ["default", "-generic"]
    try:
        with youtube_dl(params) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=False))
    except Exception as exc:
        raise RemoteSourceError(REDIRECT_REJECTED if rejected else classify_ytdlp_error(exc)) from None
    if rejected:
        raise RemoteSourceError(REDIRECT_REJECTED)
    if not isinstance(info, dict) or info.get("_type") == "playlist" or info.get("entries") is not None:
        raise RemoteSourceError(UNAVAILABLE)
    selected = info.get("requested_formats") or [info]
    if not isinstance(selected, list) or not 1 <= len(selected) <= 2:
        raise RemoteSourceError(UNAVAILABLE)
    for fmt in selected:
        if (not isinstance(fmt, dict) or not is_http_url(str(fmt.get("url") or ""))
                or fmt.get("protocol") not in HTTP_SCHEMES):
            raise RemoteSourceError(UNAVAILABLE)
    if not any(fmt.get("vcodec") != "none" for fmt in selected) and any(
        isinstance(fmt, dict) and fmt.get("vcodec") != "none" for fmt in info.get("formats") or []
    ):
        raise RemoteSourceError(UNAVAILABLE)
    if len(selected) == 2 and (selected[0].get("vcodec") == "none"
                               or selected[1].get("vcodec") != "none"):
        raise RemoteSourceError(UNAVAILABLE)
    return selected
