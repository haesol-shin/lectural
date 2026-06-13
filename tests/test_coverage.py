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
    # Speech across whole 200s, but a keyframe only in the first bin.
    res = scene_coverage([5.0], [(0, 200)], duration=200, bins=10,
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
