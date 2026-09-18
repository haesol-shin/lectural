"""Compute coverage.json — the completeness gate's input.

Four checks (all pure, unit-tested):
  1. gap_check      - max untranscribed SPEECH gap <= MAX_GAP_SEC (AC-9).
  2. scene_coverage - every timeline bin that contains speech also contains a
                      keyframe, and every slide-classified frame has OCR text.
  3. artifacts      - transcript.md and notes.md exist and are non-empty.
  4. notes_contract - marker-agnostic notes.md structure/citation contract.

`overall_pass` is the AND of the four. The hook (G003) reads this file.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass

from .config import FRAME_CARRY_MAX_SEC, MAX_GAP_SEC, SCENE_BINS_N, SCHEMA_VERSION
from .notes_contract import NOTES_CONTRACT_VERSION, coverage_contract_problems
from .vad import Span, max_non_silence_untranscribed_gap, transcript_coverage_spans


def _normalized_duration(value: object) -> float:
    """Return a positive finite duration, or zero for an invalid value."""
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return 0.0
    return duration if math.isfinite(duration) and duration > 0 else 0.0


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
    *,
    visual_required: bool = True,
    ocr_required: bool = True,
) -> dict:
    """Pure visual coverage with explicit applicability and gate state.

    ``frame_times`` are RAW sampled keyframe timestamps (pre-dedup), while
    slide counts describe retained deduplicated frames.  Audio-only sources
    set ``visual_required=False`` and receive an explicit not-applicable pass;
    skipping OCR changes only the slide-text predicate, never timeline
    coverage or its actual frame/text counts.
    """
    duration = _normalized_duration(duration)
    duration_valid = duration > 0
    bins = max(bins, 1)
    times = sorted(t for t in frame_times if duration_valid and 0 <= t <= duration)

    speech_bins: set[int] = set()
    covered: set[int] = set()
    if visual_required and duration_valid:
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
    timeline_pass = True if not visual_required else duration_valid and not uncovered
    slide_text_pass = (
        slide_frames_with_text >= slide_frames_total if ocr_required else True
    )
    return {
        "bins": bins,
        "carry_max_sec": carry_max_sec,
        "visual_required": visual_required,
        "ocr_required": ocr_required,
        "duration_valid": duration_valid,
        "speech_bins": sorted(speech_bins),
        "covered_speech_bins": sorted(covered),
        "uncovered_speech_bins": uncovered,
        "slide_frames_total": slide_frames_total,
        "slide_frames_with_text": slide_frames_with_text,
        "timeline_pass": timeline_pass,
        "slide_text_pass": slide_text_pass,
        "pass": timeline_pass and slide_text_pass,
    }


def artifact_check(
    transcript_path: str,
    notes_path: str,
    *,
    transcript_text: str | None = None,
    notes_text: str | None = None,
) -> dict:
    """Required transcript.md and notes.md artifacts must be non-empty.

    When rendered text is supplied, non-emptiness is judged from that content,
    decoupling the check from file write ordering. Otherwise it falls back to a
    filesystem stat (used by the Stop hook, which only ever sees written files).
    """

    def _nonempty(path: str | None, text: str | None) -> bool:
        if text is not None:
            return bool(text.strip())
        return bool(path and os.path.isfile(path) and os.path.getsize(path) > 0)

    t_ok = _nonempty(transcript_path, transcript_text)
    n_ok = _nonempty(notes_path, notes_text)
    return {
        "transcript_md": transcript_path,
        "notes_md": notes_path,
        "transcript_nonempty": bool(t_ok),
        "notes_nonempty": bool(n_ok),
        "pass": bool(t_ok and n_ok),
    }


@dataclass
class CoverageInputs:
    video_title: str
    duration_sec: float
    speech_spans: list[Span]
    segment_times: list[float]
    frame_times: list[float]
    transcript_path: str
    notes_path: str
    ocr_engine: str = "none"
    visual_required: bool = True
    ocr_required: bool = True
    slide_frames_total: int = 0
    slide_frames_with_text: int = 0
    transcript_text: str | None = None
    notes_text: str | None = None

    @property
    def raw_frame_times(self) -> list[float]:
        """Alias clarifying that frame_times MUST be RAW (pre-dedup) samples."""
        return self.frame_times


def coverage_inputs_from_extraction(
    *,
    video_title: str,
    duration_sec: float,
    speech_spans: list[Span],
    segment_times: list[float],
    raw_sample_times: list[float],
    slides: list[dict],
    transcript_path: str,
    notes_path: str,
    ocr_engine: str = "none",
    visual_required: bool = True,
    ocr_required: bool = True,
    transcript_text: str | None = None,
    notes_text: str | None = None,
) -> "CoverageInputs":
    """Enforce the scene-coverage contract at the call site (the orchestrator).

    `raw_sample_times` MUST be the RAW sampled keyframe timestamps from
    visual.extract_candidate_frames (pre-dedup), NOT dedupe_frames output —
    the carry cap relies on dense raw samples. `slides` are the DEDUPED slide
    frame dicts (each with `ocr_text`); their counts drive the slide-text gate.
    Keyword-only args make it hard to accidentally swap raw samples and slides.
    """
    slide_total = len(slides)
    slide_with_text = sum(1 for s in slides if (s.get("ocr_text") or "").strip())
    return CoverageInputs(
        video_title=video_title,
        duration_sec=duration_sec,
        speech_spans=speech_spans,
        segment_times=segment_times,
        frame_times=list(raw_sample_times),
        transcript_path=transcript_path,
        notes_path=notes_path,
        ocr_engine=ocr_engine,
        visual_required=visual_required,
        ocr_required=ocr_required,
        slide_frames_total=slide_total,
        slide_frames_with_text=slide_with_text,
        transcript_text=transcript_text,
        notes_text=notes_text,
    )
def build_coverage(inp: CoverageInputs) -> dict:
    """Assemble the full coverage.json structure. Pure (except file stat)."""
    duration = _normalized_duration(inp.duration_sec)
    gap = gap_check(inp.speech_spans, inp.segment_times, duration)
    scene = scene_coverage(
        inp.frame_times,
        inp.speech_spans,
        duration,
        slide_frames_total=inp.slide_frames_total,
        slide_frames_with_text=inp.slide_frames_with_text,
        visual_required=inp.visual_required,
        ocr_required=inp.ocr_required,
    )
    artifacts = artifact_check(
        inp.transcript_path,
        inp.notes_path,
        transcript_text=inp.transcript_text,
        notes_text=inp.notes_text,
    )
    if inp.notes_text is not None and inp.transcript_text is not None:
        contract_problems = coverage_contract_problems(inp.notes_text, inp.transcript_text)
        notes_contract = {
            "version": NOTES_CONTRACT_VERSION,
            "checked": True,
            "problems": contract_problems,
            "pass": not contract_problems,
        }
    else:
        notes_contract = {
            "version": NOTES_CONTRACT_VERSION,
            "checked": False,
            "problems": [],
            "pass": True,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "video_title": inp.video_title,
        "duration_sec": round(duration, 3),
        "ocr_engine": inp.ocr_engine,
        "gap_check": gap,
        "scene_coverage": scene,
        "artifacts": artifacts,
        "notes_contract": notes_contract,
        "overall_pass": bool(gap["pass"] and scene["pass"] and artifacts["pass"] and notes_contract["pass"]),
    }


def write_coverage(coverage: dict, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(coverage, fh, ensure_ascii=False, indent=2)
    return path
