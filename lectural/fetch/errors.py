"""Bounded URL error classification, independent of transport."""

from datetime import date
import re

from ..deps import DependencyError
from ..evidence import ContractError, failure

LOGIN_REQUIRED = "SOURCE_LOGIN_REQUIRED"
ACCESS_DENIED = "SOURCE_ACCESS_DENIED"
UNAVAILABLE = "SOURCE_UNAVAILABLE"
REDIRECT_REJECTED = "SOURCE_REDIRECT_REJECTED"
YTDLP_HINT = 'Install run extras: `uv pip install "lectural[run]"` (a yt-dlp Python package with request handlers).'
YTDLP_UPDATE_HINT = (
    "The installed yt-dlp is more than 90 days old, and an outdated yt-dlp can make public media "
    'look private; update it (for example `uv pip install -U "yt-dlp"`) and retry.'
)


def ytdlp_outdated(version: str | None = None, today: date | None = None) -> bool:
    if version is None:
        try:
            from yt_dlp.version import __version__ as version
        except ImportError:
            return False
    try:
        released = date(*(int(part) for part in version.split(".")[:3]))
        return ((today or date.today()) - released).days > 90
    except (ValueError, TypeError):
        return False


class RemoteSourceError(ContractError):
    def __init__(self, code: str):
        message = failure(code)["message"]
        if code in (LOGIN_REQUIRED, ACCESS_DENIED) and ytdlp_outdated():
            message += " " + YTDLP_UPDATE_HINT
        super().__init__(code, message)


def status_code(status: int) -> str:
    return LOGIN_REQUIRED if status in (401, 407) else ACCESS_DENIED if status == 403 else UNAVAILABLE


def classify_ytdlp_error(exc: BaseException) -> str:
    seen = set()
    current = exc
    while isinstance(current, BaseException) and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status", None) or getattr(current, "code", None)
        if isinstance(status, int) and 100 <= status < 600:
            return status_code(status)
        info = getattr(current, "exc_info", None)
        nested = info[1] if isinstance(info, tuple) and len(info) > 1 else None
        current = getattr(current, "cause", None) or nested or current.__cause__ or current.__context__
    # URL paths are not evidence of authentication requirements.
    text = re.sub(r"[A-Za-z][A-Za-z0-9+.-]*://\S*", " ", str(exc)).lower()
    if any(
        word in text
        for word in (
            "http error 401",
            "http error 407",
            "login",
            "log in",
            "logged in",
            "logged-in",
            "sign in",
            "cookies",
            "authentication",
            "registered users",
            "members-only",
        )
    ):
        return LOGIN_REQUIRED
    if any(word in text for word in ("http error 403", "forbidden", "private", "access denied")):
        return ACCESS_DENIED
    return UNAVAILABLE
