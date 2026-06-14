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
from lectural.notes_contract import hook_contract_problems
from lectural.synthesis import (
    NOTES_CONCEPTS_ANCHOR,
    NOTES_COVERAGE_ANCHOR,
    NOTES_DETAIL_ANCHOR,
    NOTES_FLOW_ANCHOR,
    NOTES_QUESTIONS_ANCHOR,
    NOTES_TAKEAWAY_ANCHOR,
    NOTES_TOC_ANCHOR,
    NOTES_UNENRICHED_MARKER,
    build_synthesis_input,
    render_notes_md,
    render_transcript_md,
)


def _rendered_notes_and_transcript() -> tuple[str, str]:
    video = {
        "title": "L",
        "source": "https://youtu.be/abc12345678",
        "video_id": "abc12345678",
        "duration_sec": 300.0,
    }
    segments = [{"t": 2.0, "text": "핵심 설명"}]
    coverage = {
        "duration_sec": 300.0,
        "gap_check": {"max_untranscribed_speech_gap_sec": 0, "threshold_sec": 60, "pass": True},
        "scene_coverage": {"speech_bins": [0], "uncovered_speech_bins": [], "pass": True,
                           "slide_frames_with_text": 0, "slide_frames_total": 0},
        "artifacts": {"transcript_nonempty": True, "notes_nonempty": True},
        "ocr_engine": "none",
    }
    synthesis_input = build_synthesis_input(video, segments, [])
    return render_notes_md(synthesis_input, coverage), render_transcript_md(video, segments)


def _passing_inputs(tmp_path, *, notes_text: str | None = None, transcript_text: str | None = None) -> CoverageInputs:
    return CoverageInputs(
        video_title="L",
        duration_sec=300.0,
        speech_spans=[(0, 300)],
        segment_times=[30 * i for i in range(10)],
        frame_times=[float(i) for i in range(0, 300)],
        transcript_path=str(tmp_path / "transcript.md"),
        notes_path=str(tmp_path / "notes.md"),
        ocr_engine="paddleocr",
        slide_frames_total=1,
        slide_frames_with_text=1,
        transcript_text=transcript_text,
        notes_text=notes_text,
    )


def _replace_section_body(text: str, anchor: str, next_anchor: str, lines: list[str]) -> str:
    body_start = text.index("\n", text.index(anchor)) + 1
    body_end = text.index(next_anchor, body_start)
    return text[:body_start] + "\n".join(lines).rstrip() + "\n\n" + text[body_end:]


def _layer2_enriched_notes(notes_text: str) -> str:
    notes = "\n".join(line for line in notes_text.splitlines() if line != NOTES_UNENRICHED_MARKER) + "\n"
    notes = _replace_section_body(
        notes,
        NOTES_TAKEAWAY_ANCHOR,
        NOTES_TOC_ANCHOR,
        ["- 요약 1", "- 요약 2", "- 요약 3"],
    )
    notes = _replace_section_body(
        notes,
        NOTES_FLOW_ANCHOR,
        NOTES_CONCEPTS_ANCHOR,
        ["- 흐름 1", "- 흐름 2"],
    )
    notes = _replace_section_body(
        notes,
        NOTES_CONCEPTS_ANCHOR,
        NOTES_DETAIL_ANCHOR,
        ["- **핵심 설명**: 핵심 정의. ([영상 0:02](https://youtu.be/abc12345678?t=2))"],
    )
    notes = _replace_section_body(
        notes,
        NOTES_QUESTIONS_ANCHOR,
        NOTES_COVERAGE_ANCHOR,
        [
            "**Q1. 핵심은 무엇인가요?**",
            "",
            "<details>",
            "<summary>답 보기</summary>",
            "",
            "핵심 설명입니다. ([영상 0:02](https://youtu.be/abc12345678?t=2))",
            "",
            "</details>",
            "",
            "**Q2. 근거는 어디인가요?**",
            "",
            "<details>",
            "<summary>답 보기</summary>",
            "",
            "전사 발화입니다. ([영상 0:02](https://youtu.be/abc12345678?t=2))",
            "",
            "</details>",
            "",
            "**Q3. 언제 나오나요?**",
            "",
            "<details>",
            "<summary>답 보기</summary>",
            "",
            "2초 지점입니다. ([영상 0:02](https://youtu.be/abc12345678?t=2))",
            "",
            "</details>",
        ],
    )
    return notes



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
    n = tmp_path / "notes.md"
    t.write_text("content", encoding="utf-8")
    res_missing = artifact_check(str(t), str(n))
    assert res_missing["pass"] is False  # notes missing
    n.write_text("content", encoding="utf-8")
    res_ok = artifact_check(str(t), str(n))
    assert res_ok["pass"] is True

def test_artifact_check_judges_nonempty_from_rendered_text(tmp_path):
    # Decouples the gate from file write ordering: rendered content passes even
    # when the notes file has not been written yet (the real-run regression).
    t = tmp_path / "transcript.md"
    n = tmp_path / "notes.md"  # intentionally never written
    res = artifact_check(
        str(t), str(n),
        transcript_text="[00:00:00] hi", notes_text="# notes\nbody",
    )
    assert res["transcript_nonempty"] is True
    assert res["notes_nonempty"] is True
    assert res["pass"] is True
    # Empty rendered text is still caught.
    empty = artifact_check(str(t), str(n), transcript_text="x", notes_text="   ")
    assert empty["notes_nonempty"] is False
    assert empty["pass"] is False


def test_build_coverage_passes_with_rendered_text_before_files_exist(tmp_path):
    notes_text, transcript_text = _rendered_notes_and_transcript()
    inp = _passing_inputs(tmp_path, notes_text=notes_text, transcript_text=transcript_text)
    cov = build_coverage(inp)
    assert cov["artifacts"]["notes_nonempty"] is True
    assert cov["notes_contract"] == {"version": 1, "checked": True, "problems": [], "pass": True}
    assert cov["overall_pass"] is True


def test_bare_skeleton_notes_contract_is_marker_agnostic(tmp_path):
    notes_text, transcript_text = _rendered_notes_and_transcript()
    assert "<!-- 미보강 -->" in notes_text
    cov = build_coverage(_passing_inputs(tmp_path, notes_text=notes_text, transcript_text=transcript_text))
    assert cov["notes_contract"]["pass"] is True
    assert cov["overall_pass"] is True


def test_layer1_coverage_ignores_dangling_or_non_youtube_citation_text(tmp_path):
    notes_text, transcript_text = _rendered_notes_and_transcript()
    broken = notes_text.replace("- 미보강: 핵심 용어", "- 미보강: [깨진 전사](transcript.md#t999999) 핵심 용어", 1)
    cov = build_coverage(_passing_inputs(tmp_path, notes_text=broken, transcript_text=transcript_text))

    assert cov["notes_contract"]["pass"] is True
    assert cov["notes_contract"]["problems"] == []
    assert cov["overall_pass"] is True


def test_layer2_hook_rejects_youtube_seconds_mismatch():
    notes_text, transcript_text = _rendered_notes_and_transcript()
    enriched = _layer2_enriched_notes(notes_text)
    broken = enriched.replace("https://youtu.be/abc12345678?t=2", "https://youtu.be/abc12345678?t=10", 1)

    problems = hook_contract_problems(broken, transcript_text, has_frames=False)

    assert any("1초 넘게 다릅니다" in p for p in problems)


def test_build_and_write_coverage(tmp_path):
    t = tmp_path / "transcript.md"
    n = tmp_path / "notes.md"
    t.write_text("x", encoding="utf-8")
    n.write_text("y", encoding="utf-8")
    inp = CoverageInputs(
        video_title="Lecture 1",
        duration_sec=100.0,
        speech_spans=[(0, 100)],
        segment_times=[5 * i for i in range(20)],
        frame_times=[5 * i + 2 for i in range(20)],
        transcript_path=str(t),
        notes_path=str(n),
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
    np = tmp_path / "notes.md"; np.write_text("y", encoding="utf-8")
    raw = [float(i) for i in range(0, 600)]  # dense raw samples
    slides = [
        {"t": 0.0, "frame": "frames/0.png", "ocr_text": "Slide A"},
        {"t": 300.0, "frame": "frames/1.png", "ocr_text": ""},  # no text
    ]
    inp = coverage_inputs_from_extraction(
        video_title="L", duration_sec=600.0, speech_spans=[(0, 600)],
        segment_times=[10 * i for i in range(60)], raw_sample_times=raw,
        slides=slides, transcript_path=str(tp), notes_path=str(np),
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
