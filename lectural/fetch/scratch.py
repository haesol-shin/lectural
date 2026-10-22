"""Private scratch lifetime, advisory locks and stale-run recovery."""

from contextlib import contextmanager
import os
import shutil
import signal
import stat
import sys
import tempfile
import threading
import time

try:
    import fcntl
except ImportError:
    fcntl = None

PREFIX = "lectural-fetch-"
CLEANUP_WARNING = "lectural: could not remove temporary media directory"


def _lock(path: str) -> int | None:
    if fcntl is None:
        return None
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise
    return fd


def _remove(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)
    if os.path.lexists(path):
        print(CLEANUP_WARNING, file=sys.stderr)


def sweep_stale_scratch(root: str | None = None, *, now: float | None = None) -> list[str]:
    if fcntl is None:
        return []
    cutoff = (time.time() if now is None else now) - 3600
    removed = []
    try:
        with os.scandir(root or tempfile.gettempdir()) as entries:
            candidates = [entry.path for entry in entries if entry.name.startswith(PREFIX)]
    except OSError:
        return []
    for path in candidates:
        fd = None
        try:
            info = os.lstat(path)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mtime > cutoff:
                continue
            fd = _lock(path)
            locked = os.fstat(fd)
            if (locked.st_dev, locked.st_ino) != (info.st_dev, info.st_ino):
                continue
            _remove(path)
            if not os.path.lexists(path):
                removed.append(path)
        except OSError:
            continue
        finally:
            if fd is not None:
                os.close(fd)
    return removed


@contextmanager
def scratch_space():
    path = fd = None
    main = threading.current_thread() is threading.main_thread()
    previous = None
    received = False

    def terminate(signum, _frame):
        nonlocal received
        if not received:
            received = True
            raise SystemExit(128 + signum)

    if main:
        previous = signal.signal(signal.SIGTERM, terminate)
    try:
        sweep_stale_scratch()
        path = tempfile.mkdtemp(prefix=PREFIX)
        fd = _lock(path)
        yield path
    finally:
        try:
            if path is not None:
                _remove(path)
        finally:
            if fd is not None:
                os.close(fd)
            if main:
                signal.signal(signal.SIGTERM, previous)
