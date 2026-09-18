#!/usr/bin/env python3
"""Offline benchmark harness for LecturAL speech/OCR extraction quality and resource cost.

This module implements Slice 4 of the Issue #21 benchmark plan:
  1. An argparse CLI (--fixtures-dir, --out, --platform-label, --cold/--warm, --reps, --skip-ocr)
     with ZERO heavy imports at the module level (jiwer, whisper_normalizer, augraphy,
     audiomentations, paddleocr, faster_whisper, and lectural_bench are all imported lazily
     inside functions), ensuring `python scripts/benchmark.py --help` works with zero heavy deps.
  2. A StageSampler-reusing resource-measurement function (measure_fixture_run) wrapping local-fixture
     runs to measure per-stage CPU/RSS, wall-clock time, storage delta, and RTF.
  3. A caption/fallback injection function (acquire_speech_with_caption_injection) using
     unittest.mock.patch to exercise usable/unusable/fetch-failure/force-stt branches offline.

Contract dependencies:
  - Ground truth JSON schema matches the Issue #21 specification (fixture_id, language, script,
    speech_spans, slide_change_timestamps, key_fields, usable_ocr_threshold_chars, caption_variant).
  - lectural_bench.metrics (wer_cer, terminology_recall, timestamp_error, voiced_recall_and_gap,
    frame_recall_and_duplicate_rate, ocr_quality) is an interface dependency imported lazily;
    if unavailable in the environment, benchmark execution gracefully notes its status.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import platform
import re
import statistics
import sys
import tempfile
import time
from typing import Any, Callable
from unittest.mock import patch
# Make `import lectural` and `from scripts.perf_smoke ...` work regardless of launch directory.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    from scripts.perf_smoke import StageSampler, _dep_versions, _machine_spec
except ImportError:
    from perf_smoke import StageSampler, _dep_versions, _machine_spec


# ============================================================================
# Pure Helper Functions
# ============================================================================

def measure_directory_bytes(path: str | os.PathLike) -> int:
    """Calculate the total size of all files in a directory tree in bytes. Pure.

    Returns 0 if the path does not exist or is empty.
    """
    p = Path(path)
    if not p.exists():
        return 0
    if p.is_file():
        return p.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                continue
    return total


def compute_fixture_duration_sec(gt: dict[str, Any]) -> float:
    """Compute fixture duration in seconds. Pure.

    Reads an explicit fixture metadata field ('duration_sec' or 'duration') if present;
    otherwise approximates it from the last end time of GT speech_spans:
    max over all span[1] values in gt['speech_spans'].
    Falls back to 1.0 second if no speech spans or positive duration is found.
    """
    if "duration_sec" in gt and gt["duration_sec"] is not None:
        try:
            val = float(gt["duration_sec"])
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass

    if "duration" in gt and gt["duration"] is not None:
        try:
            val = float(gt["duration"])
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass

    spans = gt.get("speech_spans", [])
    if spans:
        ends: list[float] = []
        for span in spans:
            if isinstance(span, (list, tuple)) and len(span) >= 2 and span[1] is not None:
                try:
                    ends.append(float(span[1]))
                except (ValueError, TypeError):
                    continue
        if ends:
            max_end = max(ends)
            if max_end > 0:
                return max_end

    return 1.0


def clear_model_caches() -> None:
    """Trigger in-process garbage collection (`gc.collect()`) between benchmark repetitions.

    Note: This collects unreferenced in-memory Python objects; it is NOT a real OS-level
    page cache clear or hardware VRAM purge. Cold-run isolation across separate processes
    should be driven by external harness execution rather than within a single Python runtime.
    """
    gc.collect()

# ============================================================================
# Caption and Fallback Injection Function
# ============================================================================

def acquire_speech_with_caption_injection(
    gt: dict[str, Any],
    audio_path: str | os.PathLike,
    vtt: str | os.PathLike | None = None,
    out_dir: str | os.PathLike | None = None,
    source: Any | None = None,
    model: str = "medium",
    transcribe_mock: Any | None = None,
) -> Any:
    """Acquire speech for a benchmark fixture with simulated caption/fallback conditions.

    Given a fixture GT JSON with a `caption_variant` field
    ('usable' | 'unusable' | 'fetch_failure' | 'force_stt'):
      1. Constructs or validates an InputSource with kind=SourceKind.YOUTUBE.
      2. Monkeypatches lectural.acquisition.fetch_caption_segments:
         - 'usable': returns parsed Segments from fixture VTT via lectural.acquisition.parse_vtt.
         - 'unusable': returns a near-empty/garbage list ([Segment(0.0, "x")]), failing usability heuristic.
         - 'fetch_failure': raises RuntimeError, exercising the fetch failure fallback path.
         - 'force_stt': calls acquire_speech with force_stt=True, bypassing caption fetch.
      3. Monkeypatches lectural.media.resolve_audio to return the fixture's local audio file path.

    Uses Python's standard unittest.mock.patch (not pytest's monkeypatch fixture) so that it works
    both in standalone benchmark scripts and inside unit/integration tests.
    """
    if out_dir is None:
        out_dir = tempfile.gettempdir()
    # Lazy product imports (zero heavy imports at module load time)
    from lectural.acquisition import Segment, acquire_speech, parse_vtt
    from lectural.source import InputSource, SourceKind

    caption_variant = str(gt.get("caption_variant", "usable")).lower()
    fixture_id = str(gt.get("fixture_id", "benchmark_fixture"))

    # 1. Construct or validate InputSource with kind=SourceKind.YOUTUBE
    if source is None:
        video_id = gt.get("video_id")
        if not video_id or len(str(video_id)) != 11:
            sanitized = re.sub(r"[^0-9A-Za-z_-]", "", fixture_id)
            video_id = (sanitized + "0123456789a")[:11]
        source = InputSource(
            argument=f"https://www.youtube.com/watch?v={video_id}",
            kind=SourceKind.YOUTUBE,
            locator=f"https://www.youtube.com/watch?v={video_id}",
            title_hint=fixture_id,
            video_id=video_id,
        )
    elif getattr(source, "kind", None) != SourceKind.YOUTUBE:
        raise ValueError(
            f"acquire_speech_with_caption_injection requires an InputSource with kind=SourceKind.YOUTUBE, "
            f"got {getattr(source, 'kind', None)}"
        )

    # 2. Resolve VTT text content
    vtt_content = ""
    if vtt is not None:
        if isinstance(vtt, (str, Path)) and os.path.isfile(str(vtt)):
            vtt_content = Path(vtt).read_text(encoding="utf-8")
        elif isinstance(vtt, str):
            vtt_content = vtt
    elif "vtt" in gt:
        vtt_content = str(gt["vtt"])
    elif "vtt_path" in gt and os.path.isfile(str(gt["vtt_path"])):
        vtt_content = Path(gt["vtt_path"]).read_text(encoding="utf-8")

    # 3. Define mock fetch_caption_segments behavior
    def _mock_fetch_caption_segments(
        video_id: str,
        languages: tuple[str, ...] = ("ko", "en"),
    ) -> list[Segment]:
        if caption_variant == "usable":
            return parse_vtt(vtt_content)
        elif caption_variant == "unusable":
            # Return near-empty / garbage segment list (1 segment, 1 char)
            # which fails captions_are_usable (requires >= 3 segments and >= 20 chars).
            return [Segment(t=0.0, text="x")]
        elif caption_variant == "fetch_failure":
            raise RuntimeError(f"Simulated caption fetch failure for video_id={video_id}")
        elif caption_variant == "force_stt":
            # If called, return parsed VTT, but acquire_speech with force_stt=True skips this branch
            return parse_vtt(vtt_content)
        else:
            raise ValueError(f"Unknown caption_variant: {caption_variant!r}")

    force_stt_arg = (caption_variant == "force_stt")
    resolved_audio_str = str(audio_path)

    # 4. Apply mocks via unittest.mock.patch
    patches = [
        patch("lectural.acquisition.fetch_caption_segments", side_effect=_mock_fetch_caption_segments),
        patch("lectural.media.resolve_audio", return_value=resolved_audio_str),
    ]
    if transcribe_mock is not None:
        patches.append(patch("lectural.speech.transcribe_audio", transcribe_mock))

    with patches[0], patches[1]:
        if len(patches) > 2:
            with patches[2]:
                return acquire_speech(source, str(out_dir), force_stt=force_stt_arg, model=model)
        else:
            return acquire_speech(source, str(out_dir), force_stt=force_stt_arg, model=model)


# ============================================================================
# Quality Metrics Evaluation (Interface Dependency on lectural_bench.metrics)
# ============================================================================

def slide_cer_reference(slides_text: dict[str, Any] | None) -> str | None:
    """Join unique authored slide texts, skipping near-duplicate copies. Pure.

    Dual keys (`slide_00_title.png` and `slide_00_title`) are collapsed by
    ignoring `.png` names. Near-duplicate slides are excluded because
    production dedupe drops them, so they must not inflate the CER reference.
    """
    if not slides_text:
        return None
    seen: list[str] = []
    for key, raw in slides_text.items():
        name = str(key)
        if name.endswith(".png") or "near_dup" in name:
            continue
        text = str(raw).strip()
        if text and text not in seen:
            seen.append(text)
    return "\n".join(seen) if seen else None


def evaluate_quality_metrics(
    gt: dict[str, Any],
    track: Any,
    speech_spans: list[tuple[float, float]],
    slides: list[Any],
    raw_frames: list[Any],
    slide_frames: list[Any],
) -> dict[str, Any]:
    """Evaluate extraction quality against fixture ground truth.

    Calls the six functions from `lectural_bench.metrics` per the Slice 4 contract:
      - wer_cer(ground_truth_text, hypothesis_text, language) -> dict
      - terminology_recall(ground_truth_terms, hypothesis_text, language) -> float
      - timestamp_error(ground_truth_cue_times, hypothesis_cue_times) -> dict
      - voiced_recall_and_gap(ground_truth_speech_spans, detected_spans) -> dict
      - frame_recall_and_duplicate_rate(ground_truth_slide_change_timestamps, kept, candidate) -> dict
      - ocr_quality(ground_truth_key_fields, ocr_text, usable_threshold_chars) -> dict

    If `lectural_bench.metrics` is not yet importable (e.g. running in a worktree where
    slice 3 has not landed), records a clear interface status rather than failing.
    """
    try:
        from lectural_bench.metrics import (  # type: ignore[import-not-found]
            frame_recall_and_duplicate_rate,
            ocr_quality,
            terminology_recall,
            timestamp_error,
            voiced_recall_and_gap,
            wer_cer,
        )
    except ImportError as exc:
        return {
            "status": "deferred",
            "reason": f"lectural_bench.metrics unavailable ({exc.__class__.__name__}: {exc})",
        }

    speech_source = getattr(track, "source", "unknown") if track else "unknown"
    results: dict[str, Any] = {"status": "computed", "speech_source": speech_source}
    language = str(gt.get("language", "en"))
    gt_script = str(gt.get("script", ""))
    hyp_text = " ".join(s.text for s in getattr(track, "segments", []))

    # 1. WER / CER
    try:
        wer_cer_res = wer_cer(gt_script, hyp_text, language)
        results["wer_cer"] = wer_cer_res
        if speech_source == "caption":
            # Explicitly mark caption path fidelity to avoid presenting caption WER as STT accuracy
            results["caption_fidelity"] = wer_cer_res
    except Exception as exc:  # noqa: BLE001
        results["wer_cer"] = {"error": f"{exc.__class__.__name__}: {exc}"}
    # 2. Terminology recall
    terms = gt.get("terms")
    if not isinstance(terms, list) or not terms:
        # Fallback only fires for malformed/legacy GT missing an explicit
        # "terms" list; key_fields VALUES are the actual spoken terms
        # (e.g. "Geoffrey Hinton"), never the schema key names (e.g.
        # "key_author"), which would silently score recall against text
        # that was never in the script.
        key_fields = gt.get("key_fields", {})
        terms = [str(v) for v in key_fields.values()] if isinstance(key_fields, dict) else []
    try:
        results["terminology_recall"] = terminology_recall(terms, hyp_text, language)
    except Exception as exc:  # noqa: BLE001
        results["terminology_recall"] = {"error": f"{exc.__class__.__name__}: {exc}"}

    # 3. Timestamp error
    gt_cues: list[float] = []
    for span in gt.get("speech_spans", []):
        if isinstance(span, (list, tuple)) and len(span) >= 1:
            try:
                gt_cues.append(float(span[0]))
            except (ValueError, TypeError):
                continue
    hyp_cues = [float(s.t) for s in getattr(track, "segments", [])]
    try:
        results["timestamp_error"] = timestamp_error(gt_cues, hyp_cues)
    except Exception as exc:  # noqa: BLE001
        results["timestamp_error"] = {"error": f"{exc.__class__.__name__}: {exc}"}

    # 4. Voiced speech recall and untranscribed gap
    gt_spans = [
        (float(span[0]), float(span[1]))
        for span in gt.get("speech_spans", [])
        if isinstance(span, (list, tuple)) and len(span) >= 2
    ]
    det_spans = [(float(s[0]), float(s[1])) for s in speech_spans if len(s) >= 2]
    try:
        results["voiced_recall_and_gap"] = voiced_recall_and_gap(gt_spans, det_spans)
    except Exception as exc:  # noqa: BLE001
        results["voiced_recall_and_gap"] = {"error": f"{exc.__class__.__name__}: {exc}"}

    # 5. Frame recall and duplicate rate
    gt_slide_changes = [float(t) for t in gt.get("slide_change_timestamps", [])]
    near_dup_ts = [float(t) for t in gt.get("near_duplicate_timestamps", [])]
    inc_ts = [float(t) for t in gt.get("incremental_timestamps", [])]
    kept_times = [float(getattr(f, "timestamp", 0.0)) for f in slides]
    candidate_times = [float(getattr(f, "timestamp", 0.0)) for f in raw_frames]
    try:
        results["frame_recall_and_duplicate_rate"] = frame_recall_and_duplicate_rate(
            gt_slide_changes,
            kept_times,
            candidate_times,
            near_duplicate_timestamps=near_dup_ts or None,
            incremental_timestamps=inc_ts or None,
        )
    except Exception as exc:  # noqa: BLE001
        results["frame_recall_and_duplicate_rate"] = {"error": f"{exc.__class__.__name__}: {exc}"}

    # 6. OCR quality
    key_fields = gt.get("key_fields", {})
    usable_thresh = int(gt.get("usable_ocr_threshold_chars", 12))
    combined_ocr = " ".join(
        getattr(f, "ocr_text", "") for f in slide_frames if getattr(f, "ocr_text", "")
    )
    combined_ref = slide_cer_reference(gt.get("slides_text"))
    try:
        results["ocr_quality"] = ocr_quality(
            key_fields,
            combined_ocr,
            usable_thresh,
            slide_reference_text=combined_ref,
        )
    except Exception as exc:  # noqa: BLE001
        results["ocr_quality"] = {"error": f"{exc.__class__.__name__}: {exc}"}
    return results


def evaluate_degraded_slide_ocr(gt: dict[str, Any], degraded_slide_paths: list[Path]) -> dict[str, Any]:
    """Run OCR on the fixture's standalone visually-degraded slide images.

    Scores each `slide_degraded_l*.png` with `lectural.ocr.ocr_image` against
    the fixture's slide_04 authored text and key fields via `lectural_bench.metrics.ocr_quality`.
    """
    try:
        from lectural.ocr import ocr_image
        from lectural_bench.metrics import ocr_quality
    except ImportError as exc:
        return {"status": "deferred", "reason": f"{exc.__class__.__name__}: {exc}"}

    key_fields = gt.get("key_fields", {})
    usable_thresh = int(gt.get("usable_ocr_threshold_chars", 12))
    ocr_lang = "korean"

    # Find slide_04 reference text from slides_text
    slide_4_ref = ""
    slides_text = gt.get("slides_text", {})
    for k, v in slides_text.items():
        if "slide_04" in k:
            slide_4_ref = v
            break
    if not slide_4_ref and slides_text:
        slide_4_ref = list(slides_text.values())[-1]

    if slide_4_ref:
        ref_lower = slide_4_ref.lower()
        slide_4_key_fields = {
            k: v for k, v in key_fields.items()
            if str(v).lower() in ref_lower or k.lower() in ref_lower
        }
        if not slide_4_key_fields:
            slide_4_key_fields = key_fields
    else:
        slide_4_key_fields = key_fields

    per_level: dict[str, Any] = {}
    for path in degraded_slide_paths:
        try:
            text, engine_used = ocr_image(str(path), lang=ocr_lang)
            per_level[path.stem] = {
                "engine_used": engine_used,
                **ocr_quality(
                    slide_4_key_fields,
                    text,
                    usable_thresh,
                    slide_reference_text=slide_4_ref or None,
                ),
            }
        except Exception as exc:  # noqa: BLE001
            per_level[path.stem] = {"error": f"{exc.__class__.__name__}: {exc}"}
    return per_level


# ============================================================================
# Resource Measurement Function (StageSampler Integration)
# ============================================================================

def measure_fixture_run(
    fixture_data: dict[str, Any] | str | os.PathLike,
    out_dir: str | os.PathLike,
    *,
    sample_interval: float = 0.2,
    skip_ocr: bool = False,
    model: str = "medium",
    media_variant: str = "clean",
    temp_dir: str | os.PathLike | None = None,
    audio_path: str | os.PathLike | None = None,
    video_path: str | os.PathLike | None = None,
    vtt_path: str | os.PathLike | None = None,
    transcribe_mock: Any | None = None,
) -> dict[str, Any]:
    """Execute one run of a local fixture under resource measurement.

    Wraps a local fixture run (distinct from perf_smoke's YouTube-only run) to produce:
      - per-stage CPU% (avg/peak) and RSS (avg/peak) sampled across the process tree via StageSampler
      - per-stage wall time in seconds
      - storage delta (target directory size before and after via measure_directory_bytes,
        plus separate temp directory byte measurement)
      - RTF = wall_time / fixture_duration_sec (overall and per stage)
      - extraction quality metrics against ground truth via evaluate_quality_metrics
    """
    out_p = Path(out_dir)
    out_p.mkdir(parents=True, exist_ok=True)
    # Sibling directory, never nested under out_p: measure_directory_bytes(out_p)
    # must not silently include the scratch tree, or storage totals double-count it.
    temp_p = Path(temp_dir) if temp_dir else (out_p.parent / f"_work_{out_p.name}")
    temp_p.mkdir(parents=True, exist_ok=True)
    media_variant = (media_variant or "clean").lower()
    if media_variant not in ("clean", "degraded"):
        raise ValueError(f"media_variant must be 'clean' or 'degraded', got {media_variant!r}")

    # 1. Resolve GT dict and companion fixture file paths
    gt: dict[str, Any] = {}
    fixture_dir: Path | None = None

    if isinstance(fixture_data, dict):
        gt = fixture_data
    else:
        p = Path(fixture_data)
        if p.is_dir():
            fixture_dir = p
            # Search for gt.json, ground_truth.json, or any json with fixture_id
            gt_candidates = (
                list(p.glob("gt.json"))
                or list(p.glob("ground_truth.json"))
                or list(p.glob("*.json"))
            )
            if gt_candidates:
                gt = json.loads(gt_candidates[0].read_text(encoding="utf-8"))
        elif p.is_file():
            gt = json.loads(p.read_text(encoding="utf-8"))
            fixture_dir = p.parent

    caption_variant = str(gt.get("caption_variant", "usable")).lower()

    # Resolve companion paths if not provided. `media_variant="degraded"` prefers
    # the fixture's noise/silence-injected audio and 360p re-encode so the run
    # actually exercises the injected failure modes, not just clean sources;
    # each falls back to the clean asset when a degraded one is absent.
    if fixture_dir is not None:
        if audio_path is None:
            if media_variant == "degraded":
                audio_candidates = list(fixture_dir.glob("audio_degraded.wav")) or list(
                    fixture_dir.glob("audio.wav")
                )
            else:
                audio_candidates = (
                    list(fixture_dir.glob("audio.wav"))
                    or list(fixture_dir.glob("*.wav"))
                    or list(fixture_dir.glob("*.mp3"))
                )
            if audio_candidates:
                audio_path = audio_candidates[0]
        if video_path is None:
            if media_variant == "degraded":
                video_candidates = list(fixture_dir.glob("video_360p.mp4")) or list(
                    fixture_dir.glob("video.mp4")
                )
            else:
                video_candidates = (
                    list(fixture_dir.glob("video.mp4"))
                    or list(fixture_dir.glob("*.mp4"))
                    or list(fixture_dir.glob("*.webm"))
                )
            if video_candidates:
                video_path = video_candidates[0]
        if vtt_path is None:
            variant_vtt = fixture_dir / f"captions_{caption_variant}.vtt"
            if variant_vtt.is_file():
                vtt_path = variant_vtt
            else:
                vtt_candidates = (
                    list(fixture_dir.glob("captions.vtt"))
                    or list(fixture_dir.glob("*.vtt"))
                )
                if vtt_candidates:
                    vtt_path = vtt_candidates[0]
    fixture_duration_sec = compute_fixture_duration_sec(gt)

    # 2. Storage measurements before run
    initial_target_bytes = measure_directory_bytes(out_p)
    initial_temp_bytes = measure_directory_bytes(temp_p)

    # 3. Setup StageSampler if psutil is available
    sampler: StageSampler | None = None
    try:
        import psutil

        sampler = StageSampler(
            interval=sample_interval,
            _psutil=psutil,
            _proc=psutil.Process(os.getpid()),
        )
        sampler.start()
    except Exception:  # noqa: BLE001
        sampler = None

    stage_wall_times: dict[str, float] = {}
    stage_errors: dict[str, str] = {}

    def timed_stage(label: str, fn: Callable[[], Any]) -> Any:
        if sampler is not None:
            sampler.set_stage(label)
        t0 = time.perf_counter()
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            stage_errors[label] = f"{exc.__class__.__name__}: {exc}"
            raise
        finally:
            stage_wall_times[label] = round(time.perf_counter() - t0, 4)

    # 4. Pipeline stages
    track: Any = None
    speech_spans: list[tuple[float, float]] = []
    raw_frames: list[Any] = []
    slides: list[Any] = []
    slide_frames: list[Any] = []
    quality_metrics: dict[str, Any] = {}

    try:
        # Stage: acquisition (speech acquisition with caption injection)
        resolved_audio = audio_path or (temp_p / "audio.wav")
        track = timed_stage(
            "acquisition",
            lambda: acquire_speech_with_caption_injection(
                gt=gt,
                audio_path=resolved_audio,
                vtt=vtt_path,
                out_dir=temp_p,
                model=model,
                transcribe_mock=transcribe_mock,
            ),
        )

        # Stage: vad (voice activity detection)
        def _run_vad() -> list[tuple[float, float]]:
            from lectural.deps import DependencyError
            from lectural.vad import detect_speech_spans

            target_audio = str(audio_path or (track.meta.get("audio_path", resolved_audio) if track else resolved_audio))
            if os.path.isfile(target_audio):
                try:
                    return detect_speech_spans(target_audio, fixture_duration_sec)
                except DependencyError:
                    # Offline gate has no ffmpeg. Real ffmpeg failures (RuntimeError)
                    # must surface via timed_stage, not look like perfect GT recall.
                    if gt and "speech_spans" in gt:
                        return [tuple(span) for span in gt["speech_spans"]]  # type: ignore
                    return [(0.0, fixture_duration_sec)]
            if gt and "speech_spans" in gt:
                return [tuple(span) for span in gt["speech_spans"]]  # type: ignore
            return [(0.0, fixture_duration_sec)]

        speech_spans = timed_stage("vad", _run_vad)

        # Stages: visual_extract and visual_dedupe (always run when video exists)
        if video_path is not None and os.path.isfile(str(video_path)):
            from lectural.visual import dedupe_frames, extract_candidate_frames

            frames_dir = out_p / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)

            raw_frames = timed_stage(
                "visual_extract",
                lambda: extract_candidate_frames(str(video_path), str(frames_dir)),
            )
            slides = timed_stage(
                "visual_dedupe",
                lambda: dedupe_frames(raw_frames),
            )
        else:
            raw_frames = []
            slides = []
            stage_wall_times["visual_extract"] = 0.0
            stage_wall_times["visual_dedupe"] = 0.0

        # Stage: ocr (conditional on --skip-ocr flag)
        if slides and not skip_ocr:
            from lectural.ocr import ocr_frames

            slide_frames, _ocr_engine = timed_stage(
                "ocr",
                lambda: ocr_frames(slides),
            )
        else:
            slide_frames = slides
            stage_wall_times["ocr"] = 0.0

        # Stage: metrics (evaluate extraction against GT)
        quality_metrics = timed_stage(
            "metrics",
            lambda: evaluate_quality_metrics(
                gt=gt,
                track=track,
                speech_spans=speech_spans,
                slides=slides,
                raw_frames=raw_frames,
                slide_frames=slide_frames,
            ),
        )

        # Always score OCR against the fixture's standalone visually-degraded
        # slide images (slide_degraded_l1/l2.png), independent of media_variant:
        # these are cheap (two extra images) and are the only committed asset
        # that directly exercises Augraphy/PIL-blur degradation for OCR, per
        # the accepted plan's "OCR CER/key-field recall against degraded
        # frames" requirement.
        if fixture_dir is not None:
            degraded_slide_paths = sorted(fixture_dir.glob("slide_degraded_l*.png")) or sorted(
                fixture_dir.glob("slides/slide_degraded_l*.png")
            )
            if degraded_slide_paths:
                quality_metrics["degraded_slide_ocr"] = timed_stage(
                    "degraded_slide_ocr",
                    lambda: evaluate_degraded_slide_ocr(gt, degraded_slide_paths),
                )

    finally:
        if sampler is not None:
            sampler.stop()

    # 5. Storage measurements after run
    final_target_bytes = measure_directory_bytes(out_p)
    final_temp_bytes = measure_directory_bytes(temp_p)
    target_storage_delta_bytes = max(0, final_target_bytes - initial_target_bytes)
    # temp_p is a sibling of out_p (never nested under it, see construction
    # above), so this delta is disjoint from target_storage_delta_bytes --
    # summing them does not double-count the scratch tree.
    temp_storage_delta_bytes = max(0, final_temp_bytes - initial_temp_bytes)

    # 6. Resource metrics & RTF aggregation
    sampler_summary = sampler.summary() if sampler is not None else {}
    total_wall_time = round(sum(stage_wall_times.values()), 4)
    overall_rtf = (
        round(total_wall_time / fixture_duration_sec, 4) if fixture_duration_sec > 0 else 0.0
    )

    per_stage: dict[str, dict[str, Any]] = {}
    for stage, wall_sec in stage_wall_times.items():
        sample_info = sampler_summary.get(stage, {})
        stage_rtf = round(wall_sec / fixture_duration_sec, 4) if fixture_duration_sec > 0 else 0.0
        per_stage[stage] = {
            "wall_time_sec": wall_sec,
            "rtf": stage_rtf,
            "cpu_pct_avg": sample_info.get("cpu_pct_avg", 0.0),
            "cpu_pct_peak": sample_info.get("cpu_pct_peak", 0.0),
            "rss_mb_avg": sample_info.get("rss_mb_avg", 0.0),
            "rss_mb_peak": sample_info.get("rss_mb_peak", 0.0),
            "n_samples": sample_info.get("n_samples", 0),
        }

    return {
        "fixture_id": gt.get("fixture_id", "unknown"),
        "language": gt.get("language", "unknown"),
        "caption_variant": gt.get("caption_variant", "unknown"),
        "skip_ocr": skip_ocr,
        "fixture_duration_sec": fixture_duration_sec,
        "wall_time_sec": total_wall_time,
        "rtf": overall_rtf,
        "storage": {
            "initial_target_bytes": initial_target_bytes,
            "final_target_bytes": final_target_bytes,
            "target_storage_delta_bytes": target_storage_delta_bytes,
            "temp_storage_delta_bytes": temp_storage_delta_bytes,
            "total_storage_delta_bytes": target_storage_delta_bytes + temp_storage_delta_bytes,
        },
        "stages": per_stage,
        "quality_metrics": quality_metrics,
        "stage_errors": stage_errors,
        "speech_source": getattr(track, "source", "unknown") if track else "unknown",
    }


def run_fixture_repetitions(
    fixture_data: dict[str, Any] | str | os.PathLike,
    out_dir: str | os.PathLike,
    *,
    reps: int = 3,
    skip_ocr: bool = False,
    cold: bool = False,
    sample_interval: float = 0.2,
    model: str = "medium",
    media_variant: str = "clean",
    audio_path: str | os.PathLike | None = None,
    video_path: str | os.PathLike | None = None,
    vtt_path: str | os.PathLike | None = None,
    transcribe_mock: Any | None = None,
) -> dict[str, Any]:
    """Execute `reps` runs of a fixture and compute median and variance across runs."""
    runs: list[dict[str, Any]] = []
    base_out = Path(out_dir)

    for rep_idx in range(1, reps + 1):
        if cold:
            clear_model_caches()

        rep_out = base_out / f"rep_{rep_idx}"
        run_res = measure_fixture_run(
            fixture_data=fixture_data,
            out_dir=rep_out,
            sample_interval=sample_interval,
            skip_ocr=skip_ocr,
            model=model,
            media_variant=media_variant,
            audio_path=audio_path,
            video_path=video_path,
            vtt_path=vtt_path,
            transcribe_mock=transcribe_mock,
        )
        run_res["rep"] = rep_idx
        runs.append(run_res)
    wall_times = [r["wall_time_sec"] for r in runs]
    rtfs = [r["rtf"] for r in runs]
    storage_deltas = [r["storage"]["total_storage_delta_bytes"] for r in runs]

    def _stats(values: list[float | int]) -> dict[str, float]:
        f_vals = [float(v) for v in values]
        med = float(statistics.median(f_vals)) if f_vals else 0.0
        var = float(statistics.variance(f_vals)) if len(f_vals) >= 2 else 0.0
        return {"median": round(med, 4), "variance": round(var, 4)}

    # Aggregate per-stage wall time, CPU avg, RSS peak
    all_stages = set()
    for r in runs:
        all_stages.update(r.get("stages", {}).keys())

    stage_aggregates: dict[str, Any] = {}
    for stage in sorted(all_stages):
        stage_walls = [r["stages"][stage]["wall_time_sec"] for r in runs if stage in r["stages"]]
        stage_rtfs = [r["stages"][stage]["rtf"] for r in runs if stage in r["stages"]]
        stage_cpu_avgs = [r["stages"][stage]["cpu_pct_avg"] for r in runs if stage in r["stages"]]
        stage_rss_peaks = [r["stages"][stage]["rss_mb_peak"] for r in runs if stage in r["stages"]]
        stage_aggregates[stage] = {
            "wall_time_sec": _stats(stage_walls),
            "rtf": _stats(stage_rtfs),
            "cpu_pct_avg": _stats(stage_cpu_avgs),
            "rss_mb_peak": _stats(stage_rss_peaks),
        }

    first_run = runs[0] if runs else {}
    # Quality metrics are reported from the first repetition because greedy STT and OCR
    # decoding are deterministic; variation across repetitions is captured in the aggregate resource measurements.
    return {
        "fixture_id": first_run.get("fixture_id", "unknown"),
        "language": first_run.get("language", "unknown"),
        "caption_variant": first_run.get("caption_variant", "unknown"),
        "speech_source": first_run.get("speech_source", "unknown"),
        "skip_ocr": skip_ocr,
        "media_variant": media_variant,
        "cache_mode": "cold" if cold else "warm",
        "reps": reps,
        "fixture_duration_sec": first_run.get("fixture_duration_sec", 1.0),
        "aggregate": {
            "wall_time_sec": _stats(wall_times),
            "rtf": _stats(rtfs),
            "total_storage_delta_bytes": _stats(storage_deltas),
            "stages": stage_aggregates,
        },
        "quality_metrics": first_run.get("quality_metrics", {}),
        "runs": runs,
    }


def find_fixture_dirs(fixtures_dir: str | os.PathLike) -> list[Path]:
    """Find all fixture directories containing a GT JSON file (flat, nested, or comma-separated)."""
    raw_str = str(fixtures_dir)
    targets: list[Path] = []
    if "," in raw_str or ";" in raw_str:
        for part in re.split(r"[,;]", raw_str):
            p_part = Path(part.strip())
            if p_part.exists():
                targets.append(p_part)
    else:
        p_single = Path(fixtures_dir)
        if p_single.exists():
            targets.append(p_single)

    found_dirs: set[Path] = set()
    for p in targets:
        if p.is_file():
            if p.name in ("gt.json", "ground_truth.json"):
                found_dirs.add(p.parent)
            continue
        for gt_candidate in p.rglob("*.json"):
            if gt_candidate.name in ("gt.json", "ground_truth.json"):
                found_dirs.add(gt_candidate.parent)
            else:
                try:
                    data = json.loads(gt_candidate.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and "fixture_id" in data:
                        found_dirs.add(gt_candidate.parent)
                except Exception:
                    continue
    return sorted(found_dirs)


# ============================================================================
# CLI Implementation
# ============================================================================

def build_parser() -> argparse.ArgumentParser:
    """Build the benchmark harness argument parser."""
    parser = argparse.ArgumentParser(
        prog="benchmark.py",
        description="Offline benchmark harness for LecturAL speech/OCR extraction quality and resource cost.",
    )
    parser.add_argument(
        "--fixtures-dir",
        type=str,
        default="tests/fixtures/benchmark",
        help="Directory containing benchmark fixtures (default: tests/fixtures/benchmark)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="output/benchmark",
        help="Output directory for benchmark reports and raw artifacts (default: output/benchmark)",
    )
    parser.add_argument(
        "--platform-label",
        type=str,
        default=platform.machine() or "unknown",
        help="Label for the execution platform (e.g. x86_64, arm64, pi-server) (default: host architecture)",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--cold",
        action="store_true",
        help="Run in cold-cache mode (clear model caches between repetitions)",
    )
    group.add_argument(
        "--warm",
        action="store_true",
        help="Run in warm-cache mode (allow cached models across repetitions) (default)",
    )

    parser.add_argument(
        "--reps",
        type=int,
        default=3,
        help="Number of repetitions per fixture condition (default: 3)",
    )
    parser.add_argument(
        "--skip-ocr",
        action="store_true",
        help="Run the OCR-off side of the paired comparison",
    )
    parser.add_argument(
        "--media-variant",
        choices=["clean", "degraded"],
        default="clean",
        help=(
            "'clean' uses the fixture's clean TTS audio/720p video (default); "
            "'degraded' uses audio_degraded.wav/video_360p.mp4 (falls back to "
            "clean assets when a degraded one is absent). Standalone degraded "
            "slide images are always OCR-scored regardless of this flag."
        ),
    )
    parser.add_argument(
        "--sample-interval",
        type=float,
        default=0.2,
        help="StageSampler interval in seconds (default: 0.2)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="medium",
        help="Whisper STT model size to evaluate (default: medium)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse fixtures and print execution plan without invoking speech/OCR models",
    )
    parser.add_argument(
        "--observational-perf-smoke",
        type=str,
        default=None,
        help=(
            "Path to a raw scripts/perf_smoke.py JSON result (e.g. the real "
            "555-second YouTube run) to embed as one non-repeated, "
            "non-cold/warm-controlled observational row in the report. "
            "Never merged into the controlled fixture results or treated as "
            "ground truth."
        ),
    )
    return parser


def build_observational_entry(perf_smoke_json_path: str | os.PathLike) -> dict[str, Any]:
    """Wrap a raw scripts/perf_smoke.py JSON result as one observational report row. Pure.

    `observational: true` marks this row as a live, uncontrolled real-world
    data point (e.g. the 555-second YouTube run) -- never ground truth, never
    averaged into the fixture-derived `results` list's medians/variances.
    """
    raw = json.loads(Path(perf_smoke_json_path).read_text(encoding="utf-8"))
    return {
        "observational": True,
        "source_harness": raw.get("harness", "scripts/perf_smoke.py"),
        "source_url": raw.get("url"),
        "started_at": raw.get("started_at"),
        "finished_at": raw.get("finished_at"),
        "machine": raw.get("machine", {}),
        "dependency_versions": raw.get("dependency_versions", {}),
        "status": raw.get("status"),
        "overall_pass": raw.get("overall_pass"),
        "stage_wall_seconds": raw.get("stage_wall_seconds", {}),
        "stage_resource_usage": raw.get("stage_resource_usage", {}),
        "raw_source_path": str(perf_smoke_json_path),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for scripts/benchmark.py."""
    parser = build_parser()
    args = parser.parse_args(argv)

    is_cold = bool(args.cold)
    cache_mode = "cold" if is_cold else "warm"

    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    fixtures = find_fixture_dirs(args.fixtures_dir)

    report: dict[str, Any] = {
        "schema_version": 1,
        "harness": "scripts/benchmark.py",
        "started_at": started_at,
        "platform_label": args.platform_label,
        "machine": _machine_spec(),
        "dependency_versions": _dep_versions(),
        "config": {
            "fixtures_dir": args.fixtures_dir,
            "out": args.out,
            "platform_label": args.platform_label,
            "cache_mode": cache_mode,
            "reps": args.reps,
            "skip_ocr": args.skip_ocr,
            "media_variant": args.media_variant,
            "sample_interval": args.sample_interval,
            "model": args.model,
        },
        "fixtures_found": len(fixtures),
        "results": [],
        "observational_results": [],
    }

    if args.observational_perf_smoke:
        report["observational_results"].append(
            build_observational_entry(args.observational_perf_smoke)
        )

    print(
        f"LecturAL Benchmark Harness [Platform: {args.platform_label}, Mode: {cache_mode}, Reps: {args.reps}, Skip-OCR: {args.skip_ocr}]"
    )
    print(f"Found {len(fixtures)} fixture(s) in {args.fixtures_dir}")

    if not fixtures:
        print("Note: No fixtures found in directory. Fixtures may still be generating in parallel.")
        report_path = out_dir / f"benchmark_{time.strftime('%Y%m%d_%H%M%S')}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Empty benchmark summary written to {report_path}")
        return 0

    if args.dry_run:
        print("[DRY RUN] Plan:")
        for idx, f_dir in enumerate(fixtures, 1):
            print(f"  {idx}. {f_dir.name}")
        return 0

    # Run execution matrix across discovered fixtures
    for f_dir in fixtures:
        print(f"\nEvaluating fixture: {f_dir.name} ({args.reps} reps)...")
        res = run_fixture_repetitions(
            fixture_data=f_dir,
            out_dir=out_dir / f_dir.name,
            reps=args.reps,
            skip_ocr=args.skip_ocr,
            cold=is_cold,
            sample_interval=args.sample_interval,
            model=args.model,
            media_variant=args.media_variant,
        )
        report["results"].append(res)
        agg = res["aggregate"]
        speech_src = res.get("speech_source", "unknown")
        print(
            f"  RTF: {agg['rtf']['median']:.4f} (var: {agg['rtf']['variance']:.4f}) | "
            f"Wall Time: {agg['wall_time_sec']['median']:.2f}s | "
            f"Storage Delta: {agg['total_storage_delta_bytes']['median']} bytes | "
            f"Speech Source: {speech_src}"
        )

    report_path = out_dir / f"benchmark_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nComplete benchmark report written to {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
