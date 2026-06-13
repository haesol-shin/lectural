"""Unit tests for CLI orchestration (AC-1, AC-2, AC-11). Offline, injected processor."""

import json

from lectural import cli, runstate


def test_slugify():
    assert cli.slugify("운영체제 1강: 프로세스/스레드") == "운영체제-1강-프로세스-스레드"
    assert cli.slugify("   ") == "video"
    assert cli.slugify("a" * 200).startswith("a") and len(cli.slugify("a" * 200)) <= 80


def test_output_dir_for():
    import os
    assert cli.output_dir_for("./output", "OS Lecture") == os.path.join("./output", "OS-Lecture")

def test_frame_link_is_posix_separated():
    import os
    out_dir = os.path.join("output", "lecture")
    image = os.path.join(out_dir, "frames", "frame_00001.png")
    link = cli._frame_link(image, out_dir)
    # Markdown/web links must use forward slashes on every OS (Windows regression:
    # backslash links broke the completeness hook's "frames/" slide-link check).
    assert link == "frames/frame_00001.png"
    assert "\\" not in link


def test_parse_args_single_and_batch():
    a = cli.parse_args(["https://youtu.be/abc"])
    assert a.urls == ["https://youtu.be/abc"] and a.force_stt is False and a.model == "medium"
    b = cli.parse_args(["u1", "u2", "--force-stt", "--model", "small", "--out", "./o"])
    assert b.urls == ["u1", "u2"] and b.force_stt is True and b.model == "small" and b.out == "./o"


def _fake_processor(url, out_dir, force_stt, model):
    # Stand-in for the real pipeline; records what it was asked to do.
    return {
        "output_dir": f"./output/{url[-1]}",
        "coverage_json": f"./output/{url[-1]}/coverage.json",
        "summary_md": f"./output/{url[-1]}/summary.md",
        "transcript_md": f"./output/{url[-1]}/transcript.md",
        "overall_pass": True,
    }


def test_run_single(tmp_path, monkeypatch):
    rs = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(rs))
    results = cli.run(["https://youtu.be/A"], processor=_fake_processor, runstate_file=str(rs))
    assert len(results) == 1
    state = json.loads(rs.read_text(encoding="utf-8"))
    assert len(state["runs"]) == 1  # AC-1: one run recorded


def test_run_sequential_batch_records_each(tmp_path):
    rs = tmp_path / "runstate.json"
    results = cli.run(["u-A", "u-B", "u-C"], processor=_fake_processor, runstate_file=str(rs))
    assert [r["output_dir"][-1] for r in results] == ["A", "B", "C"]  # order preserved
    state = json.loads(rs.read_text(encoding="utf-8"))
    assert len(state["runs"]) == 3  # AC-2: every batch run recorded for the hook


def test_run_starts_fresh_session_each_invocation(tmp_path):
    rs = tmp_path / "runstate.json"
    cli.run(["u-A", "u-B"], processor=_fake_processor, runstate_file=str(rs))
    first = json.loads(rs.read_text(encoding="utf-8"))["session_id"]
    cli.run(["u-C"], processor=_fake_processor, runstate_file=str(rs))
    second = json.loads(rs.read_text(encoding="utf-8"))
    assert second["session_id"] != first  # fresh session
    assert len(second["runs"]) == 1  # previous batch's runs cleared


def test_runstate_read_missing_is_none(tmp_path):
    assert runstate.read_state(str(tmp_path / "nope.json")) is None

def test_main_exit_2_on_coverage_failure(monkeypatch):
    monkeypatch.setattr(cli, "run", lambda *a, **k: [{"output_dir": "x", "overall_pass": False}])
    assert cli.main(["https://youtu.be/x"]) == 2


def test_main_exit_0_on_success(monkeypatch):
    monkeypatch.setattr(cli, "run", lambda *a, **k: [{"output_dir": "x", "overall_pass": True}])
    assert cli.main(["https://youtu.be/x"]) == 0
