"""Adversarial QA for CLI orchestration and completeness Stop hook."""

from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path

import pytest

from lectural import cli, runstate
from lectural.notes_contract import hook_contract_problems


_HOOK_PATH = Path(__file__).resolve().parents[1] / "scripts" / "completeness_hook.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("completeness_hook_redteam", _HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _coverage_payload(overall_pass: bool = True) -> dict:
    return {
        "schema_version": 1,
        "overall_pass": overall_pass,
        "gap_check": {
            "max_untranscribed_speech_gap_sec": 3 if overall_pass else 90,
            "threshold_sec": 60,
            "pass": overall_pass,
        },
        "scene_coverage": {
            "uncovered_speech_bins": [] if overall_pass else [2],
            "slide_frames_with_text": 2 if overall_pass else 0,
            "slide_frames_total": 2,
            "pass": overall_pass,
        },
        "artifacts": {"pass": overall_pass},
    }


def _write_coverage(path: Path, overall_pass: bool = True) -> None:
    path.write_text(json.dumps(_coverage_payload(overall_pass), ensure_ascii=False), encoding="utf-8")


def _notes_text(hook, *, frame_link: bool = False) -> str:
    image_line = '<img src="frames/slide-001.png" alt="슬라이드 1" width="480">\n\n' if frame_link else ""
    return (
        f"{hook.NOTES_ENRICH_MARKER}\n"
        "# 강의 정리\n\n"
        f"{hook.NOTES_TAKEAWAY_ANCHOR}\n- 요약 1\n- 요약 2\n- 요약 3\n\n"
        f"{hook.NOTES_TOC_ANCHOR}\n- [시작](#sec-1)\n\n"
        f"{hook.NOTES_FLOW_ANCHOR}\n- 도입 흐름\n- 핵심 흐름\n\n"
        f"{hook.NOTES_CONCEPTS_ANCHOR}\n"
        "- **핵심 설명**: 핵심 정의. ([영상 0:02](https://youtu.be/abc12345678?t=2))\n\n"
        f"{hook.NOTES_DETAIL_ANCHOR}\n"
        '<a id="sec-1"></a>\n'
        "### 시작\n"
        f"{image_line}"
        "- 핵심 설명을 정리합니다.\n\n"
        f"{hook.NOTES_QUESTIONS_ANCHOR}\n"
        "**Q1. 핵심은 무엇인가요?**\n\n"
        "<details>\n<summary>답 보기</summary>\n\n"
        "핵심 설명입니다. ([영상 0:02](https://youtu.be/abc12345678?t=2))\n\n"
        "</details>\n\n"
        "**Q2. 근거는 어디인가요?**\n\n"
        "<details>\n<summary>답 보기</summary>\n\n"
        "전사 발화입니다. ([영상 0:02](https://youtu.be/abc12345678?t=2))\n\n"
        "</details>\n\n"
        "**Q3. 언제 나오나요?**\n\n"
        "<details>\n<summary>답 보기</summary>\n\n"
        "2초 지점입니다. ([영상 0:02](https://youtu.be/abc12345678?t=2))\n\n"
        "</details>\n\n"
        f"{hook.NOTES_COVERAGE_ANCHOR}\n"
        "- coverage: pass\n"
    )


def _transcript_text() -> str:
    return '# 강의 정리 — 전체 전사본 (raw)\n\n<a id="t000002"></a> [00:00:02] 핵심 설명\n'


def _set_runstate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runs: list[dict]) -> Path:
    rs = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
    state = {
        "session_id": "redteam-session",
        "started_at": 1.0,
        "tool": "lectural",
        "runs": runs,
    }
    rs.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return rs


def _hook_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runs: list[dict]) -> int:
    _set_runstate(tmp_path, monkeypatch, runs)
    hook = _load_hook()
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    return hook.main()


def _make_run(
    tmp_path: Path,
    hook,
    name: str = "run1",
    *,
    coverage: bool = True,
    malformed_coverage: bool = False,
    overall_pass: bool = True,
    notes_text: str | None = None,
    write_notes: bool = True,
    frames_png: bool = False,
) -> dict:
    out = tmp_path / name
    out.mkdir()
    notes = out / "notes.md"
    if write_notes:
        notes.write_text(notes_text if notes_text is not None else _notes_text(hook, frame_link=frames_png), encoding="utf-8")

    (out / "transcript.md").write_text(_transcript_text(), encoding="utf-8")
    coverage_path = out / "coverage.json"
    if malformed_coverage:
        coverage_path.write_text("{not json", encoding="utf-8")
    elif coverage:
        _write_coverage(coverage_path, overall_pass=overall_pass)

    if frames_png:
        frames = out / "frames"
        frames.mkdir()
        (frames / "slide-001.png").write_bytes(b"not-a-real-png-but-extension-is-enough")

    run = {
        "output_dir": str(out),
        "coverage_json": str(coverage_path),
        "notes_md": str(notes),
    }
    if not write_notes:
        run.pop("notes_md")
    return run


@pytest.mark.parametrize(
    "raw",
    [
        "운영체제 1강: 프로세스/스레드",
        "emoji 😀 lecture 🚀",
        "../traverse/..\\escape",
        "  ...leading and trailing...  ",
        "a" * 500,
        "",
        "   ",
        "././",
    ],
)
def test_slugify_adversarial_names_are_safe(raw):
    slug = cli.slugify(raw)

    assert slug
    assert len(slug) <= 80
    assert "/" not in slug
    assert "\\" not in slug
    assert ".." not in slug
    assert slug == slug.strip(" .")
    assert os.path.basename(slug) == slug


def test_cli_run_empty_url_list_starts_empty_session(tmp_path):
    rs = tmp_path / "runstate.json"

    def processor(*_args):  # pragma: no cover - must not be called
        raise AssertionError("processor should not run for an empty URL list")

    assert cli.run([], processor=processor, runstate_file=str(rs)) == []
    state = json.loads(rs.read_text(encoding="utf-8"))
    assert state["tool"] == "lectural"
    assert state["runs"] == []


def test_cli_run_continues_batch_on_processor_error_and_records_failure(tmp_path):
    # New contract: a mid-batch failure does NOT abort; the failed URL is
    # recorded as `failed` and remaining URLs still run, so nothing is hidden
    # from the completeness hook.
    rs = tmp_path / "runstate.json"
    calls: list[str] = []

    def processor(url, out_dir, force_stt, model):
        calls.append(url)
        if url == "u2":
            raise RuntimeError("boom on second URL")
        return {
            "output_dir": out_dir,
            "coverage_json": str(Path(out_dir) / "coverage.json"),
            "notes_md": str(Path(out_dir) / "notes.md"),
            "transcript_md": str(Path(out_dir) / "transcript.md"),
            "overall_pass": True,
        }

    results = cli.run(["u1", "u2", "u3"], out_root=str(tmp_path / "out"),
                      processor=processor, runstate_file=str(rs))

    assert calls == ["u1", "u2", "u3"]  # batch did NOT abort
    state = json.loads(rs.read_text(encoding="utf-8"))
    assert len(state["runs"]) == 3  # every URL visible to the hook (AC-2)
    statuses = {r["index"]: r["status"] for r in state["runs"]}
    assert statuses == {0: "complete", 1: "failed", 2: "complete"}
    assert any(not r.get("overall_pass") for r in results)  # failure surfaced


def test_cli_run_fresh_session_per_invocation_and_records_every_run(tmp_path):
    rs = tmp_path / "runstate.json"

    def processor(url, out_dir, force_stt, model):
        return {
            "output_dir": f"{out_dir}-{url}",
            "coverage_json": f"{out_dir}-{url}/coverage.json",
            "notes_md": f"{out_dir}-{url}/notes.md",
            "transcript_md": f"{out_dir}-{url}/transcript.md",
            "overall_pass": True,
        }

    cli.run(["a", "b", "c"], out_root=str(tmp_path / "out"), processor=processor, runstate_file=str(rs))
    first_state = json.loads(rs.read_text(encoding="utf-8"))
    cli.run(["d", "e"], out_root=str(tmp_path / "out"), processor=processor, runstate_file=str(rs))
    second_state = json.loads(rs.read_text(encoding="utf-8"))

    assert first_state["session_id"] != second_state["session_id"]
    assert len(first_state["runs"]) == 3
    assert len(second_state["runs"]) == 2
    assert [Path(r["output_dir"]).name for r in second_state["runs"]] == ["video_01-d", "video_02-e"]


def test_hook_no_runstate_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(tmp_path / "missing-runstate.json"))
    hook = _load_hook()
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    assert hook.main() == 0


def test_hook_empty_runs_is_noop(tmp_path, monkeypatch):
    assert _hook_exit(tmp_path, monkeypatch, []) == 0


def test_hook_missing_coverage_json_blocks(tmp_path, monkeypatch):
    hook = _load_hook()
    run = _make_run(tmp_path, hook, coverage=False)

    assert _hook_exit(tmp_path, monkeypatch, [run]) == 2


def test_hook_malformed_coverage_json_blocks_without_crashing(tmp_path, monkeypatch):
    hook = _load_hook()
    run = _make_run(tmp_path, hook, malformed_coverage=True)

    assert _hook_exit(tmp_path, monkeypatch, [run]) == 2


@pytest.mark.parametrize("missing_anchor", ["NOTES_ENRICH_MARKER", "NOTES_COVERAGE_ANCHOR"])
def test_hook_blocks_when_each_required_notes_anchor_is_missing(tmp_path, monkeypatch, missing_anchor):
    hook = _load_hook()
    text = _notes_text(hook).replace(getattr(hook, missing_anchor), "")
    run = _make_run(tmp_path, hook, notes_text=text)

    assert _hook_exit(tmp_path, monkeypatch, [run]) == 2


def test_hook_blocks_when_notes_missing(tmp_path, monkeypatch):
    hook = _load_hook()
    run = _make_run(tmp_path, hook, write_notes=False)

    assert _hook_exit(tmp_path, monkeypatch, [run]) == 2


@pytest.mark.parametrize(
    "missing_anchor",
    ["NOTES_TOC_ANCHOR", "NOTES_DETAIL_ANCHOR"],
)
def test_hook_blocks_when_required_notes_section_is_missing(tmp_path, monkeypatch, missing_anchor):
    hook = _load_hook()
    text = _notes_text(hook).replace(getattr(hook, missing_anchor), "")
    run = _make_run(tmp_path, hook, notes_text=text)

    assert _hook_exit(tmp_path, monkeypatch, [run]) == 2


def test_hook_blocks_when_notes_marker_is_not_line_one(tmp_path, monkeypatch):
    hook = _load_hook()
    run = _make_run(tmp_path, hook, notes_text="\n" + _notes_text(hook))

    assert _hook_exit(tmp_path, monkeypatch, [run]) == 2


def test_hook_blocks_when_frames_exist_but_notes_has_no_frame_link(tmp_path, monkeypatch):
    hook = _load_hook()
    run = _make_run(tmp_path, hook, frames_png=True, notes_text=_notes_text(hook, frame_link=False))

    assert _hook_exit(tmp_path, monkeypatch, [run]) == 2


def test_hook_all_good_with_notes_frame_link_passes(tmp_path, monkeypatch):
    hook = _load_hook()
    run = _make_run(tmp_path, hook, frames_png=True, notes_text=_notes_text(hook, frame_link=True))

    assert _hook_exit(tmp_path, monkeypatch, [run]) == 0


def test_hook_batch_with_one_failed_run_blocks_whole_gate(tmp_path, monkeypatch):
    hook = _load_hook()
    runs = [
        _make_run(tmp_path, hook, "run1", overall_pass=True),
        _make_run(tmp_path, hook, "run2", overall_pass=False),
        _make_run(tmp_path, hook, "run3", overall_pass=True),
    ]

    assert _hook_exit(tmp_path, monkeypatch, runs) == 2


def test_notes_contract_adversarial_bad_youtube_second_fails():
    hook = _load_hook()
    text = _notes_text(hook).replace("https://youtu.be/abc12345678?t=2", "https://youtu.be/abc12345678?t=999", 1)
    problems = hook_contract_problems(text, _transcript_text(), has_frames=False)

    assert any("1초 넘게 다릅니다" in p for p in problems)


def test_notes_contract_adversarial_missing_youtube_fails():
    hook = _load_hook()
    text = _notes_text(hook).replace(" ([영상 0:02](https://youtu.be/abc12345678?t=2))", "", 1)
    problems = hook_contract_problems(text, _transcript_text(), has_frames=False)

    assert any("영상 딥링크" in p for p in problems)


@pytest.mark.parametrize(
    ("offset", "passes"),
    [
        (1, True),
        (2, False),
    ],
)
def test_notes_contract_adversarial_youtube_seconds_tolerance(offset, passes):
    hook = _load_hook()
    text = _notes_text(hook).replace("https://youtu.be/abc12345678?t=2", f"https://youtu.be/abc12345678?t={2 + offset}", 1)
    problems = hook_contract_problems(text, _transcript_text(), has_frames=False)

    assert (not [p for p in problems if "1초 넘게 다릅니다" in p]) is passes
