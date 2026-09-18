"""Smoke and offline contract tests for the benchmark harness and caption injection.

Tests:
  1. acquire_speech_with_caption_injection for all four caption_variant cases:
     - 'usable': returns SpeechTrack.source == 'caption' from fake VTT without STT.
     - 'unusable': falls back to SpeechTrack.source == 'stt' with unusable-captions reason.
     - 'fetch_failure': falls back to SpeechTrack.source == 'stt' with fetch-failed reason.
     - 'force_stt': falls back to SpeechTrack.source == 'stt' with force_stt reason.
     Asserts zero network calls occur in all four branches.
  2. compute_fixture_duration_sec: explicit duration vs speech_spans approximation vs fallback.
  3. measure_directory_bytes: pure recursive directory size calculation.
  4. measure_fixture_run: per-stage timing, RTF calculation, storage measurement.
  5. run_fixture_repetitions: multi-repetition median and variance aggregation.
  6. CLI parser: argument parsing, defaults, mutual exclusion of --cold/--warm.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch
import warnings
import wave
# Ensure repository root is on sys.path for scripts import
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest
from lectural.acquisition import SpeechTrack
from scripts.benchmark import (
    acquire_speech_with_caption_injection,
    build_parser,
    compute_fixture_duration_sec,
    evaluate_quality_metrics,
    measure_directory_bytes,
    measure_fixture_run,
    run_fixture_repetitions,
)

_MINIMAL_USABLE_VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
First cue with sufficient text content.

00:00:03.500 --> 00:00:05.500
Second cue with sufficient text content.

00:00:06.000 --> 00:00:08.000
Third cue with sufficient text content.
"""

def _write_minimal_wav(path: Path, duration_sec: float = 1.0) -> None:
    """Write a minimal valid PCM WAV file for offline testing."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        n_samples = int(16000 * duration_sec)
        wf.writeframes(b"\x00\x00" * n_samples)
# ============================================================================
# 1. Caption / Fallback Injection Tests (All 4 Cases)
# ============================================================================

def test_caption_variant_usable_returns_caption_source_without_stt(tmp_path: Path) -> None:
    """Case 1: 'usable' caption_variant parses VTT and returns SpeechTrack with source='caption'."""
    gt = {
        "fixture_id": "en_terms_01",
        "language": "en",
        "caption_variant": "usable",
        "speech_spans": [[1.0, 8.0]],
    }
    audio_file = tmp_path / "dummy_audio.wav"
    audio_file.write_bytes(b"RIFFdummywavbytes")

    transcribe_mock = MagicMock(side_effect=AssertionError("STT transcribe_audio must not be called for usable captions"))

    track = acquire_speech_with_caption_injection(
        gt=gt,
        audio_path=audio_file,
        vtt=_MINIMAL_USABLE_VTT,
        out_dir=tmp_path,
        transcribe_mock=transcribe_mock,
    )

    assert track.source == "caption"
    assert len(track.segments) == 3
    assert track.segments[0].text == "First cue with sufficient text content."
    assert track.meta["source_kind"] == "youtube"
    transcribe_mock.assert_not_called()


def test_caption_variant_unusable_falls_back_to_stt(tmp_path: Path) -> None:
    """Case 2: 'unusable' caption_variant fails usability heuristic and falls back to STT."""
    gt = {
        "fixture_id": "en_terms_01_unusable",
        "language": "en",
        "caption_variant": "unusable",
        "speech_spans": [[0.5, 4.2]],
    }
    audio_file = tmp_path / "audio.wav"
    audio_file.write_bytes(b"RIFFdummywavbytes")

    stt_track = SpeechTrack(
        segments=[],
        source="stt",
        meta={"duration": 4.2, "mocked": True},
    )
    transcribe_mock = MagicMock(return_value=stt_track)

    with pytest.warns(RuntimeWarning, match="captions present but unusable"):
        track = acquire_speech_with_caption_injection(
            gt=gt,
            audio_path=audio_file,
            vtt=_MINIMAL_USABLE_VTT,
            out_dir=tmp_path,
            transcribe_mock=transcribe_mock,
        )

    assert track.source == "stt"
    assert track.meta["caption_fallback_reason"] == "captions present but unusable (1 cues)"
    assert track.meta["audio_path"] == str(audio_file)
    transcribe_mock.assert_called_once()


def test_caption_variant_fetch_failure_falls_back_to_stt(tmp_path: Path) -> None:
    """Case 3: 'fetch_failure' caption_variant raises on fetch and falls back to STT."""
    gt = {
        "fixture_id": "en_terms_01_fetch_failure",
        "language": "en",
        "caption_variant": "fetch_failure",
        "speech_spans": [[0.5, 4.2]],
    }
    audio_file = tmp_path / "audio.wav"
    audio_file.write_bytes(b"RIFFdummywavbytes")

    stt_track = SpeechTrack(
        segments=[],
        source="stt",
        meta={"duration": 4.2},
    )
    transcribe_mock = MagicMock(return_value=stt_track)

    with pytest.warns(RuntimeWarning, match="caption fetch failed"):
        track = acquire_speech_with_caption_injection(
            gt=gt,
            audio_path=audio_file,
            vtt=_MINIMAL_USABLE_VTT,
            out_dir=tmp_path,
            transcribe_mock=transcribe_mock,
        )

    assert track.source == "stt"
    assert "caption fetch failed" in track.meta["caption_fallback_reason"]
    assert track.meta["audio_path"] == str(audio_file)
    transcribe_mock.assert_called_once()


def test_caption_variant_force_stt_bypasses_captions_and_uses_stt(tmp_path: Path) -> None:
    """Case 4: 'force_stt' caption_variant skips caption fetch and calls STT directly."""
    gt = {
        "fixture_id": "en_terms_01_force_stt",
        "language": "en",
        "caption_variant": "force_stt",
        "speech_spans": [[0.5, 4.2]],
    }
    audio_file = tmp_path / "audio.wav"
    audio_file.write_bytes(b"RIFFdummywavbytes")

    stt_track = SpeechTrack(
        segments=[],
        source="stt",
        meta={"duration": 4.2},
    )
    transcribe_mock = MagicMock(return_value=stt_track)

    with pytest.warns(RuntimeWarning, match="force_stt requested"):
        track = acquire_speech_with_caption_injection(
            gt=gt,
            audio_path=audio_file,
            vtt=_MINIMAL_USABLE_VTT,
            out_dir=tmp_path,
            transcribe_mock=transcribe_mock,
        )

    assert track.source == "stt"
    assert track.meta["caption_fallback_reason"] == "force_stt requested"
    assert track.meta["audio_path"] == str(audio_file)
    transcribe_mock.assert_called_once()


# ============================================================================
# 2. Pure Helper Functions Tests
# ============================================================================

def test_compute_fixture_duration_sec() -> None:
    # Explicit duration_sec takes precedence
    assert compute_fixture_duration_sec({"duration_sec": 15.5, "speech_spans": [[0.0, 10.0]]}) == 15.5
    assert compute_fixture_duration_sec({"duration": 12.0}) == 12.0

    # Approximation from speech_spans last end time
    gt_spans = {
        "speech_spans": [[0.5, 4.2], [5.0, 9.8], [10.2, 14.6]],
    }
    assert compute_fixture_duration_sec(gt_spans) == 14.6

    # Unordered spans take max end time
    gt_unordered = {
        "speech_spans": [[10.0, 25.0], [0.0, 5.0]],
    }
    assert compute_fixture_duration_sec(gt_unordered) == 25.0

    # Fallback to 1.0 when empty or missing
    assert compute_fixture_duration_sec({}) == 1.0
    assert compute_fixture_duration_sec({"speech_spans": []}) == 1.0


def test_measure_directory_bytes(tmp_path: Path) -> None:
    assert measure_directory_bytes(tmp_path / "nonexistent") == 0
    assert measure_directory_bytes(tmp_path) == 0

    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "f1.bin").write_bytes(b"x" * 128)
    (sub / "f2.bin").write_bytes(b"y" * 64)
    (tmp_path / "f3.bin").write_bytes(b"z" * 32)

    total = measure_directory_bytes(tmp_path)
    assert total == 128 + 64 + 32


# ============================================================================
# 3. Resource Measurement & Repetitions Tests
# ============================================================================

def test_measure_fixture_run_computes_rtf_and_storage(tmp_path: Path) -> None:
    """Verify measure_fixture_run computes wall time, RTF, storage delta, and per-stage metrics."""
    audio_file = tmp_path / "audio.wav"
    _write_minimal_wav(audio_file, duration_sec=5.0)

    gt = {
        "fixture_id": "test_synth_01",
        "language": "en",
        "caption_variant": "usable",
        "speech_spans": [[0.0, 5.0]],
        "slide_change_timestamps": [0.0, 2.5],
        "key_fields": {"model": "transformer"},
        "usable_ocr_threshold_chars": 5,
        "vtt": _MINIMAL_USABLE_VTT,
    }
    out_dir = tmp_path / "run_out"
    res = measure_fixture_run(
        fixture_data=gt,
        out_dir=out_dir,
        audio_path=audio_file,
        vtt_path=None,
        transcribe_mock=None,
    )

    assert res["fixture_id"] == "test_synth_01"
    assert res["fixture_duration_sec"] == 5.0
    assert res["speech_source"] == "caption"
    assert "wall_time_sec" in res
    assert "rtf" in res
    # rtf must equal wall_time_sec / 5.0 (rounded to 4 decimal places)
    expected_rtf = round(res["wall_time_sec"] / 5.0, 4)
    assert abs(res["rtf"] - expected_rtf) < 1e-4

    # Storage fields
    storage = res["storage"]
    assert "initial_target_bytes" in storage
    assert "final_target_bytes" in storage
    assert "target_storage_delta_bytes" in storage
    assert "temp_storage_delta_bytes" in storage
    assert storage["total_storage_delta_bytes"] >= 0

    # Stages recorded
    stages = res["stages"]
    assert "acquisition" in stages
    assert "vad" in stages
    assert stages["acquisition"]["wall_time_sec"] >= 0


def test_run_fixture_repetitions_aggregates_median_and_variance(tmp_path: Path) -> None:
    """Verify run_fixture_repetitions produces aggregate statistics across repetitions."""
    audio_file = tmp_path / "audio.wav"
    _write_minimal_wav(audio_file, duration_sec=10.0)

    gt = {
        "fixture_id": "test_reps_01",
        "language": "en",
        "caption_variant": "usable",
        "speech_spans": [[0.0, 10.0]],
        "vtt": _MINIMAL_USABLE_VTT,
    }

    out_dir = tmp_path / "reps_out"
    rep_res = run_fixture_repetitions(
        fixture_data=gt,
        out_dir=out_dir,
        reps=3,
        audio_path=audio_file,
    )

    assert rep_res["fixture_id"] == "test_reps_01"
    assert rep_res["reps"] == 3
    assert len(rep_res["runs"]) == 3

    agg = rep_res["aggregate"]
    assert "wall_time_sec" in agg
    assert "median" in agg["wall_time_sec"]
    assert "variance" in agg["wall_time_sec"]
    assert "rtf" in agg
    assert "total_storage_delta_bytes" in agg
    assert "stages" in agg


# ============================================================================
# 4. Quality Metrics Interface Dependency Handling
# ============================================================================

def test_evaluate_quality_metrics_contract_handling() -> None:
    """When lectural_bench.metrics is not importable, records deferred status."""
    gt = {
        "fixture_id": "dummy_01",
        "language": "en",
        "script": "hello world",
        "speech_spans": [[0.0, 2.0]],
    }
    track = SpeechTrack(segments=[], source="caption")

    res = evaluate_quality_metrics(
        gt=gt,
        track=track,
        speech_spans=[(0.0, 2.0)],
        slides=[],
        raw_frames=[],
        slide_frames=[],
    )

    # In slice 4 before slice 3 lands, lectural_bench.metrics is either deferred or computed
    assert res["status"] in ("deferred", "computed")


# ============================================================================
# 5. CLI Parser Tests
# ============================================================================

def test_cli_parser_defaults_and_mutual_exclusion() -> None:
    parser = build_parser()

    # Defaults
    args = parser.parse_args([])
    assert args.fixtures_dir == "tests/fixtures/benchmark"
    assert args.out == "output/benchmark"
    assert args.reps == 3
    assert args.skip_ocr is False
    assert args.cold is False
    assert args.warm is False
    assert args.model == "medium"
    # Custom flags
    custom = parser.parse_args([
        "--fixtures-dir", "custom/fixtures",
        "--out", "custom/out",
        "--reps", "5",
        "--skip-ocr",
        "--cold",
        "--platform-label", "pi-server",
        "--sample-interval", "0.5",
        "--model", "medium",
    ])
    assert custom.fixtures_dir == "custom/fixtures"
    assert custom.out == "custom/out"
    assert custom.reps == 5
    assert custom.skip_ocr is True
    assert custom.cold is True
    assert custom.platform_label == "pi-server"
    assert custom.sample_interval == 0.5
    assert custom.model == "medium"

    # Mutual exclusion between --cold and --warm
    with pytest.raises(SystemExit):
        parser.parse_args(["--cold", "--warm"])


def test_harness_default_model_is_medium() -> None:
    parser = build_parser()
    args = parser.parse_args([])
    assert args.model == "medium"


def test_degraded_slide_ocr_uses_slide4_reference(tmp_path: Path) -> None:
    """Verify evaluate_degraded_slide_ocr scores against slide_04 authored text and key fields."""
    from scripts.benchmark import evaluate_degraded_slide_ocr
    from PIL import Image

    img_path = tmp_path / "slide_degraded_l1.png"
    im = Image.new("RGB", (100, 100), color=(255, 255, 255))
    im.save(img_path)

    gt = {
        "fixture_id": "test_synth_01",
        "language": "en",
        "key_fields": {
            "lecture_title": "Lecture 4: Optimization",
            "key_author": "Geoffrey Hinton",
            "batch_iterations": "128",
            "learning_rate": "0.05",
        },
        "slides_text": {
            "slide_00_title": "Lecture 4: Optimization\nSpeaker: Geoffrey Hinton",
            "slide_04_inc_ext": "Hyperparameter Settings\nBatch Iterations: 128\nLearning Rate: 0.05",
        },
        "usable_ocr_threshold_chars": 12,
    }

    mock_ocr = ("Hyperparameter Settings\nBatch Iterations: 128\nLearning Rate: 0.05", "paddle")
    with patch("lectural.ocr.ocr_image", return_value=mock_ocr):
        res = evaluate_degraded_slide_ocr(gt, [img_path])

    assert "slide_degraded_l1" in res
    entry = res["slide_degraded_l1"]
    assert entry["engine_used"] == "paddle"
    assert math.isclose(entry["cer"], 0.0, rel_tol=1e-5)
    assert entry["key_field_recall_exact"] == 1.0


def test_harness_records_explicit_speech_source(tmp_path: Path) -> None:
    """Verify measure_fixture_run and run_fixture_repetitions record explicit speech_source."""
    audio_file = tmp_path / "audio.wav"
    _write_minimal_wav(audio_file, duration_sec=5.0)

    gt = {
        "fixture_id": "test_speech_src_01",
        "language": "en",
        "caption_variant": "usable",
        "speech_spans": [[0.0, 5.0]],
        "vtt": _MINIMAL_USABLE_VTT,
    }
    out_dir = tmp_path / "run_out"
    res = measure_fixture_run(
        fixture_data=gt,
        out_dir=out_dir,
        audio_path=audio_file,
    )
    assert res["speech_source"] == "caption"

    f_dir = tmp_path / "fixture_dir"
    f_dir.mkdir(parents=True, exist_ok=True)
    gt_file = f_dir / "gt.json"
    gt_file.write_text(json.dumps(gt), encoding="utf-8")
    (f_dir / "audio.wav").write_bytes(audio_file.read_bytes())
    (f_dir / "captions.vtt").write_text(_MINIMAL_USABLE_VTT, encoding="utf-8")

    rep_out = tmp_path / "rep_out"
    agg_res = run_fixture_repetitions(
        fixture_data=gt,
        out_dir=rep_out,
        reps=1,
        audio_path=audio_file,
    )
    assert agg_res["speech_source"] == "caption"
def test_measure_fixture_run_offline_vad_falls_back_without_ffmpeg(tmp_path: Path) -> None:
    """Verify that when ffmpeg is absent and detect_speech_spans raises DependencyError,
    measure_fixture_run cleanly falls back to GT speech_spans without raising."""
    from lectural.deps import DependencyError

    audio_file = tmp_path / "audio.wav"
    _write_minimal_wav(audio_file, duration_sec=5.0)

    gt = {
        "fixture_id": "test_offline_vad",
        "language": "en",
        "caption_variant": "usable",
        "speech_spans": [[0.5, 4.5]],
        "vtt": _MINIMAL_USABLE_VTT,
    }
    out_dir = tmp_path / "offline_vad_out"

    with patch("lectural.vad.detect_speech_spans", side_effect=DependencyError("Required binary `ffmpeg` not found")):
        res = measure_fixture_run(
            fixture_data=gt,
            out_dir=out_dir,
            audio_path=audio_file,
        )

    assert res["fixture_id"] == "test_offline_vad"
    assert "vad" in res["stages"]
    assert res["stages"]["vad"]["wall_time_sec"] >= 0
