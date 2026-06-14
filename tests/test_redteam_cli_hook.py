"""Adversarial QA for CLI orchestration and completeness Stop hook."""

from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path

import pytest

from lectural import cli, runstate


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


def _summary_text(hook) -> str:
    return (
        f"{hook.ENRICH_MARKER}\n"
        "# 강의 요약\n\n"
        f"{hook.COVERAGE_ANCHOR}\n"
        "- coverage: pass\n\n"
        "## TO-ENRICH\n"
        "TO-ENRICH: host agent는 요약을 보강할 수 있습니다.\n"
    )


def _outline_text(hook, *, frame_link: bool = False) -> str:
    image_line = "![slide](frames/slide-001.png)\n" if frame_link else ""
    return (
        "# 강의 개요\n\n"
        f"{hook.TOC_ANCHOR}\n"
        "- [00:00:00 · 시작](#sec-0)\n\n"
        '<a id="sec-0"></a>\n'
        "## 섹션 1. [00:00:00] 시작\n"
        f"{image_line}"
        "- [00:00:02] 핵심 설명\n"
    )


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
    summary_text: str | None = None,
    outline_text: str | None = None,
    write_outline: bool = True,
    frames_png: bool = False,
) -> dict:
    out = tmp_path / name
    out.mkdir()
    summary = out / "summary.md"
    summary.write_text(summary_text if summary_text is not None else _summary_text(hook), encoding="utf-8")
    outline = out / "outline.md"
    if write_outline:
        outline.write_text(outline_text if outline_text is not None else _outline_text(hook, frame_link=frames_png), encoding="utf-8")

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
        "summary_md": str(summary),
        "outline_md": str(outline),
    }
    if not write_outline:
        run.pop("outline_md")
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
            "summary_md": str(Path(out_dir) / "summary.md"),
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
            "summary_md": f"{out_dir}-{url}/summary.md",
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


@pytest.mark.parametrize("missing_anchor", ["ENRICH_MARKER", "COVERAGE_ANCHOR"])
def test_hook_blocks_when_each_required_summary_anchor_is_missing(tmp_path, monkeypatch, missing_anchor):
    hook = _load_hook()
    text = _summary_text(hook).replace(getattr(hook, missing_anchor), "")
    run = _make_run(tmp_path, hook, summary_text=text)

    assert _hook_exit(tmp_path, monkeypatch, [run]) == 2


def test_hook_blocks_when_outline_missing(tmp_path, monkeypatch):
    hook = _load_hook()
    run = _make_run(tmp_path, hook, write_outline=False)

    assert _hook_exit(tmp_path, monkeypatch, [run]) == 2


@pytest.mark.parametrize(
    "outline_text",
    [
        "# 강의 개요\n\n- [00:00:00 · 시작](#sec-0)\n",
        "# 강의 개요\n\n## 목차\n- 시작\n",
    ],
)
def test_hook_blocks_when_required_outline_anchor_is_missing(tmp_path, monkeypatch, outline_text):
    hook = _load_hook()
    run = _make_run(tmp_path, hook, outline_text=outline_text)

    assert _hook_exit(tmp_path, monkeypatch, [run]) == 2


def test_hook_blocks_when_outline_has_toc_and_section_timestamp_but_no_transcript_bullet(tmp_path, monkeypatch):
    hook = _load_hook()
    outline_text = (
        "# 강의 개요\n\n"
        f"{hook.TOC_ANCHOR}\n"
        "- [00:00:00 · 시작](#sec-0)\n\n"
        '<a id="sec-0"></a>\n'
        "## 섹션 1. [00:00:00] 시작\n"
    )
    run = _make_run(tmp_path, hook, outline_text=outline_text)

    assert _hook_exit(tmp_path, monkeypatch, [run]) == 2


def test_hook_blocks_when_frames_exist_but_outline_has_no_frame_link(tmp_path, monkeypatch):
    hook = _load_hook()
    run = _make_run(tmp_path, hook, frames_png=True, outline_text=_outline_text(hook, frame_link=False))

    assert _hook_exit(tmp_path, monkeypatch, [run]) == 2


def test_hook_all_good_with_outline_frame_link_passes(tmp_path, monkeypatch):
    hook = _load_hook()
    run = _make_run(tmp_path, hook, frames_png=True, outline_text=_outline_text(hook, frame_link=True))

    assert _hook_exit(tmp_path, monkeypatch, [run]) == 0


def test_hook_batch_with_one_failed_run_blocks_whole_gate(tmp_path, monkeypatch):
    hook = _load_hook()
    runs = [
        _make_run(tmp_path, hook, "run1", overall_pass=True),
        _make_run(tmp_path, hook, "run2", overall_pass=False),
        _make_run(tmp_path, hook, "run3", overall_pass=True),
    ]

    assert _hook_exit(tmp_path, monkeypatch, runs) == 2
