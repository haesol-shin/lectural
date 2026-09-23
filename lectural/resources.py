"""Optional process-tree resource measurement for extraction runs."""

from __future__ import annotations

from contextlib import contextmanager
import os
import threading
import time
from typing import Iterator


class ResourceSampler:
    """Measure extraction wall time, stage durations, and peak process-tree RSS.

    psutil is imported only when a sampler starts. If it is unavailable, timing
    and artifact metrics remain available and ``peak_rss_mb`` is ``None``.
    """

    def __init__(self, sample_interval: float = 0.1):
        self.sample_interval = sample_interval
        self.stages = {"speech": 0.0, "frames": 0.0, "dedupe": 0.0, "ocr": 0.0}
        self._psutil = None
        self._peak_rss = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = 0.0

    def start(self) -> "ResourceSampler":
        self._started = time.perf_counter()
        try:
            import psutil

            self._psutil = psutil
            self._sample_rss()
            thread = threading.Thread(target=self._sample_loop, name="lectural-rss", daemon=True)
            thread.start()
            self._thread = thread
        except Exception:
            self._psutil = None
            self._peak_rss = None
            self._thread = None
        return self

    def _sample_rss(self) -> None:
        if self._psutil is None:
            return
        try:
            process = self._psutil.Process(os.getpid())
            total = process.memory_info().rss
            for child in process.children(recursive=True):
                try:
                    total += child.memory_info().rss
                except Exception:
                    continue
            current = total / (1024 * 1024)
            self._peak_rss = current if self._peak_rss is None else max(self._peak_rss, current)
        except Exception:
            return

    def _sample_loop(self) -> None:
        while not self._stop.wait(self.sample_interval):
            self._sample_rss()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] += time.perf_counter() - started

    def abort(self) -> None:
        """Stop background sampling when extraction exits before finalization."""
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join()

    def finish(self, *, artifact_bytes: int, frames_candidate: int, frames_retained: int) -> dict:
        self._sample_rss()
        self.abort()
        wall_sec = max(time.perf_counter() - self._started, 0.0)
        return {
            "wall_sec": round(wall_sec, 6),
            "stages": {name: round(value, 6) for name, value in self.stages.items()},
            "peak_rss_mb": round(self._peak_rss, 3) if self._peak_rss is not None else None,
            "artifact_bytes": int(artifact_bytes),
            "frames_candidate": int(frames_candidate),
            "frames_retained": int(frames_retained),
        }


__all__ = ["ResourceSampler"]
