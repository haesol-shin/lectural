"""Compute coverage.json — the completeness gate's input.

Three checks (all pure, unit-tested):
  1. gap_check     - max untranscribed SPEECH gap <= MAX_GAP_SEC (AC-9).
  2. scene_coverage- every timeline bin that contains speech also contains a
                     keyframe, and every slide-classified frame has OCR text.
  3. artifacts     - transcript.md and summary.md exist and are non-empty.

`overall_pass` is the AND of the three. The hook (G003) reads this file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .config import FRAME_CARRY_MAX_SEC, MAX_GAP_SEC, SCENE_BINS_N, SCHEMA_VERSION
from .vad import Span, max_non_silence_untranscribed_gap, transcript_coverage_spans


def gap_check(
    speech_spans: list[Span],
    segment_times: list[float],
    duration: float,
    threshold: float = MAX_GAP_SEC,
) -> dict:
    """Pure: largest untranscribed speech gap vs threshold."""
    coverage = transcript_coverage_spans(segment_times, duration)
    gap = max_non_silence_untranscribed_gap(speech_spans, coverage)
    return {
        "max_untranscribed_speech_gap_sec": round(gap, 3),
        "threshold_sec": threshold,
        "pass": gap <= threshold,
    }


def _bin_of(t: float, duration: float, bins: int) -> int:
    if duration <= 0:
        return 0
    idx = int((t / duration) * bins)
    return min(max(idx, 0), bins - 1)


def scene_coverage(
    frame_times: list[float],
    speech_spans: list[Span],
    duration: float,
    bins: int = SCENE_BINS_N,
    slide_frames_total: int = 0,
    slide_frames_with_text: int = 0,
    carry_max_sec: float = FRAME_CARRY_MAX_SEC,
) -> dict:
    """Pure: every speech bin must be covered by a keyframe (capped carry).

    A bin "contains speech" when any speech span overlaps its time range. A
    keyframe covers its own bin AND carries forward to later bins, but only for
    up to `carry_max_sec`. So a static slide passes when the visual pass feeds
    dense RAW samples (~SAMPLE_FPS), while a stretch with NO keyframe for longer
    than the cap (an extractor stall, mid-video OR tail, or speech before the
    first keyframe) stays uncovered and FAILs. `pass` also requires every
    slide-classified frame to carry OCR text.

    `frame_times` MUST be the RAW sampled keyframe times (pre-dedup); the cap is
    what makes a missing/stalled visual pass detectable.
    """
    bins = max(bins, 1)
    times = sorted(t for t in frame_times if 0 <= t <= duration)

    speech_bins: set[int] = set()
    covered: set[int] = set()
    if duration > 0:
        bin_width = duration / bins
        import bisect

        for b in range(bins):
            b0, b1 = b * bin_width, (b + 1) * bin_width
            if not any(s < b1 and e > b0 for s, e in speech_spans):
                continue
            speech_bins.add(b)
            # Most recent keyframe at or before this bin's end.
            idx = bisect.bisect_right(times, b1) - 1
            if idx >= 0 and (b0 - times[idx]) <= carry_max_sec:
                covered.add(b)

    uncovered = sorted(b for b in speech_bins if b not in covered)
    slides_ok = slide_frames_with_text >= slide_frames_total  # every slide has text
    return {
        "bins": bins,
        "carry_max_sec": carry_max_sec,
        "speech_bins": sorted(speech_bins),
        "covered_speech_bins": sorted(covered),
        "uncovered_speech_bins": uncovered,
        "slide_frames_total": slide_frames_total,
        "slide_frames_with_text": slide_frames_with_text,
        "pass": not uncovered and slides_ok,
    }


def artifact_check(transcript_path: str, summary_path: str) -> dict:
    """Both artifacts must exist and be non-empty."""
    t_ok = os.path.isfile(transcript_path) and os.path.getsize(transcript_path) > 0
    s_ok = os.path.isfile(summary_path) and os.path.getsize(summary_path) > 0
    return {
        "transcript_md": transcript_path,
        "summary_md": summary_path,
        "transcript_nonempty": bool(t_ok),
        "summary_nonempty": bool(s_ok),
        "pass": bool(t_ok and s_ok),
    }


@dataclass
class CoverageInputs:
    video_title: str
    duration_sec: float
    speech_spans: list[Span]
    segment_times: list[float]
    frame_times: list[float]
    transcript_path: str
    summary_path: str
    ocr_engine: str = "none"
    slide_frames_total: int = 0
    slide_frames_with_text: int = 0


def build_coverage(inp: CoverageInputs) -> dict:
    """Assemble the full coverage.json structure. Pure (except file stat)."""
    gap = gap_check(inp.speech_spans, inp.segment_times, inp.duration_sec)
    scene = scene_coverage(
        inp.frame_times,
        inp.speech_spans,
        inp.duration_sec,
        slide_frames_total=inp.slide_frames_total,
        slide_frames_with_text=inp.slide_frames_with_text,
    )
    artifacts = artifact_check(inp.transcript_path, inp.summary_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "video_title": inp.video_title,
        "duration_sec": round(inp.duration_sec, 3),
        "ocr_engine": inp.ocr_engine,
        "gap_check": gap,
        "scene_coverage": scene,
        "artifacts": artifacts,
        "overall_pass": bool(gap["pass"] and scene["pass"] and artifacts["pass"]),
    }


def write_coverage(coverage: dict, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(coverage, fh, ensure_ascii=False, indent=2)
    return path
