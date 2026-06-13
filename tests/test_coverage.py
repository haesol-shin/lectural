"""Unit tests for coverage.json computation (AC-13). Pure, offline."""

import json
import os

from lectural.config import MAX_GAP_SEC
from lectural.coverage import (
    CoverageInputs,
    artifact_check,
    build_coverage,
    gap_check,
    scene_coverage,
    write_coverage,
)


def test_gap_check_pass_and_fail():
    speech = [(0, 300)]
    good = gap_check(speech, [0, 30, 60, 90, 120, 150, 180, 210, 240, 270], 300)
    assert good["pass"] is True
    bad = gap_check(speech, [0, 50, 100], 300)  # long tail untranscribed
    assert bad["pass"] is False
    assert bad["max_untranscribed_speech_gap_sec"] > MAX_GAP_SEC


def test_scene_coverage_uncovered_speech_bin_fails():
    # First keyframe only appears at 150s while speech starts at 0 -> the
    # pre-keyframe bins (speech the visual pass never reached) are uncovered.
    res = scene_coverage([150.0], [(0, 200)], duration=200, bins=10,
                         slide_frames_total=1, slide_frames_with_text=1)
    assert res["pass"] is False
    assert res["uncovered_speech_bins"]


def test_scene_coverage_pass_when_every_speech_bin_has_frame():
    frames = [10 * i + 5 for i in range(10)]  # one per bin (bins=10, dur=100)
    res = scene_coverage(frames, [(0, 100)], duration=100, bins=10,
                         slide_frames_total=3, slide_frames_with_text=3)
    assert res["pass"] is True
    assert res["uncovered_speech_bins"] == []


def test_scene_coverage_fails_when_slide_lacks_text():
    frames = [10 * i + 5 for i in range(10)]
    res = scene_coverage(frames, [(0, 100)], duration=100, bins=10,
                         slide_frames_total=3, slide_frames_with_text=2)
    assert res["pass"] is False  # a slide frame missing OCR text


def test_artifact_check(tmp_path):
    t = tmp_path / "transcript.md"
    s = tmp_path / "summary.md"
    t.write_text("content", encoding="utf-8")
    res_missing = artifact_check(str(t), str(s))
    assert res_missing["pass"] is False  # summary missing
    s.write_text("content", encoding="utf-8")
    res_ok = artifact_check(str(t), str(s))
    assert res_ok["pass"] is True

def test_artifact_check_judges_nonempty_from_rendered_text(tmp_path):
    # Decouples the gate from file write ordering: rendered content passes even
    # when the summary file has not been written yet (the real-run regression).
    t = tmp_path / "transcript.md"
    s = tmp_path / "summary.md"  # intentionally never written
    res = artifact_check(
        str(t), str(s),
        transcript_text="[00:00:00] hi", summary_text="# notes\nbody",
    )
    assert res["transcript_nonempty"] is True
    assert res["summary_nonempty"] is True
    assert res["pass"] is True
    # Empty rendered text is still caught.
    empty = artifact_check(str(t), str(s), transcript_text="x", summary_text="   ")
    assert empty["summary_nonempty"] is False
    assert empty["pass"] is False


def test_build_coverage_passes_with_rendered_text_before_files_exist(tmp_path):
    inp = CoverageInputs(
        video_title="L", duration_sec=300.0, speech_spans=[(0, 300)],
        segment_times=[30 * i for i in range(10)],
        frame_times=[float(i) for i in range(0, 300)],
        transcript_path=str(tmp_path / "transcript.md"),
        summary_path=str(tmp_path / "summary.md"),  # not written
        ocr_engine="paddleocr", slide_frames_total=1, slide_frames_with_text=1,
        transcript_text="[00:00:00] hi", summary_text="# notes",
    )
    cov = build_coverage(inp)
    assert cov["artifacts"]["summary_nonempty"] is True
    assert cov["overall_pass"] is True


def test_build_and_write_coverage(tmp_path):
    t = tmp_path / "transcript.md"
    s = tmp_path / "summary.md"
    t.write_text("x", encoding="utf-8")
    s.write_text("y", encoding="utf-8")
    inp = CoverageInputs(
        video_title="Lecture 1",
        duration_sec=100.0,
        speech_spans=[(0, 100)],
        segment_times=[5 * i for i in range(20)],
        frame_times=[5 * i + 2 for i in range(20)],
        transcript_path=str(t),
        summary_path=str(s),
        ocr_engine="paddleocr",
        slide_frames_total=2,
        slide_frames_with_text=2,
    )
    cov = build_coverage(inp)
    assert cov["overall_pass"] is True
    assert cov["ocr_engine"] == "paddleocr"
    out = write_coverage(cov, str(tmp_path / "coverage.json"))
    assert os.path.isfile(out)
    reloaded = json.loads((tmp_path / "coverage.json").read_text(encoding="utf-8"))
    assert reloaded["schema_version"] == 1


def test_scene_coverage_mid_video_stall_detected_by_carry_cap():
    # Dense samples then a long stall (no keyframe) in the middle -> FAIL.
    frames = [float(i) for i in range(0, 100)] + [590.0, 595.0]
    res = scene_coverage(frames, [(0, 600)], duration=600, bins=20,
                         slide_frames_total=2, slide_frames_with_text=2,
                         carry_max_sec=120.0)
    assert res["pass"] is False
    assert res["uncovered_speech_bins"]


def test_scene_coverage_static_slide_passes_with_dense_raw_samples():
    # One static slide for the whole 600s, but raw sampling kept dense frames.
    frames = [float(i) for i in range(0, 600, 1)]
    res = scene_coverage(frames, [(0, 600)], duration=600, bins=20,
                         slide_frames_total=1, slide_frames_with_text=1,
                         carry_max_sec=120.0)
    assert res["pass"] is True
    assert res["uncovered_speech_bins"] == []


def test_coverage_inputs_from_extraction_routes_raw_times_and_counts(tmp_path):
    from lectural.coverage import coverage_inputs_from_extraction, build_coverage
    tp = tmp_path / "transcript.md"; tp.write_text("x", encoding="utf-8")
    sp = tmp_path / "summary.md"; sp.write_text("y", encoding="utf-8")
    raw = [float(i) for i in range(0, 600)]  # dense raw samples
    slides = [
        {"t": 0.0, "frame": "frames/0.png", "ocr_text": "Slide A"},
        {"t": 300.0, "frame": "frames/1.png", "ocr_text": ""},  # no text
    ]
    inp = coverage_inputs_from_extraction(
        video_title="L", duration_sec=600.0, speech_spans=[(0, 600)],
        segment_times=[10 * i for i in range(60)], raw_sample_times=raw,
        slides=slides, transcript_path=str(tp), summary_path=str(sp),
        ocr_engine="paddleocr",
    )
    # raw sample times are routed to frame_times (not the 2 slides)
    assert inp.frame_times == raw
    assert inp.raw_frame_times == raw
    assert inp.slide_frames_total == 2
    assert inp.slide_frames_with_text == 1  # one slide had empty ocr_text
    cov = build_coverage(inp)
    # dense raw samples -> scene coverage covered; but a slide lacks text -> fail
    assert cov["scene_coverage"]["uncovered_speech_bins"] == []
    assert cov["overall_pass"] is False  # slide-text gate fails
