"""Voice-activity / silence handling and the speech-coverage gap metric.

The completeness gate must NOT use a wall-clock coverage ratio (that conflates
legitimate silence with missed speech). Instead we build a *speech mask* and
measure the largest contiguous span of speech that the transcript fails to
cover. All the math here is pure and unit-tested; only the silence detection
itself shells out to ffmpeg (or webrtcvad), lazily.
"""

from __future__ import annotations

import re

Span = tuple[float, float]


# --- Interval algebra (pure) -----------------------------------------------

def merge_spans(spans: list[Span]) -> list[Span]:
    """Sort and merge overlapping/adjacent intervals. Pure."""
    norm = [(min(a, b), max(a, b)) for a, b in spans if b > a or b == a]
    norm = [s for s in norm if s[1] > s[0]]
    norm.sort()
    merged: list[Span] = []
    for s, e in norm:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def invert_spans(spans: list[Span], start: float, end: float) -> list[Span]:
    """Complement of `spans` within [start, end]. Pure."""
    if end <= start:
        return []
    merged = merge_spans([s for s in spans if s[1] > start and s[0] < end])
    out: list[Span] = []
    cursor = start
    for s, e in merged:
        s = max(s, start)
        e = min(e, end)
        if s > cursor:
            out.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < end:
        out.append((cursor, end))
    return out


def subtract_spans(base: list[Span], cut: list[Span]) -> list[Span]:
    """base minus cut: portions of base not covered by cut. Pure."""
    cut_m = merge_spans(cut)
    out: list[Span] = []
    for b0, b1 in merge_spans(base):
        cursor = b0
        for c0, c1 in cut_m:
            if c1 <= cursor or c0 >= b1:
                continue
            if c0 > cursor:
                out.append((cursor, min(c0, b1)))
            cursor = max(cursor, c1)
            if cursor >= b1:
                break
        if cursor < b1:
            out.append((cursor, b1))
    return [s for s in out if s[1] > s[0]]


# --- Transcript coverage + gap metric (pure) -------------------------------

def transcript_coverage_spans(segment_times: list[float], duration: float) -> list[Span]:
    """Turn transcript start times into covered intervals. Pure.

    Each cue covers from its start up to the next cue's start, but never more
    than CUE_MAX_COVER_SEC. A long cue-less stretch therefore stays uncovered
    so a real untranscribed speech gap is detected. Time before the first cue
    is uncovered.
    """
    from .config import CUE_MAX_COVER_SEC

    times = sorted(t for t in segment_times if 0 <= t <= duration)
    if not times:
        return []
    spans: list[Span] = []
    for i, t in enumerate(times):
        next_bound = times[i + 1] if i + 1 < len(times) else duration
        end = min(next_bound, t + CUE_MAX_COVER_SEC)
        if end > t:
            spans.append((t, end))
    return merge_spans(spans)


def max_non_silence_untranscribed_gap(
    speech_spans: list[Span],
    coverage_spans: list[Span],
) -> float:
    """Largest contiguous SPEECH span with no transcript coverage. Pure.

    This is the value the completeness gate compares against MAX_GAP_SEC.
    Silence never contributes because it is not in `speech_spans`.
    """
    uncovered = subtract_spans(speech_spans, coverage_spans)
    if not uncovered:
        return 0.0
    return max(e - s for s, e in uncovered)


# --- Silence detection backends (lazy / subprocess) ------------------------

_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")


def parse_silencedetect(stderr_text: str, duration: float) -> list[Span]:
    """Parse ffmpeg `silencedetect` stderr into SPEECH spans. Pure.

    ffmpeg reports silence intervals; we invert them to get speech.
    """
    silences: list[Span] = []
    pending_start: float | None = None
    for line in stderr_text.splitlines():
        ms = _SILENCE_START_RE.search(line)
        me = _SILENCE_END_RE.search(line)
        if ms:
            pending_start = float(ms.group(1))
        if me:
            end = float(me.group(1))
            start = pending_start if pending_start is not None else 0.0
            silences.append((start, end))
            pending_start = None
    if pending_start is not None:
        silences.append((pending_start, duration))
    return invert_spans(silences, 0.0, duration)


def detect_speech_spans(audio_path: str, duration: float, noise_db: int = -30, min_silence: float = 1.0) -> list[Span]:
    """Run ffmpeg silencedetect and return speech spans. Lazy/subprocess."""
    import subprocess

    from .deps import require_binary

    require_binary("ffmpeg")
    proc = subprocess.run(
        [
            "ffmpeg", "-i", audio_path,
            "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    return parse_silencedetect(proc.stderr, duration)
