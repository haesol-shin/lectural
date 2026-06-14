"""Adversarial WU-2 QA for notes.md-only deterministic synthesis."""

from __future__ import annotations

import json
import re
import os
import subprocess
import sys
from pathlib import Path

from lectural.coverage import CoverageInputs, build_coverage, coverage_inputs_from_extraction
from lectural.synthesis import (
    ANCHOR_ID_PATTERN,
    NOTES_CONCEPTS_ANCHOR,
    NOTES_COVERAGE_ANCHOR,
    NOTES_DETAIL_ANCHOR,
    NOTES_ENRICH_MARKER,
    NOTES_FLOW_ANCHOR,
    NOTES_QUESTIONS_ANCHOR,
    NOTES_TAKEAWAY_ANCHOR,
    NOTES_TOC_ANCHOR,
    NOTES_UNENRICHED_MARKER,
    build_synthesis_input,
    build_transcript_anchor_ids,
    render_notes_md,
    render_transcript_md,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "scripts" / "completeness_hook.py"
VIDEO_ID = "WU2VID00001"
LEGACY_NOTES_MARKERS = (
    "<!-- lectural:baseline -->",
    "## 핵심 요약",
    "## 구간별 요약",
    "## TO-ENRICH",
    "## 커버리지 요약",
)


def _coverage_payload(overall_pass: bool = True) -> dict:
    return {
        "schema_version": 1,
        "video_title": "WU-2 smoke",
        "duration_sec": 240.0,
        "ocr_engine": "none",
        "gap_check": {
            "max_untranscribed_speech_gap_sec": 0 if overall_pass else 90,
            "threshold_sec": 60,
            "pass": overall_pass,
        },
        "scene_coverage": {
            "speech_bins": [0],
            "covered_speech_bins": [0] if overall_pass else [],
            "uncovered_speech_bins": [] if overall_pass else [0],
            "slide_frames_total": 1,
            "slide_frames_with_text": 1 if overall_pass else 0,
            "pass": overall_pass,
        },
        "artifacts": {
            "transcript_md": "transcript.md",
            "notes_md": "notes.md",
            "transcript_nonempty": overall_pass,
            "notes_nonempty": overall_pass,
            "pass": overall_pass,
        },
        "overall_pass": overall_pass,
    }


def _fixture(*, video_id: str | None = VIDEO_ID, url: str | None = None) -> tuple[dict, list[dict], list[dict], dict]:
    video = {
        "title": "WU-2 [Red|Team] 강의",
        "duration_sec": 240.0,
        "source": "caption",
    }
    if video_id is not None:
        video["video_id"] = video_id
    if url is not None:
        video["url"] = url
    segments = [
        {"t": 65.0, "text": "동일 타임스탬프 첫 번째 개념"},
        {"t": 65.0, "text": "동일 타임스탬프 두 번째 세부"},
        {"t": 65.0, "text": "동일 타임스탬프 세 번째 질문 후보"},
        {"t": 130.0, "text": "후반부 비교 설명"},
    ]
    slides = [
        {"t": 0.0, "frame": "frames/slide-001.png", "ocr_text": "Opening [A|B]", "is_slide": True},
        {"t": 90.0, "frame": "frames/slide-002.png", "ocr_text": "Empty [Slide|Only]", "is_slide": True},
        {"t": 120.0, "frame": "frames/slide-003.png", "ocr_text": "Later [C|D]", "is_slide": True},
    ]
    return video, segments, slides, _coverage_payload(True)


def _render_notes_and_transcript(
    *, video_id: str | None = VIDEO_ID, url: str | None = None, segments: list[dict] | None = None, slides: list[dict] | None = None
) -> tuple[str, str, dict, list[dict], list[dict]]:
    video, default_segments, default_slides, coverage = _fixture(video_id=video_id, url=url)
    if segments is None:
        segments = default_segments
    if slides is None:
        slides = default_slides
    synthesis_input = build_synthesis_input(video, segments, slides)
    return render_notes_md(synthesis_input, coverage), render_transcript_md(video, segments), video, segments, slides
def _replace_section_body(text: str, anchor: str, next_anchor: str, lines: list[str]) -> str:
    body_start = text.index("\n", text.index(anchor)) + 1
    body_end = text.index(next_anchor, body_start)
    return text[:body_start] + "\n".join(lines).rstrip() + "\n\n" + text[body_end:]


def _enrich(notes_md: str) -> str:
    notes = "\n".join(
        line for line in notes_md.splitlines() if line.strip() != NOTES_UNENRICHED_MARKER
    ) + "\n"
    notes = _replace_section_body(
        notes,
        NOTES_TAKEAWAY_ANCHOR,
        NOTES_TOC_ANCHOR,
        [
            "강의는 자동 생성된 전사와 슬라이드 근거를 바탕으로 핵심 흐름을 정리한다.",
            "학습자는 각 개념의 출처를 전사 링크와 영상 시간으로 되짚을 수 있다.",
            "상세 노트는 슬라이드별 설명을 보강해 복습 가능한 기록으로 완성한다.",
        ],
    )
    return _replace_section_body(
        notes,
        NOTES_FLOW_ANCHOR,
        NOTES_CONCEPTS_ANCHOR,
        [
            "- 도입부에서 강의의 문제의식과 확인할 자료를 제시한다.",
            "- 본문에서는 전사 근거를 따라 개념과 예시를 순서대로 연결한다.",
        ],
    )


def _hook_fixture_texts() -> tuple[str, str]:
    video = {"title": "WU-2 hook smoke", "duration_sec": 60.0, "video_id": VIDEO_ID, "source": "caption"}
    segments = [{"t": 2.0, "text": "hook smoke utterance"}]
    slides = [{"t": 0.0, "frame": "frames/slide-001.png", "ocr_text": "Hook slide", "is_slide": True}]
    synthesis_input = build_synthesis_input(video, segments, slides)
    return render_notes_md(synthesis_input, _coverage_payload(True)), render_transcript_md(video, segments)




def _block(md: str, start: str, end: str | None = None) -> str:
    start_index = md.index(start)
    end_index = md.index(end, start_index + len(start)) if end else len(md)
    return md[start_index:end_index]


def _bullet_lines(block: str) -> list[str]:
    return [line for line in block.splitlines() if line.startswith("- ")]


def _anchor_seconds(anchor_id: str) -> int:
    hh, mm, ss = anchor_id[1:3], anchor_id[3:5], anchor_id[5:7]
    return int(hh) * 3600 + int(mm) * 60 + int(ss)


def _all_keys(value) -> list[str]:
    if isinstance(value, dict):
        keys = list(value)
        for child in value.values():
            keys.extend(_all_keys(child))
        return keys
    if isinstance(value, list):
        keys: list[str] = []
        for child in value:
            keys.extend(_all_keys(child))
        return keys
    return []


def test_anchor_uniqueness_pattern_and_notes_deeplinks_are_grounded_in_transcript():
    notes_md, transcript_md, _video, segments, _slides = _render_notes_and_transcript()

    anchor_ids = build_transcript_anchor_ids(segments)
    assert anchor_ids[:3] == ["t000105", "t000105-2", "t000105-3"]
    assert len(anchor_ids) == len(set(anchor_ids))
    assert all(re.fullmatch(ANCHOR_ID_PATTERN, anchor_id) for anchor_id in anchor_ids)

    transcript_ids = set(re.findall(r'<a id="(t\d{6}(?:-\d+)?)"></a>', transcript_md))
    referenced_ids = set(re.findall(r"transcript\.md#(t\d{6}(?:-\d+)?)", notes_md))
    assert referenced_ids
    assert referenced_ids <= transcript_ids


def test_citation_correctness_and_narrative_sections_are_citation_exempt():
    notes_md, _transcript_md, _video, _segments, _slides = _render_notes_and_transcript()

    cited_blocks = [
        _block(notes_md, NOTES_CONCEPTS_ANCHOR, NOTES_DETAIL_ANCHOR),
        _block(notes_md, NOTES_DETAIL_ANCHOR, NOTES_QUESTIONS_ANCHOR),
        _block(notes_md, NOTES_QUESTIONS_ANCHOR, NOTES_COVERAGE_ANCHOR),
    ]
    for block in cited_blocks:
        for line in _bullet_lines(block):
            anchor = re.search(r"transcript\.md#(t\d{6}(?:-\d+)?)", line)
            video = re.search(rf"youtu\.be/{VIDEO_ID}\?t=(\d+)", line)
            assert anchor, line
            assert video, line
            assert int(video.group(1)) == _anchor_seconds(anchor.group(1))

    narrative_blocks = [
        _block(notes_md, NOTES_TAKEAWAY_ANCHOR, NOTES_TOC_ANCHOR),
        _block(notes_md, NOTES_TOC_ANCHOR, NOTES_FLOW_ANCHOR),
        _block(notes_md, NOTES_FLOW_ANCHOR, NOTES_CONCEPTS_ANCHOR),
    ]
    for block in narrative_blocks:
        assert "transcript.md#" not in block
        assert "youtu.be/" not in block


def test_narrative_sections_are_marker_and_placeholder_only_with_no_legacy_markers():
    notes_md, _transcript_md, _video, _segments, _slides = _render_notes_and_transcript()

    for start, end in (
        (NOTES_TAKEAWAY_ANCHOR, NOTES_TOC_ANCHOR),
        (NOTES_FLOW_ANCHOR, NOTES_CONCEPTS_ANCHOR),
    ):
        block = _block(notes_md, start, end)
        content_lines = [line for line in block.splitlines()[1:] if line.strip()]
        assert content_lines[0] == NOTES_UNENRICHED_MARKER
        assert all(line.startswith("- 미보강") for line in content_lines[1:])

    for legacy in LEGACY_NOTES_MARKERS:
        assert legacy not in notes_md


def test_boundary_empty_zero_missing_video_id_past_duration_and_markdown_special_titles():
    no_video_notes, _transcript_md, _video, _segments, _slides = _render_notes_and_transcript(video_id=None, url=None)
    cited_lines = _bullet_lines(_block(no_video_notes, NOTES_CONCEPTS_ANCHOR, NOTES_DETAIL_ANCHOR))
    assert cited_lines
    assert all("transcript.md#" in line for line in cited_lines)
    assert all("youtu.be/" not in line for line in cited_lines)

    empty_notes, empty_transcript, _video, _segments, _slides = _render_notes_and_transcript(segments=[], slides=[])
    assert "<a id=" not in empty_transcript
    assert "transcript.md#" not in _block(empty_notes, NOTES_QUESTIONS_ANCHOR, NOTES_COVERAGE_ANCHOR)
    assert "youtu.be/" not in _block(empty_notes, NOTES_QUESTIONS_ANCHOR, NOTES_COVERAGE_ANCHOR)

    notes_md, _transcript_md, _video, _segments, _slides = _render_notes_and_transcript()
    detail = _block(notes_md, NOTES_DETAIL_ANCHOR, NOTES_QUESTIONS_ANCHOR)
    assert "### [00:01:30] Empty (Slide/Only)" in detail
    assert "### [00:01:30](transcript.md#" not in detail
    assert "Opening (A/B)" in notes_md
    assert "[A|B]" not in notes_md
    assert "[Slide|Only]" not in notes_md

    video = {"title": "Past duration", "duration_sec": 60.0, "video_id": VIDEO_ID, "source": "caption"}
    segments = [{"t": 130.0, "text": "duration 이후에도 캡처된 설명"}]
    slides = [{"t": 120.0, "frame": "frames/past.png", "ocr_text": "Past [Duration|Slide]", "is_slide": True}]
    past_notes = render_notes_md(build_synthesis_input(video, segments, slides), _coverage_payload(True))
    assert "duration 이후에도 캡처된 설명" in past_notes
    assert "Past (Duration/Slide)" in past_notes
    assert "transcript.md#t000210" in past_notes
    assert "youtu.be/WU2VID00001?t=130" in past_notes


def test_coverage_contract_uses_notes_only_and_overall_pass_and_folds_components():
    video = {"title": "ok", "duration_sec": 3.0, "video_id": VIDEO_ID, "source": "caption"}
    segments = [
        {"t": 0.5, "text": "첫 번째 슬라이드 개념"},
        {"t": 1.5, "text": "두 번째 슬라이드 세부"},
    ]
    slides = [
        {"t": 0.0, "frame": "frames/slide-001.png", "ocr_text": "첫 슬라이드", "is_slide": True},
        {"t": 1.0, "frame": "frames/slide-002.png", "ocr_text": "둘째 슬라이드", "is_slide": True},
    ]
    synthesis_input = build_synthesis_input(video, segments, slides)
    notes_text = render_notes_md(synthesis_input, _coverage_payload(True))
    transcript_text = render_transcript_md(video, segments)
    all_pass = CoverageInputs(
        video_title="ok",
        duration_sec=3.0,
        speech_spans=[],
        segment_times=[0.5, 1.5],
        frame_times=[],
        transcript_path="transcript.md",
        notes_path="notes.md",
        transcript_text=transcript_text,
        notes_text=notes_text,
    )
    coverage = build_coverage(all_pass)
    assert coverage["artifacts"] == {
        "transcript_md": "transcript.md",
        "notes_md": "notes.md",
        "transcript_nonempty": True,
        "notes_nonempty": True,
        "pass": True,
    }
    assert coverage["notes_contract"]["checked"] is True
    assert coverage["notes_contract"]["pass"] is True
    assert coverage["overall_pass"] is True

    artifact_fail = build_coverage(CoverageInputs(**{**all_pass.__dict__, "notes_text": ""}))
    assert artifact_fail["artifacts"]["notes_nonempty"] is False
    assert artifact_fail["overall_pass"] is False

    gap_fail = build_coverage(
        CoverageInputs(
            **{
                **all_pass.__dict__,
                "duration_sec": 120.0,
                "speech_spans": [(0.0, 120.0)],
                "segment_times": [],
                "frame_times": [0.0],
            }
        )
    )
    assert gap_fail["gap_check"]["pass"] is False
    assert gap_fail["overall_pass"] is False

    scene_fail = build_coverage(
        CoverageInputs(**{**all_pass.__dict__, "duration_sec": 10.0, "speech_spans": [(0.0, 10.0)], "segment_times": [0.0], "frame_times": []})
    )
    assert scene_fail["scene_coverage"]["pass"] is False
    assert scene_fail["overall_pass"] is False

    from_extraction = coverage_inputs_from_extraction(
        video_title="from extraction",
        duration_sec=3.0,
        speech_spans=[],
        segment_times=[0.5, 1.5],
        raw_sample_times=[],
        slides=[],
        transcript_path="transcript.md",
        notes_path="notes.md",
        transcript_text=transcript_text,
        notes_text=notes_text,
    )
    assert from_extraction.notes_path == "notes.md"
    assert from_extraction.notes_text == notes_text

    forbidden = {"summary_path", "outline_path", "summary_nonempty", "outline_nonempty"}
    assert forbidden.isdisjoint(_all_keys(coverage))
    assert forbidden.isdisjoint(_all_keys(artifact_fail))

    dangling_notes = re.sub(
        r"(transcript\.md#)t\d{6}(?:-\d+)?",
        lambda match: f"{match.group(1)}t999999",
        notes_text,
        count=1,
    )
    assert dangling_notes != notes_text
    dangling_fail = build_coverage(CoverageInputs(**{**all_pass.__dict__, "notes_text": dangling_notes}))
    assert dangling_fail["notes_contract"]["pass"] is False
    assert dangling_fail["overall_pass"] is False


def test_fresh_synthesis_import_keeps_heavy_runtime_modules_lazy():
    probe = """
import json
import sys
for name in list(sys.modules):
    if name == 'lectural' or name.startswith('lectural.') or name in {'cv2', 'numpy', 'paddleocr', 'paddle', 'PIL'}:
        sys.modules.pop(name, None)
import lectural.synthesis  # noqa: F401
print(json.dumps({name: (name in sys.modules) for name in ['cv2', 'numpy', 'paddleocr', 'paddle', 'PIL']}, sort_keys=True))
"""
    proc = subprocess.run([sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    loaded = json.loads(proc.stdout)
    assert loaded == {"PIL": False, "cv2": False, "numpy": False, "paddle": False, "paddleocr": False}


def _write_hook_case(root: Path, name: str, *, notes_text: str | None = None, frames_png: bool = False, status: str = "complete") -> dict:
    out = root / name
    out.mkdir(parents=True)
    notes_path = out / "notes.md"
    default_notes, transcript_text = _hook_fixture_texts()
    if notes_text is None:
        notes_text = _enrich(default_notes)
    notes_path.write_text(notes_text, encoding="utf-8")
    (out / "transcript.md").write_text(transcript_text, encoding="utf-8")

    coverage_path = out / "coverage.json"
    coverage_path.write_text(json.dumps(_coverage_payload(True), ensure_ascii=False), encoding="utf-8")
    if frames_png:
        frames = out / "frames"
        frames.mkdir()
        (frames / "slide-001.png").write_bytes(b"png extension is enough for hook")
    run = {"status": status, "output_dir": str(out), "coverage_json": str(coverage_path), "notes_md": str(notes_path)}
    if status == "failed":
        run["error"] = "forced failure"
    return run


def _invoke_hook(runstate_path: Path, runs: list[dict], *, malformed_runstate: bool = False) -> subprocess.CompletedProcess[str]:
    if malformed_runstate:
        runstate_path.write_text("{not valid json", encoding="utf-8")
    else:
        runstate_path.write_text(json.dumps({"tool": "lectural", "runs": runs}, ensure_ascii=False), encoding="utf-8")
    env = {**os.environ, "LECTURAL_RUNSTATE": str(runstate_path)}
    return subprocess.run([sys.executable, str(HOOK_PATH)], cwd=REPO_ROOT, input="{}", capture_output=True, text=True, env=env)


def test_completeness_hook_real_subprocess_adversarial_smoke(tmp_path):
    artifact = REPO_ROOT / "artifacts" / "wu2-hook-smoke.txt"
    artifact.parent.mkdir(exist_ok=True)
    transcript: list[str] = []

    def record(name: str, proc: subprocess.CompletedProcess[str], expected: int) -> None:
        transcript.extend(
            [
                f"## {name}",
                f"command: {sys.executable} {HOOK_PATH}",
                f"expected_exit: {expected}",
                f"actual_exit: {proc.returncode}",
                "stdout:",
                proc.stdout.rstrip(),
                "stderr:",
                proc.stderr.rstrip(),
                "",
            ]
        )
        assert proc.returncode == expected

    try:
        valid_run = _write_hook_case(tmp_path, "valid", frames_png=True)
        record("complete-valid-notes", _invoke_hook(tmp_path / "valid-runstate.json", [valid_run]), 0)

        missing_marker_text = (Path(valid_run["notes_md"]).read_text(encoding="utf-8").replace(f"{NOTES_ENRICH_MARKER}\n", "", 1))
        missing_marker_run = _write_hook_case(tmp_path, "missing-marker", notes_text=missing_marker_text)
        record("missing-notes-marker-line-one", _invoke_hook(tmp_path / "missing-marker-runstate.json", [missing_marker_run]), 2)

        missing_anchor_text = Path(valid_run["notes_md"]).read_text(encoding="utf-8").replace(NOTES_QUESTIONS_ANCHOR, "## 빠진 복습 질문", 1)
        missing_anchor_run = _write_hook_case(tmp_path, "missing-anchor", notes_text=missing_anchor_text)
        record("missing-required-section-anchor", _invoke_hook(tmp_path / "missing-anchor-runstate.json", [missing_anchor_run]), 2)

        failed_run = _write_hook_case(tmp_path, "failed-run", status="failed")
        record("failed-runstate-run", _invoke_hook(tmp_path / "failed-runstate.json", [failed_run]), 2)

        pending_run = _write_hook_case(tmp_path, "pending-run", status="pending")
        record("pending-runstate-run", _invoke_hook(tmp_path / "pending-runstate.json", [pending_run]), 2)

        record("malformed-runstate-fails-closed", _invoke_hook(tmp_path / "malformed-runstate.json", [], malformed_runstate=True), 2)

        no_frame_link_text = re.sub(r"\n!\[[^\n]*\]\(frames/slide-001\.png\)", "", Path(valid_run["notes_md"]).read_text(encoding="utf-8"))
        no_frame_link_run = _write_hook_case(tmp_path, "frames-without-link", notes_text=no_frame_link_text, frames_png=True)
        record("frames-present-without-slide-link", _invoke_hook(tmp_path / "frames-no-link-runstate.json", [no_frame_link_run]), 2)
        bare_skeleton_text, _ = _hook_fixture_texts()
        bare_skeleton_run = _write_hook_case(tmp_path, "bare-skeleton", notes_text=bare_skeleton_text)
        record("bare-unenriched-skeleton", _invoke_hook(tmp_path / "bare-skeleton-runstate.json", [bare_skeleton_run]), 2)
    finally:
        artifact.write_text("\n".join(transcript), encoding="utf-8")
