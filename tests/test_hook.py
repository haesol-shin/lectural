"""Unit tests for the completeness Stop hook (AC-13). Offline."""

import importlib.util
import json
import os

from lectural import runstate

_HOOK_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "completeness_hook.py")


def _load_hook():
    spec = importlib.util.spec_from_file_location("completeness_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _good_summary(path):
    text = (
        "<!-- lectural:baseline -->\n# T — 학습 정리\n\n"
        "## 커버리지 요약\n- 전체 길이: 00:10:00\n\n"
        "## TO-ENRICH\nTO-ENRICH: 보강 가능\n"
    )
    path.write_text(text, encoding="utf-8")


def _good_outline(path, *, frame_link=False):
    image_line = "![slide](frames/slide-001.png)\n" if frame_link else ""
    text = (
        "# T — 강의 개요\n\n"
        "## 목차\n- [00:00:00 · 도입](#sec-0)\n\n"
        '<a id="sec-0"></a>\n## 섹션 1. [00:00:00] 도입\n'
        f"{image_line}"
        "- [00:00:05] 안녕하세요\n"
    )
    path.write_text(text, encoding="utf-8")


def _coverage(path, overall_pass=True):
    cov = {
        "schema_version": 1, "overall_pass": overall_pass,
        "gap_check": {"max_untranscribed_speech_gap_sec": 10, "threshold_sec": 60, "pass": overall_pass},
        "scene_coverage": {"uncovered_speech_bins": [] if overall_pass else [3, 4],
                           "slide_frames_with_text": 2, "slide_frames_total": 2, "pass": overall_pass},
        "artifacts": {"pass": True},
    }
    path.write_text(json.dumps(cov), encoding="utf-8")


def test_hook_no_runstate_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(tmp_path / "absent.json"))
    hook = _load_hook()
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(""))
    assert hook.main() == 0  # not a LecturAL run -> no-op


def test_hook_passes_when_coverage_and_anchors_good(tmp_path, monkeypatch):
    rs = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
    out = tmp_path / "run1"
    out.mkdir()
    _good_summary(out / "summary.md")
    _good_outline(out / "outline.md")
    _coverage(out / "coverage.json", overall_pass=True)
    runstate.start_session(["u"], str(rs))
    runstate.update_run(0, status="complete", output_dir=str(out),
                        coverage_json=str(out / "coverage.json"),
                        summary_md=str(out / "summary.md"), path=str(rs))
    hook = _load_hook()
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    assert hook.main() == 0


def test_hook_blocks_when_coverage_fails(tmp_path, monkeypatch, capsys):
    rs = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
    out = tmp_path / "run1"
    out.mkdir()
    _good_summary(out / "summary.md")
    _good_outline(out / "outline.md")
    _coverage(out / "coverage.json", overall_pass=False)  # failing coverage
    runstate.start_session(["u"], str(rs))
    runstate.update_run(0, status="complete", output_dir=str(out),
                        coverage_json=str(out / "coverage.json"),
                        summary_md=str(out / "summary.md"), path=str(rs))
    hook = _load_hook()
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    assert hook.main() == 2  # exit 2 blocks "done"


def test_hook_blocks_when_summary_anchor_missing(tmp_path, monkeypatch):
    rs = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
    out = tmp_path / "run1"
    out.mkdir()
    (out / "summary.md").write_text("# no anchors here", encoding="utf-8")  # missing anchors
    _good_outline(out / "outline.md")
    _coverage(out / "coverage.json", overall_pass=True)
    runstate.start_session(["u"], str(rs))
    runstate.update_run(0, status="complete", output_dir=str(out),
                        coverage_json=str(out / "coverage.json"),
                        summary_md=str(out / "summary.md"), path=str(rs))
    hook = _load_hook()
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    assert hook.main() == 2


def test_hook_blocks_when_outline_missing(tmp_path, monkeypatch):
    rs = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
    out = tmp_path / "run1"
    out.mkdir()
    _good_summary(out / "summary.md")
    _coverage(out / "coverage.json", overall_pass=True)
    runstate.start_session(["u"], str(rs))
    runstate.update_run(0, status="complete", output_dir=str(out),
                        coverage_json=str(out / "coverage.json"),
                        summary_md=str(out / "summary.md"), path=str(rs))
    hook = _load_hook()
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    assert hook.main() == 2


def test_hook_blocks_when_outline_toc_or_timestamp_missing(tmp_path, monkeypatch):
    for filename, outline_text in [
        ("missing_toc", "# T\n\n- [00:00:00] 도입\n"),
        ("missing_timestamp", "# T\n\n## 목차\n- 도입\n"),
    ]:
        rs = tmp_path / f"{filename}.json"
        monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
        out = tmp_path / filename
        out.mkdir()
        _good_summary(out / "summary.md")
        (out / "outline.md").write_text(outline_text, encoding="utf-8")
        _coverage(out / "coverage.json", overall_pass=True)
        runstate.start_session(["u"], str(rs))
        runstate.update_run(0, status="complete", output_dir=str(out),
                            coverage_json=str(out / "coverage.json"),
                            summary_md=str(out / "summary.md"), path=str(rs))
        hook = _load_hook()
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
        assert hook.main() == 2


def test_hook_blocks_when_outline_has_timestamp_but_no_transcript_bullet(tmp_path, monkeypatch):
    rs = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
    out = tmp_path / "run1"
    out.mkdir()
    _good_summary(out / "summary.md")
    (out / "outline.md").write_text(
        "# T — 강의 개요\n\n"
        "## 목차\n- [00:00:00 · 도입](#sec-0)\n\n"
        '<a id="sec-0"></a>\n## 섹션 1. [00:00:00] 도입\n',
        encoding="utf-8",
    )
    _coverage(out / "coverage.json", overall_pass=True)
    runstate.start_session(["u"], str(rs))
    runstate.update_run(0, status="complete", output_dir=str(out),
                        coverage_json=str(out / "coverage.json"),
                        summary_md=str(out / "summary.md"), path=str(rs))
    hook = _load_hook()
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    assert hook.main() == 2


def test_hook_blocks_when_outline_lacks_frame_link_for_existing_frames(tmp_path, monkeypatch):
    rs = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
    out = tmp_path / "run1"
    out.mkdir()
    frames = out / "frames"
    frames.mkdir()
    (frames / "slide-001.png").write_bytes(b"png")
    _good_summary(out / "summary.md")
    _good_outline(out / "outline.md", frame_link=False)
    _coverage(out / "coverage.json", overall_pass=True)
    runstate.start_session(["u"], str(rs))
    runstate.update_run(0, status="complete", output_dir=str(out),
                        coverage_json=str(out / "coverage.json"),
                        summary_md=str(out / "summary.md"), path=str(rs))
    hook = _load_hook()
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    assert hook.main() == 2


def test_hook_blocks_when_one_of_batch_fails(tmp_path, monkeypatch):
    rs = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
    runstate.start_session(["u0", "u1"], str(rs))
    for i, ok in enumerate([True, False]):  # second run fails -> whole gate fails (AC-2)
        out = tmp_path / f"run{i}"
        out.mkdir()
        _good_summary(out / "summary.md")
        _good_outline(out / "outline.md")
        _coverage(out / "coverage.json", overall_pass=ok)
        runstate.update_run(i, status="complete", output_dir=str(out),
                            coverage_json=str(out / "coverage.json"),
                            summary_md=str(out / "summary.md"), path=str(rs))
    hook = _load_hook()
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    assert hook.main() == 2
