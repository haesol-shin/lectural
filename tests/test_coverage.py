"""Offline coverage gate tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lectural.coverage import CoverageInputs, artifact_check, build_coverage, coverage_inputs_from_extraction, gap_check, scene_coverage, write_coverage
from lectural.synthesis import build_synthesis_input, render_notes_md, render_transcript_md


def _passing_inputs(tmp_path: Path, *, visual_required=True, ocr_required=True, notes_text=None, transcript_text=None) -> CoverageInputs:
    return CoverageInputs(
        video_title="L",
        duration_sec=300.0,
        speech_spans=[(0, 300)],
        segment_times=[30 * i for i in range(10)],
        frame_times=[float(i) for i in range(300)],
        transcript_path=str(tmp_path / "transcript.md"),
        notes_path=str(tmp_path / "notes.md"),
        ocr_engine="paddleocr" if ocr_required else "skipped",
        visual_required=visual_required,
        ocr_required=ocr_required,
        slide_frames_total=1 if visual_required else 0,
        slide_frames_with_text=1 if ocr_required and visual_required else 0,
        transcript_text=transcript_text,
        notes_text=notes_text,
    )


def test_gap_check_pass_and_fail():
    assert gap_check([(0, 300)], [0, 30, 60, 90, 120, 150, 180, 210, 240, 270], 300)["pass"] is True
    bad = gap_check([(0, 300)], [0, 50, 100], 300)
    assert bad["pass"] is False and bad["max_untranscribed_speech_gap_sec"] > 60


def test_scene_coverage_timeline_pass_and_stall_fail():
    good = scene_coverage([10 * i + 5 for i in range(10)], [(0, 100)], 100, bins=10, slide_frames_total=3, slide_frames_with_text=3)
    assert good["timeline_pass"] is True and good["pass"] is True
    bad = scene_coverage([150], [(0, 200)], 200, bins=10, slide_frames_total=1, slide_frames_with_text=1)
    assert bad["timeline_pass"] is False and bad["uncovered_speech_bins"]


@pytest.mark.parametrize("duration", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_visual_timeline_fails_closed_without_positive_finite_duration(duration):
    result = scene_coverage(
        [0.0],
        [(0.0, 10.0)],
        duration,
        visual_required=True,
        ocr_required=False,
    )

    assert result["duration_valid"] is False
    assert result["timeline_pass"] is False
    assert result["pass"] is False


def test_default_visual_source_fails_when_slide_lacks_ocr_text():
    result = scene_coverage([10 * i + 5 for i in range(10)], [(0, 100)], 100, bins=10, slide_frames_total=3, slide_frames_with_text=2)
    assert result["visual_required"] is True and result["ocr_required"] is True
    assert result["slide_text_pass"] is False and result["pass"] is False


def test_skip_ocr_passes_slide_predicate_but_preserves_real_counts_and_timeline():
    result = scene_coverage([10 * i + 5 for i in range(10)], [(0, 100)], 100, bins=10,
                            slide_frames_total=3, slide_frames_with_text=0,
                            visual_required=True, ocr_required=False)
    assert result["visual_required"] is True and result["ocr_required"] is False
    assert result["timeline_pass"] is True and result["slide_text_pass"] is True and result["pass"] is True
    assert result["slide_frames_total"] == 3 and result["slide_frames_with_text"] == 0
    stalled = scene_coverage([60], [(0, 100)], 100, bins=10, slide_frames_total=1, slide_frames_with_text=0,
                             visual_required=True, ocr_required=False)
    assert stalled["timeline_pass"] is False and stalled["slide_text_pass"] is True and stalled["pass"] is False


def test_audio_source_visual_and_ocr_checks_are_explicitly_not_applicable():
    result = scene_coverage([], [(0, 100)], 0.0, visual_required=False, ocr_required=False)
    assert result["visual_required"] is False and result["ocr_required"] is False
    assert result["timeline_pass"] is True and result["slide_text_pass"] is True and result["pass"] is True
    assert result["duration_valid"] is False
    assert result["uncovered_speech_bins"] == []


def test_artifact_check(tmp_path: Path):
    transcript = tmp_path / "transcript.md"
    notes = tmp_path / "notes.md"
    transcript.write_text("content", encoding="utf-8")
    assert artifact_check(str(transcript), str(notes))["pass"] is False
    notes.write_text("content", encoding="utf-8")
    assert artifact_check(str(transcript), str(notes))["pass"] is True


def test_build_coverage_schema_and_write(tmp_path: Path):
    video = {"title": "L", "duration_sec": 300.0, "speech_source": "stt",
             "input_source": {"kind": "local_video", "argument": "x.mp4", "has_video": True,
                               "citation": {"kind": "transcript"}}}
    segments = [{"t": 2.0, "text": "핵심 설명"}]
    synthesis_input = build_synthesis_input(video, segments, [])
    transcript = render_transcript_md(video, segments)
    notes = render_notes_md(synthesis_input, {
        "duration_sec": 300.0,
        "gap_check": {"max_untranscribed_speech_gap_sec": 0, "threshold_sec": 60, "pass": True},
        "scene_coverage": {"speech_bins": [], "uncovered_speech_bins": [], "pass": True,
                           "visual_required": True, "ocr_required": True,
                           "slide_frames_with_text": 0, "slide_frames_total": 0},
        "artifacts": {"transcript_nonempty": True, "notes_nonempty": True},
        "ocr_engine": "none",
    })
    coverage = build_coverage(_passing_inputs(tmp_path, notes_text=notes, transcript_text=transcript))
    assert coverage["schema_version"] == 2
    assert coverage["scene_coverage"]["visual_required"] is True
    assert coverage["overall_pass"] is True
    out = write_coverage(coverage, str(tmp_path / "coverage.json"))
    assert json.loads(Path(out).read_text(encoding="utf-8"))["schema_version"] == 2


def test_coverage_inputs_routes_applicability_and_actual_counts(tmp_path: Path):
    transcript = tmp_path / "transcript.md"; transcript.write_text("x", encoding="utf-8")
    notes = tmp_path / "notes.md"; notes.write_text("y", encoding="utf-8")
    slides = [
        {"t": 0.0, "frame": "frames/0.png", "ocr_text": "Slide A"},
        {"t": 300.0, "frame": "frames/1.png", "ocr_text": ""},
    ]
    inputs = coverage_inputs_from_extraction(
        video_title="L", duration_sec=600.0, speech_spans=[(0, 600)], segment_times=[10 * i for i in range(60)],
        raw_sample_times=[float(i) for i in range(600)], slides=slides,
        transcript_path=str(transcript), notes_path=str(notes), ocr_engine="skipped",
        visual_required=True, ocr_required=False,
    )
    coverage = build_coverage(inputs)
    assert inputs.slide_frames_total == 2 and inputs.slide_frames_with_text == 1
    assert coverage["scene_coverage"]["slide_text_pass"] is True
    assert coverage["overall_pass"] is True


def test_independent_speech_and_artifact_failures_remain_mandatory(tmp_path: Path):
    inputs = _passing_inputs(tmp_path, visual_required=False, ocr_required=False)
    inputs.speech_spans = [(0, 300)]
    inputs.segment_times = [0, 30]
    coverage = build_coverage(inputs)
    assert coverage["scene_coverage"]["pass"] is True
    assert coverage["gap_check"]["pass"] is False
    assert coverage["overall_pass"] is False
