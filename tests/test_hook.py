"""Unit tests for the completeness Stop hook (AC-13). Offline."""

import builtins
import importlib.util
import json
import os

from lectural import runstate
from lectural.synthesis import (
    NOTES_CONCEPTS_ANCHOR,
    NOTES_DETAIL_ANCHOR,
    NOTES_FLOW_ANCHOR,
    NOTES_COVERAGE_ANCHOR,
    NOTES_QUESTIONS_ANCHOR,
    NOTES_INTRO_MARKER,
    NOTES_TAKEAWAY_ANCHOR,
    NOTES_TOC_ANCHOR,
    NOTES_UNENRICHED_MARKER,
    build_synthesis_input,
    render_notes_md,
    render_transcript_md,
)

_HOOK_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "completeness_hook.py")


def _load_hook(name="completeness_hook"):
    spec = importlib.util.spec_from_file_location(name, _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fixture_texts() -> tuple[str, str]:
    video = {
        "title": "T",
        "source": "https://youtu.be/abc12345678",
        "video_id": "abc12345678",
        "duration_sec": 600.0,
    }
    segments = [{"t": 5.0, "text": "핵심 설명"}]
    slides = [{"t": 0.0, "frame": "frames/slide-001.png", "ocr_text": "도입 슬라이드"}]
    coverage = {
        "duration_sec": 600.0,
        "gap_check": {"max_untranscribed_speech_gap_sec": 0, "threshold_sec": 60, "pass": True},
        "scene_coverage": {"speech_bins": [0], "uncovered_speech_bins": [], "pass": True,
                           "slide_frames_with_text": 1, "slide_frames_total": 1},
        "artifacts": {"transcript_nonempty": True, "notes_nonempty": True},
        "ocr_engine": "none",
    }
    synthesis_input = build_synthesis_input(video, segments, slides)
    return render_notes_md(synthesis_input, coverage), render_transcript_md(video, segments)

def _multi_slide_fixture_texts(*, intro: bool = False) -> tuple[str, str]:
    video = {
        "title": "T",
        "source": "https://youtu.be/abc12345678",
        "video_id": "abc12345678",
        "duration_sec": 120.0,
    }
    segments = [
        {"t": 5.0, "text": "도입 설명" if intro else "첫 번째 슬라이드 설명"},
        {"t": 15.0, "text": "첫 번째 슬라이드 본문"},
        {"t": 65.0, "text": "두 번째 슬라이드 본문"},
    ] if intro else [
        {"t": 5.0, "text": "첫 번째 슬라이드 본문"},
        {"t": 65.0, "text": "두 번째 슬라이드 본문"},
    ]
    slides = [
        {"t": 10.0 if intro else 0.0, "frame": "frames/slide-001.png", "ocr_text": "첫 슬라이드"},
        {"t": 60.0, "frame": "frames/slide-002.png", "ocr_text": "핵심 슬라이드"},
    ]
    coverage = {
        "duration_sec": 120.0,
        "gap_check": {"max_untranscribed_speech_gap_sec": 0, "threshold_sec": 60, "pass": True},
        "scene_coverage": {"speech_bins": [0], "uncovered_speech_bins": [], "pass": True,
                           "slide_frames_with_text": 2, "slide_frames_total": 2},
        "artifacts": {"transcript_nonempty": True, "notes_nonempty": True},
        "ocr_engine": "none",
    }
    synthesis_input = build_synthesis_input(video, segments, slides)
    return render_notes_md(synthesis_input, coverage), render_transcript_md(video, segments)




def _replace_section_body(text: str, anchor: str, next_anchor: str, lines: list[str]) -> str:
    body_start = text.index("\n", text.index(anchor)) + 1
    body_end = text.index(next_anchor, body_start)
    return text[:body_start] + "\n".join(lines).rstrip() + "\n\n" + text[body_end:]


def _enrich_rendered_notes(*, notes: str, takeaway_lines: int = 3, flow_bullets: int = 2,
                           detail_bullets: bool = True, frame_link: bool = True,
                           keep_unenriched_marker: bool = False) -> str:
    if not keep_unenriched_marker:
        notes = notes.replace(f"{NOTES_UNENRICHED_MARKER}\n", "")
    notes = _replace_section_body(
        notes,
        NOTES_TAKEAWAY_ANCHOR,
        NOTES_TOC_ANCHOR,
        [f"- 요약 {i}" for i in range(1, takeaway_lines + 1)],
    )
    notes = _replace_section_body(
        notes,
        NOTES_FLOW_ANCHOR,
        NOTES_CONCEPTS_ANCHOR,
        [f"- 흐름 {i}" for i in range(1, flow_bullets + 1)],
    )
    notes = _replace_section_body(
        notes,
        NOTES_CONCEPTS_ANCHOR,
        NOTES_DETAIL_ANCHOR,
        ["- **핵심 설명**: 핵심 정의. ([영상 0:05](https://youtu.be/abc12345678?t=5))"],
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
            "핵심 설명입니다. ([영상 0:05](https://youtu.be/abc12345678?t=5))",
            "",
            "</details>",
            "",
            "**Q2. 근거는 어디인가요?**",
            "",
            "<details>",
            "<summary>답 보기</summary>",
            "",
            "전사 발화입니다. ([영상 0:05](https://youtu.be/abc12345678?t=5))",
            "",
            "</details>",
            "",
            "**Q3. 언제 나오나요?**",
            "",
            "<details>",
            "<summary>답 보기</summary>",
            "",
            "5초 지점입니다. ([영상 0:05](https://youtu.be/abc12345678?t=5))",
            "",
            "</details>",
        ],
    )
    if not detail_bullets:
        lines = []
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
    if not frame_link:
        notes = "\n".join(
            line for line in notes.splitlines()
            if not line.startswith("![") and not line.startswith("<img")
        ) + "\n"
    return notes


def _enriched_notes(*, takeaway_lines: int = 3, flow_bullets: int = 2, detail_bullets: bool = True,
                    frame_link: bool = True, keep_unenriched_marker: bool = False) -> str:
    notes, _ = _fixture_texts()
    return _enrich_rendered_notes(
        notes=notes,
        takeaway_lines=takeaway_lines,
        flow_bullets=flow_bullets,
        detail_bullets=detail_bullets,
        frame_link=frame_link,
        keep_unenriched_marker=keep_unenriched_marker,
    )

def _detail_heading_block(notes: str, heading_text: str) -> str:
    lines = notes.splitlines()
    in_detail = False
    start: int | None = None
    for i, line in enumerate(lines):
        if line == NOTES_DETAIL_ANCHOR:
            in_detail = True
            continue
        if in_detail and line.startswith("## "):
            break
        if in_detail and line.startswith("### ") and heading_text in line:
            start = i
            break
    assert start is not None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("### ") or lines[i].startswith("## "):
            end = i
            break
    return "\n".join(lines[start:end])



def _remove_image_from_detail_heading(notes: str, heading_text: str) -> str:
    lines = []
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
        if in_target_heading and (line.startswith("![") or line.startswith("<img")) and not removed:
            removed = True
            continue
        lines.append(line)
    assert removed
    return "\n".join(lines) + "\n"


def _coverage(path, overall_pass=True):
    cov = {
        "schema_version": 1, "overall_pass": overall_pass,
        "gap_check": {"max_untranscribed_speech_gap_sec": 10, "threshold_sec": 60, "pass": overall_pass},
        "scene_coverage": {"uncovered_speech_bins": [] if overall_pass else [3, 4],
                           "slide_frames_with_text": 2, "slide_frames_total": 2, "pass": overall_pass},
        "artifacts": {"pass": True},
    }
    path.write_text(json.dumps(cov), encoding="utf-8")


def _make_complete_run(tmp_path, monkeypatch, *, notes_text: str | None = None,
                       transcript_text: str | None = None, overall_pass: bool = True,
                       frames: bool = True, write_notes: bool = True):
    rs = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
    out = tmp_path / "run1"
    out.mkdir()
    default_notes, default_transcript = _fixture_texts()
    if write_notes:
        (out / "notes.md").write_text(notes_text if notes_text is not None else default_notes, encoding="utf-8")
    (out / "transcript.md").write_text(transcript_text if transcript_text is not None else default_transcript, encoding="utf-8")
    if frames:
        frames_dir = out / "frames"
        frames_dir.mkdir()
        (frames_dir / "slide-001.png").write_bytes(b"png")
    _coverage(out / "coverage.json", overall_pass=overall_pass)
    runstate.start_session(["u"], str(rs))
    runstate.update_run(0, status="complete", output_dir=str(out),
                        coverage_json=str(out / "coverage.json"),
                        notes_md=str(out / "notes.md"), path=str(rs))
    return out


def _run_hook(monkeypatch, name="completeness_hook") -> int:
    hook = _load_hook(name)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    return hook.main()


def test_hook_no_runstate_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(tmp_path / "absent.json"))
    assert _run_hook(monkeypatch) == 0


def test_hook_passes_with_enriched_valid_notes(tmp_path, monkeypatch):
    _make_complete_run(tmp_path, monkeypatch, notes_text=_enriched_notes())
    assert _run_hook(monkeypatch) == 0
def test_hook_passes_when_every_slide_heading_has_image_and_bullet(tmp_path, monkeypatch):
    notes, transcript = _multi_slide_fixture_texts()
    _make_complete_run(
        tmp_path,
        monkeypatch,
        notes_text=_enrich_rendered_notes(notes=notes),
        transcript_text=transcript,
    )
    assert _run_hook(monkeypatch) == 0


def test_hook_blocks_when_non_intro_slide_heading_lacks_own_image(tmp_path, monkeypatch):
    notes, transcript = _multi_slide_fixture_texts()
    enriched = _enrich_rendered_notes(notes=notes)
    missing_image = _remove_image_from_detail_heading(enriched, "핵심 슬라이드")
    _make_complete_run(tmp_path, monkeypatch, notes_text=missing_image, transcript_text=transcript)
    assert _run_hook(monkeypatch) == 2


def test_hook_allows_intro_heading_without_image_when_real_slides_have_images(tmp_path, monkeypatch):
    notes, transcript = _multi_slide_fixture_texts(intro=True)
    enriched = _enrich_rendered_notes(notes=notes)
    intro_block = _detail_heading_block(enriched, "도입")

    assert NOTES_INTRO_MARKER in intro_block
    assert "<img" not in intro_block
    real_slide_block = _detail_heading_block(enriched, "첫 슬라이드")
    assert NOTES_INTRO_MARKER not in real_slide_block
    assert "frames/slide-001.png" in real_slide_block

    _make_complete_run(
        tmp_path,
        monkeypatch,
        notes_text=enriched,
        transcript_text=transcript,
    )
    assert _run_hook(monkeypatch) == 0




def test_hook_blocks_when_coverage_fails(tmp_path, monkeypatch):
    _make_complete_run(tmp_path, monkeypatch, notes_text=_enriched_notes(), overall_pass=False)
    assert _run_hook(monkeypatch) == 2


def test_hook_blocks_when_notes_marker_missing(tmp_path, monkeypatch):
    text = _enriched_notes().replace("<!-- lectural:notes -->", "")
    _make_complete_run(tmp_path, monkeypatch, notes_text=text)
    assert _run_hook(monkeypatch) == 2


def test_hook_blocks_when_notes_missing(tmp_path, monkeypatch):
    _make_complete_run(tmp_path, monkeypatch, write_notes=False)
    assert _run_hook(monkeypatch) == 2


def test_hook_blocks_when_required_notes_section_missing(tmp_path, monkeypatch):
    for filename, missing_anchor in [
        ("missing_toc", "## 목차"),
        ("missing_detail", NOTES_DETAIL_ANCHOR),
    ]:
        run_dir = tmp_path / filename
        run_dir.mkdir()
        rs = tmp_path / f"{filename}.json"
        monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
        notes = _enriched_notes().replace(missing_anchor, "")
        _, transcript = _fixture_texts()
        (run_dir / "notes.md").write_text(notes, encoding="utf-8")
        (run_dir / "transcript.md").write_text(transcript, encoding="utf-8")
        frames = run_dir / "frames"
        frames.mkdir()
        (frames / "slide-001.png").write_bytes(b"png")
        _coverage(run_dir / "coverage.json", overall_pass=True)
        runstate.start_session(["u"], str(rs))
        runstate.update_run(0, status="complete", output_dir=str(run_dir),
                            coverage_json=str(run_dir / "coverage.json"),
                            notes_md=str(run_dir / "notes.md"), path=str(rs))
        assert _run_hook(monkeypatch, f"completeness_hook_{filename}") == 2


def test_hook_blocks_when_notes_marker_is_not_line_one(tmp_path, monkeypatch):
    _make_complete_run(tmp_path, monkeypatch, notes_text="\n" + _enriched_notes())
    assert _run_hook(monkeypatch) == 2


def test_hook_blocks_when_notes_still_contains_unenriched_marker(tmp_path, monkeypatch):
    _make_complete_run(tmp_path, monkeypatch, notes_text=_enriched_notes(keep_unenriched_marker=True))
    assert _run_hook(monkeypatch) == 2


def test_hook_blocks_when_slide_heading_has_image_but_no_bullet(tmp_path, monkeypatch):
    notes, transcript = _multi_slide_fixture_texts()
    _make_complete_run(
        tmp_path,
        monkeypatch,
        notes_text=_enrich_rendered_notes(notes=notes, detail_bullets=False),
        transcript_text=transcript,
    )
    assert _run_hook(monkeypatch) == 2


def test_hook_blocks_when_takeaway_has_too_few_or_too_many_lines(tmp_path, monkeypatch):
    for count in [2, 6]:
        run_dir = tmp_path / f"takeaway_{count}"
        run_dir.mkdir()
        rs = tmp_path / f"takeaway_{count}.json"
        monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
        notes, transcript = _enriched_notes(takeaway_lines=count), _fixture_texts()[1]
        (run_dir / "notes.md").write_text(notes, encoding="utf-8")
        (run_dir / "transcript.md").write_text(transcript, encoding="utf-8")
        frames = run_dir / "frames"; frames.mkdir(); (frames / "slide-001.png").write_bytes(b"png")
        _coverage(run_dir / "coverage.json", overall_pass=True)
        runstate.start_session(["u"], str(rs))
        runstate.update_run(0, status="complete", output_dir=str(run_dir),
                            coverage_json=str(run_dir / "coverage.json"),
                            notes_md=str(run_dir / "notes.md"), path=str(rs))
        assert _run_hook(monkeypatch, f"completeness_hook_takeaway_{count}") == 2


def test_hook_blocks_bare_skeleton_because_unenriched_marker_remains(tmp_path, monkeypatch):
    notes, _ = _fixture_texts()
    _make_complete_run(tmp_path, monkeypatch, notes_text=notes)
    assert _run_hook(monkeypatch) == 2

def test_hook_blocks_when_flow_has_fewer_than_two_bullets(tmp_path, monkeypatch):
    _make_complete_run(tmp_path, monkeypatch, notes_text=_enriched_notes(flow_bullets=1))
    assert _run_hook(monkeypatch) == 2


def test_hook_blocks_when_notes_lacks_frame_link_for_existing_frames(tmp_path, monkeypatch):
    _make_complete_run(tmp_path, monkeypatch, notes_text=_enriched_notes(frame_link=False), frames=True)
    assert _run_hook(monkeypatch) == 2


def test_hook_blocks_when_one_of_batch_fails(tmp_path, monkeypatch):
    rs = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
    runstate.start_session(["u0", "u1"], str(rs))
    _, transcript = _fixture_texts()
    for i, ok in enumerate([True, False]):
        out = tmp_path / f"run{i}"
        out.mkdir()
        (out / "notes.md").write_text(_enriched_notes(), encoding="utf-8")
        (out / "transcript.md").write_text(transcript, encoding="utf-8")
        frames = out / "frames"; frames.mkdir(); (frames / "slide-001.png").write_bytes(b"png")
        _coverage(out / "coverage.json", overall_pass=ok)
        runstate.update_run(i, status="complete", output_dir=str(out),
                            coverage_json=str(out / "coverage.json"),
                            notes_md=str(out / "notes.md"), path=str(rs))
    assert _run_hook(monkeypatch) == 2


def test_hook_contract_import_failure_fails_closed(tmp_path, monkeypatch):
    rs = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
    runstate.start_session(["u"], str(rs))
    runstate.update_run(0, status="complete", output_dir=str(tmp_path),
                        coverage_json=str(tmp_path / "coverage.json"),
                        notes_md=str(tmp_path / "notes.md"), path=str(rs))

    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "lectural.notes_contract":
            raise ImportError("blocked contract")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    hook = _load_hook("completeness_hook_import_failed")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    assert hook.main() == 2


def test_hook_source_has_no_literal_anchor_fallback():
    source = open(_HOOK_PATH, encoding="utf-8").read()
    assert "from lectural.notes_contract import" in source
    assert "fall back to literals" not in source
    assert "NOTES_TAKEAWAY_ANCHOR = \"## 한눈에 요약\"" not in source
