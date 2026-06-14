"""WU-4 adversarial QA for the two-layer notes.md contract gate."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from lectural.coverage import CoverageInputs, build_coverage
from lectural.notes_contract import (
    anchor_seconds,
    coverage_contract_problems,
    enrichment_problems,
    hook_contract_problems,
    slide_detail_problems,
)
from lectural.synthesis import (
    NOTES_CONCEPTS_ANCHOR,
    NOTES_COVERAGE_ANCHOR,
    NOTES_DETAIL_ANCHOR,
    NOTES_ENRICH_MARKER,
    NOTES_FLOW_ANCHOR,
    NOTES_INTRO_MARKER,
    NOTES_QUESTIONS_ANCHOR,
    NOTES_TAKEAWAY_ANCHOR,
    NOTES_TOC_ANCHOR,
    NOTES_UNENRICHED_MARKER,
    build_synthesis_input,
    render_notes_md,
    render_transcript_md,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HOOK_PATH = _REPO_ROOT / "scripts" / "completeness_hook.py"
_ARTIFACTS = _REPO_ROOT / "artifacts"


def _video() -> dict:
    return {
        "title": "WU4 contract fixture",
        "source": "https://youtu.be/abc12345678",
        "video_id": "abc12345678",
        "duration_sec": 130.0,
    }


def _segments() -> list[dict]:
    return [
        {"t": 5.0, "text": "도입에서 전체 문제를 제시합니다."},
        {"t": 65.0, "text": "핵심 개념을 근거와 함께 설명합니다."},
        {"t": 65.0, "text": "같은 초에 나온 보충 설명입니다."},
    ]


def _slides() -> list[dict]:
    return [
        {"t": 0.0, "frame": "frames/slide-001.png", "ocr_text": "도입 슬라이드"},
        {"t": 60.0, "frame": "frames/slide-002.png", "ocr_text": "핵심 슬라이드"},
    ]


def _footer_coverage() -> dict:
    return {
        "duration_sec": 130.0,
        "gap_check": {"max_untranscribed_speech_gap_sec": 0, "threshold_sec": 60, "pass": True},
        "scene_coverage": {
            "speech_bins": [],
            "uncovered_speech_bins": [],
            "pass": True,
            "slide_frames_with_text": 2,
            "slide_frames_total": 2,
        },
        "artifacts": {"transcript_nonempty": True, "notes_nonempty": True},
        "ocr_engine": "none",
    }


def _fixture_texts() -> tuple[str, str]:
    video = _video()
    segments = _segments()
    synthesis_input = build_synthesis_input(video, segments, _slides())
    return render_notes_md(synthesis_input, _footer_coverage()), render_transcript_md(video, segments)


def _coverage_for(notes_text: str, transcript_text: str) -> dict:
    return build_coverage(
        CoverageInputs(
            video_title="WU4 contract fixture",
            duration_sec=130.0,
            speech_spans=[],
            segment_times=[s["t"] for s in _segments()],
            frame_times=[0.0, 30.0, 60.0, 90.0, 120.0],
            transcript_path="transcript.md",
            notes_path="notes.md",
            ocr_engine="none",
            slide_frames_total=2,
            slide_frames_with_text=2,
            transcript_text=transcript_text,
            notes_text=notes_text,
        )
    )


def _replace_section_body(text: str, anchor: str, next_anchor: str, lines: list[str]) -> str:
    body_start = text.index("\n", text.index(anchor)) + 1
    body_end = text.index(next_anchor, body_start)
    return text[:body_start] + "\n".join(lines).rstrip() + "\n\n" + text[body_end:]


def _remove_marker_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if line != NOTES_UNENRICHED_MARKER) + "\n"

def _fixture_texts_with_slides(slides: list[dict]) -> tuple[str, str]:
    video = _video()
    segments = _segments()
    synthesis_input = build_synthesis_input(video, segments, slides)
    return render_notes_md(synthesis_input, _footer_coverage()), render_transcript_md(video, segments)


def _remove_image_from_detail_heading(notes: str, heading_text: str) -> str:
    lines: list[str] = []
    in_detail = False
    in_target_heading = False
    removed = False
    for line in notes.splitlines():
        if line == NOTES_DETAIL_ANCHOR:
            in_detail = True
            in_target_heading = False
        elif line.startswith("## ") and line != NOTES_DETAIL_ANCHOR:
            in_detail = False
            in_target_heading = False
        elif in_detail and line.startswith("### "):
            in_target_heading = heading_text in line
        if in_target_heading and line.startswith("![") and not removed:
            removed = True
            continue
        lines.append(line)
    assert removed
    return "\n".join(lines) + "\n"


def _first_concept_bullet(notes_text: str) -> str:
    block = notes_text[notes_text.index(NOTES_CONCEPTS_ANCHOR):notes_text.index(NOTES_DETAIL_ANCHOR)]
    for line in block.splitlines():
        if line.startswith("- ") and line.strip() != NOTES_UNENRICHED_MARKER:
            return line
    raise AssertionError("concept bullet not found")


def _mutate_first_concept_bullet(notes_text: str, mutator) -> str:
    old_line = _first_concept_bullet(notes_text)
    new_line = mutator(old_line)
    assert new_line != old_line
    return notes_text.replace(old_line, new_line, 1)


def _enriched_notes(
    *,
    takeaway_lines: int = 3,
    flow_bullets: int = 2,
    keep_marker: bool = False,
    detail_bullets: bool = True,
    frame_links: bool = True,
) -> str:
    notes, _ = _fixture_texts()
    if not keep_marker:
        notes = _remove_marker_lines(notes)
    notes = _replace_section_body(
        notes,
        NOTES_TAKEAWAY_ANCHOR,
        NOTES_TOC_ANCHOR,
        [f"요약 문장 {i}" for i in range(1, takeaway_lines + 1)],
    )
    notes = _replace_section_body(
        notes,
        NOTES_FLOW_ANCHOR,
        NOTES_CONCEPTS_ANCHOR,
        [f"- 흐름 {i}: 근거를 따라 전개됩니다." for i in range(1, flow_bullets + 1)],
    )
    notes = _replace_section_body(
        notes,
        NOTES_QUESTIONS_ANCHOR,
        NOTES_COVERAGE_ANCHOR,
        [
            "- 질문 1: 도입의 핵심 문제는 무엇인가요?",
            "- 질문 2: 핵심 개념의 근거는 무엇인가요?",
            "- 질문 3: 보충 설명은 어디에 연결되나요?",
        ],
    )
    if not detail_bullets:
        lines: list[str] = []
        in_detail = False
        for line in notes.splitlines():
            if line == NOTES_DETAIL_ANCHOR:
                in_detail = True
            elif line.startswith("## ") and line != NOTES_DETAIL_ANCHOR:
                in_detail = False
            if in_detail and line.startswith("- "):
                continue
            lines.append(line)
        notes = "\n".join(lines) + "\n"
    if not frame_links:
        notes = "\n".join(line for line in notes.splitlines() if not line.startswith("![")) + "\n"
    return notes


def _write_run_dir(tmp_path: Path, name: str, notes_text: str, transcript_text: str, *, overall_pass: bool = True) -> Path:
    out = tmp_path / name
    out.mkdir()
    (out / "notes.md").write_text(notes_text, encoding="utf-8")
    (out / "transcript.md").write_text(transcript_text, encoding="utf-8")
    frames = out / "frames"
    frames.mkdir()
    (frames / "slide-001.png").write_bytes(b"png")
    (frames / "slide-002.png").write_bytes(b"png")
    coverage = _coverage_for(notes_text, transcript_text)
    if not overall_pass:
        coverage["overall_pass"] = False
        coverage["gap_check"]["pass"] = False
        coverage["gap_check"]["max_untranscribed_speech_gap_sec"] = 90
    (out / "coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _write_runstate(path: Path, runs: list[dict]) -> None:
    path.write_text(
        json.dumps({"session_id": "wu4-redteam", "tool": "lectural", "runs": runs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _complete_run(out: Path) -> dict:
    return {
        "status": "complete",
        "output_dir": str(out),
        "coverage_json": str(out / "coverage.json"),
        "notes_md": str(out / "notes.md"),
    }


def _run_hook(hook_path: Path, runstate_path: Path, *, cwd: Path | None = None, strip_pythonpath: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LECTURAL_RUNSTATE"] = str(runstate_path)
    if strip_pythonpath:
        env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(hook_path)],
        input="{}",
        text=True,
        capture_output=True,
        cwd=str(cwd or _REPO_ROOT),
        env=env,
        check=False,
    )


def _record_hook_matrix(records: list[tuple[str, subprocess.CompletedProcess[str]]]) -> None:
    _ARTIFACTS.mkdir(exist_ok=True)
    lines: list[str] = []
    for label, proc in records:
        lines.extend(
            [
                f"## {label}",
                f"exit={proc.returncode}",
                "### stdout",
                proc.stdout.rstrip() or "<empty>",
                "### stderr",
                proc.stderr.rstrip() or "<empty>",
                "",
            ]
        )
    (_ARTIFACTS / "wu4-hook-smoke.txt").write_text("\n".join(lines), encoding="utf-8")


def test_layer1_coverage_is_marker_agnostic_for_bare_skeleton():
    skeleton, transcript = _fixture_texts()

    coverage = _coverage_for(skeleton, transcript)

    assert NOTES_UNENRICHED_MARKER in skeleton
    assert coverage["overall_pass"] is True
    assert coverage["notes_contract"]["checked"] is True
    assert coverage["notes_contract"]["pass"] is True


@pytest.mark.parametrize(
    ("mutator", "problem"),
    [
        (lambda line: re.sub(r"transcript\.md#t\d{6}(?:-\d+)?", "transcript.md#t999999", line, count=1), "전사본에 없는 앵커"),
        (lambda line: re.sub(r" \(\[영상\]\(https://youtu\.be/[^)]*\)\)", "", line, count=1), "영상 시간 링크"),
    ],
)
def test_coverage_contract_rejects_dangling_anchor_and_missing_youtube(mutator, problem):
    skeleton, transcript = _fixture_texts()
    mutated = _mutate_first_concept_bullet(skeleton, mutator)

    coverage = _coverage_for(mutated, transcript)

    assert coverage["notes_contract"]["pass"] is False
    assert coverage["overall_pass"] is False
    assert any(problem in item for item in coverage["notes_contract"]["problems"])


@pytest.mark.parametrize(("offset", "passes"), [(1, True), (2, False)])
def test_youtube_seconds_tolerance_is_one_second(offset: int, passes: bool):
    skeleton, transcript = _fixture_texts()

    def shift_youtube(line: str) -> str:
        match = re.search(r"transcript\.md#(t\d{6}(?:-\d+)?)", line)
        assert match is not None
        shifted = anchor_seconds(match.group(1)) + offset
        return re.sub(r"https://youtu\.be/([^)?]+)\?t=\d+", rf"https://youtu.be/\1?t={shifted}", line, count=1)

    mutated = _mutate_first_concept_bullet(skeleton, shift_youtube)

    assert _coverage_for(mutated, transcript)["notes_contract"]["pass"] is passes


def test_anchor_seconds_decodes_duplicate_suffix_and_rendered_duplicate_citations_pass():
    skeleton, transcript = _fixture_texts()

    assert "transcript.md#t000105-2" in skeleton
    assert anchor_seconds("t000105-2") == 65
    assert coverage_contract_problems(skeleton, transcript) == []


@pytest.mark.parametrize(
    ("mutate", "problem"),
    [
        (lambda text: text.replace(NOTES_ENRICH_MARKER + "\n", "", 1), "첫 줄"),
        (lambda text: text.replace(NOTES_DETAIL_ANCHOR, "", 1), "필수 섹션"),
        (
            lambda text: text.replace(NOTES_FLOW_ANCHOR, "@@FLOW@@", 1)
            .replace(NOTES_CONCEPTS_ANCHOR, NOTES_FLOW_ANCHOR, 1)
            .replace("@@FLOW@@", NOTES_CONCEPTS_ANCHOR, 1),
            "섹션 순서",
        ),
    ],
)
def test_base_structure_failures_make_coverage_fail(mutate, problem):
    skeleton, transcript = _fixture_texts()

    coverage = _coverage_for(mutate(skeleton), transcript)

    assert coverage["notes_contract"]["pass"] is False
    assert coverage["overall_pass"] is False
    assert any(problem in item for item in coverage["notes_contract"]["problems"])


def test_hook_enrichment_rejects_remaining_unenriched_marker():
    notes, transcript = _fixture_texts()

    problems = hook_contract_problems(notes, transcript, has_frames=True)

    assert any("미보강 마커" in item for item in problems)


@pytest.mark.parametrize(("count", "passes"), [(2, False), (3, True), (4, True), (5, True), (6, False)])
def test_hook_enrichment_takeaway_requires_three_to_five_content_lines(count: int, passes: bool):
    notes = _enriched_notes(takeaway_lines=count)

    assert (enrichment_problems(notes) == []) is passes


@pytest.mark.parametrize(("count", "passes"), [(1, False), (2, True), (3, True)])
def test_hook_enrichment_flow_requires_at_least_two_bullets(count: int, passes: bool):
    notes = _enriched_notes(flow_bullets=count)

    assert (enrichment_problems(notes) == []) is passes


def test_slide_detail_rejects_heading_without_following_bullet():
    notes = _enriched_notes(detail_bullets=False)

    problems = slide_detail_problems(notes, has_frames=False)

    assert any("설명 글머리표" in item for item in problems)


def test_slide_detail_rejects_missing_frame_link_when_frames_exist():
    notes = _enriched_notes(frame_links=False)

    problems = slide_detail_problems(notes, has_frames=True)

    assert any("frames/" in item for item in problems)


@pytest.mark.parametrize("title", ["도입", "진짜 도입"])
def test_framed_slide_intro_title_cannot_skip_required_image(tmp_path, title: str):
    notes, transcript = _fixture_texts_with_slides(
        [
            {"t": 0.0, "frame": "frames/slide-001.png", "ocr_text": title},
            {"t": 60.0, "frame": "frames/slide-002.png", "ocr_text": "핵심 슬라이드"},
        ]
    )
    enriched = _replace_section_body(
        _remove_marker_lines(notes),
        NOTES_TAKEAWAY_ANCHOR,
        NOTES_TOC_ANCHOR,
        [f"요약 문장 {i}" for i in range(1, 4)],
    )
    missing_image = _remove_image_from_detail_heading(enriched, title)

    assert NOTES_INTRO_MARKER not in enriched
    problems = hook_contract_problems(missing_image, transcript, has_frames=True)
    assert any("frames/" in item and title in item for item in problems)

    out = _write_run_dir(tmp_path, f"framed-intro-{len(title)}", missing_image, transcript)
    runstate_path = tmp_path / "framed-intro-runstate.json"
    _write_runstate(runstate_path, [_complete_run(out)])
    proc = _run_hook(_HOOK_PATH, runstate_path)

    assert proc.returncode == 2, proc.stderr or proc.stdout
    assert "frames/" in proc.stderr


def test_fresh_notes_contract_import_keeps_heavy_runtime_modules_unloaded():
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import lectural.notes_contract; "
                "heavy=['cv2','numpy','paddleocr','paddle','PIL']; "
                "loaded=[m for m in heavy if m in sys.modules]; "
                "assert loaded == [], loaded"
            ),
        ],
        text=True,
        capture_output=True,
        cwd=str(_REPO_ROOT),
        check=False,
    )

    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_real_completeness_hook_subprocess_matrix(tmp_path):
    skeleton, transcript = _fixture_texts()
    valid_notes = _enriched_notes()
    valid_out = _write_run_dir(tmp_path, "valid", valid_notes, transcript)
    bare_out = _write_run_dir(tmp_path, "bare", skeleton, transcript)
    dangling_notes = _mutate_first_concept_bullet(
        valid_notes,
        lambda line: re.sub(r"transcript\.md#t\d{6}(?:-\d+)?", "transcript.md#t999999", line, count=1),
    )
    dangling_out = _write_run_dir(tmp_path, "dangling", dangling_notes, transcript)

    records: list[tuple[str, subprocess.CompletedProcess[str]]] = []

    cases: list[tuple[str, Path, int]] = []
    valid_rs = tmp_path / "valid-runstate.json"
    _write_runstate(valid_rs, [_complete_run(valid_out)])
    cases.append(("enriched-valid", valid_rs, 0))

    bare_rs = tmp_path / "bare-runstate.json"
    _write_runstate(bare_rs, [_complete_run(bare_out)])
    cases.append(("bare-skeleton", bare_rs, 2))

    dangling_rs = tmp_path / "dangling-runstate.json"
    _write_runstate(dangling_rs, [_complete_run(dangling_out)])
    cases.append(("dangling-anchor", dangling_rs, 2))

    failed_rs = tmp_path / "failed-runstate.json"
    _write_runstate(failed_rs, [{"status": "failed", "error": "intentional failure", "output_dir": str(tmp_path / "failed")}])
    cases.append(("failed-run", failed_rs, 2))

    pending_rs = tmp_path / "pending-runstate.json"
    _write_runstate(pending_rs, [{"status": "pending", "url": "https://youtu.be/pending"}])
    cases.append(("pending-run", pending_rs, 2))

    malformed_rs = tmp_path / "malformed-runstate.json"
    malformed_rs.write_text("{not json", encoding="utf-8")
    cases.append(("malformed-runstate", malformed_rs, 2))

    for label, runstate_path, expected in cases:
        proc = _run_hook(_HOOK_PATH, runstate_path)
        records.append((label, proc))
        assert proc.returncode == expected, proc.stderr or proc.stdout

    broken_scripts = tmp_path / "broken_repo" / "scripts"
    broken_scripts.mkdir(parents=True)
    broken_hook = broken_scripts / "completeness_hook.py"
    broken_hook.write_text(
        _HOOK_PATH.read_text(encoding="utf-8").replace(
            "from lectural.notes_contract import (",
            "from lectural._missing_notes_contract_for_wu4 import (",
            1,
        ),
        encoding="utf-8",
    )

    import_fail_rs = tmp_path / "import-fail-runstate.json"
    _write_runstate(import_fail_rs, [_complete_run(valid_out)])
    import_fail_proc = _run_hook(broken_hook, import_fail_rs, cwd=tmp_path / "broken_repo", strip_pythonpath=True)
    records.append(("fail-closed-import-error-with-runstate", import_fail_proc))
    assert import_fail_proc.returncode == 2, import_fail_proc.stderr or import_fail_proc.stdout

    missing_rs = tmp_path / "missing-runstate.json"
    no_runstate_proc = _run_hook(broken_hook, missing_rs, cwd=tmp_path / "broken_repo", strip_pythonpath=True)
    records.append(("import-error-no-runstate-noop", no_runstate_proc))
    assert no_runstate_proc.returncode == 0, no_runstate_proc.stderr or no_runstate_proc.stdout

    _record_hook_matrix(records)
