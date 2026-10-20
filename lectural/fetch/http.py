"""Checked HTTP transport and direct-media detection."""

from dataclasses import dataclass
import http.client
import mimetypes
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

from ..urlpolicy import is_http_url
from .errors import RemoteSourceError, REDIRECT_REJECTED, UNAVAILABLE, status_code

TIMEOUT = 60
USER_AGENT = "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


@dataclass(frozen=True)
class PageFallback:
    login_wall: bool


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 10

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_http_url(urljoin(req.full_url, newurl)):
            raise RemoteSourceError(REDIRECT_REJECTED)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url: str, headers: dict | None = None):
    if not is_http_url(url):
        raise RemoteSourceError("SOURCE_INVALID")
    # Building explicitly avoids urllib's file, FTP, data and cookie handlers.
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler({}), urllib.request.UnknownHandler(), urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(), urllib.request.HTTPDefaultErrorHandler(), _Redirects(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        return opener.open(request, timeout=TIMEOUT)
    except RemoteSourceError:
        raise
    except urllib.error.HTTPError as exc:
        rejected = 300 <= exc.code < 400 and "loop" not in str(exc.msg)
        code = REDIRECT_REJECTED if rejected else status_code(exc.code)
        exc.close()
        raise RemoteSourceError(code) from None
    except (OSError, http.client.HTTPException, ValueError):
        raise RemoteSourceError(UNAVAILABLE) from None


def media_filename(content_type: str, ext: str | None = None, stem: str = "media") -> str:
    suffix = f".{ext}" if ext and re.fullmatch(r"[A-Za-z0-9]{1,8}", ext) else None
    return stem + (suffix or mimetypes.guess_extension(content_type) or ".media")


def stream_to_file(response, path: str) -> None:
    declared = response.headers.get("Content-Length")
    try:
        with response, open(path, "wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        size = os.path.getsize(path)
        if not size or (declared and declared.strip().isdigit() and size != int(declared)):
            raise RemoteSourceError(UNAVAILABLE)
    except (OSError, http.client.HTTPException, ValueError):
        raise RemoteSourceError(UNAVAILABLE) from None


def try_direct(url: str, dest_dir: str):
    from .assets import FetchedMedia, probe

    response = open_url(url)
    content_type = response.headers.get_content_type().lower()
    final = response.geturl()
    login_wall = final != url and bool(re.search(
        r"/(?:login|log-in|signin|sign-in|sign_in)(?:[/.?]|$)", urlsplit(final).path, re.I,
    ))
    if not login_wall and content_type.split("/", 1)[0] in ("audio", "video"):
        path = os.path.join(dest_dir, media_filename(content_type))
        stream_to_file(response, path)
        return FetchedMedia(path, probe(path))
    response.close()
    return PageFallback(login_wall)
