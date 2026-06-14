"""Unit tests for CLI orchestration (AC-1, AC-2, AC-11). Offline, injected processor."""

import json
import os
from pathlib import Path
import pytest

from lectural import acquisition, cli, coverage, deps, doctor, ocr, runstate, visual


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
    assert a.keep_frames is False
    b = cli.parse_args(["u1", "u2", "--force-stt", "--model", "small", "--out", "./o", "--keep-frames"])
    assert b.urls == ["u1", "u2"] and b.force_stt is True and b.model == "small" and b.out == "./o"
    assert b.keep_frames is True
def test_parse_args_doctor_command():
    args = cli.parse_args(["doctor", "--fix", "--json"])
    assert args.command == "doctor"
    assert args.fix is True
    assert args.json is True


def test_help_works_for_root_and_doctor():
    with pytest.raises(SystemExit) as root_exit:
        cli.parse_args(["--help"])
    assert root_exit.value.code == 0

    with pytest.raises(SystemExit) as doctor_exit:
        cli.parse_args(["doctor", "--help"])
    assert doctor_exit.value.code == 0




def _fake_processor(url, out_dir, force_stt, model):
    # Stand-in for the real pipeline; records what it was asked to do.
    return {
        "output_dir": f"./output/{url[-1]}",
        "coverage_json": f"./output/{url[-1]}/coverage.json",
        "notes_md": f"./output/{url[-1]}/notes.md",
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


def _install_default_processor_fakes(monkeypatch, tmp_path, metadata):
    calls: dict[str, str] = {}
    monkeypatch.setattr(deps, "assert_acquisition_ready", lambda: None)
    monkeypatch.setattr(acquisition, "fetch_video_metadata", lambda url: dict(metadata))

    def fake_acquire_speech(url, out_dir, force_stt=False):
        calls["acquire_out_dir"] = out_dir
        return acquisition.SpeechTrack(
            segments=[
                acquisition.Segment(0.0, "첫 번째 문장입니다"),
                acquisition.Segment(30.0, "두 번째 문장입니다"),
                acquisition.Segment(60.0, "세 번째 문장입니다"),
            ],
            source="caption",
            meta={"audio_path": os.path.join(out_dir, "audio.wav")},
        )

    def fake_download_video(url, out_dir):
        calls["download_out_dir"] = out_dir
        return str(tmp_path / "video.mp4")

    def fake_extract_candidate_frames(video_path, frames_dir):
        calls["frames_dir"] = frames_dir
        Path(frames_dir).mkdir(parents=True, exist_ok=True)
        frames = []
        for index, timestamp in ((1, 5.0), (2, 15.0), (3, 25.0)):
            path = Path(frames_dir) / f"frame_{index:05d}.png"
            path.write_text(f"raw {index}", encoding="utf-8")
            frames.append(visual.Frame(timestamp=timestamp, image_path=str(path)))
        return frames

    def fake_ocr_frames(frames):
        for frame in frames:
            frame.ocr_text = "슬라이드 제목"
            frame.is_slide = True
        return frames, "none"

    monkeypatch.setattr(acquisition, "acquire_speech", fake_acquire_speech)
    monkeypatch.setattr(cli, "_download_video", fake_download_video)
    monkeypatch.setattr(visual, "extract_candidate_frames", fake_extract_candidate_frames)
    monkeypatch.setattr(visual, "dedupe_frames", lambda frames: [frames[0], frames[-1]])
    monkeypatch.setattr(ocr, "ocr_frames", fake_ocr_frames)
    return calls


def test_default_processor_uses_title_slug_before_acquiring_speech(tmp_path, monkeypatch):
    metadata = {
        "title": "운영체제 1강: 프로세스/스레드",
        "duration": 120.0,
        "video_id": "dQw4w9WgXcQ",
    }
    calls = _install_default_processor_fakes(monkeypatch, tmp_path, metadata)

    result = cli._default_processor(
        "https://youtu.be/dQw4w9WgXcQ",
        str(tmp_path / "video_01"),
        force_stt=False,
        model="tiny",
    )

    expected_dir = os.path.join(str(tmp_path), "운영체제-1강-프로세스-스레드")
    assert calls["acquire_out_dir"] == expected_dir
    assert calls["download_out_dir"] == expected_dir
    assert calls["frames_dir"] == os.path.join(expected_dir, "frames")
    assert result["output_dir"] == expected_dir
    assert result["notes_md"] == os.path.join(expected_dir, "notes.md")
    assert "video_01" not in calls["acquire_out_dir"]

    coverage = json.loads((tmp_path / "운영체제-1강-프로세스-스레드" / "coverage.json").read_text(encoding="utf-8"))
    assert coverage["video_title"] == "운영체제 1강: 프로세스/스레드"
    assert coverage["duration_sec"] == 120.0
    assert coverage["artifacts"]["notes_md"] == os.path.join(expected_dir, "notes.md")
    assert coverage["artifacts"]["notes_nonempty"] is True
    assert coverage["artifacts"]["transcript_nonempty"] is True

    notes = (tmp_path / "운영체제-1강-프로세스-스레드" / "notes.md").read_text(encoding="utf-8")
    transcript = (tmp_path / "운영체제-1강-프로세스-스레드" / "transcript.md").read_text(encoding="utf-8")
    assert notes.startswith("<!-- lectural:notes -->")
    assert "## 목차" in notes
    assert "frames/frame_00001.png" in notes
    assert "## 정리 노트" in notes
    assert '<img src="frames/frame_00001.png"' in notes
    assert '<a id="t000030"></a> [00:00:30] 두 번째 문장입니다' in transcript
    assert not (tmp_path / "운영체제-1강-프로세스-스레드" / "summary.md").exists()
    assert not (tmp_path / "운영체제-1강-프로세스-스레드" / "outline.md").exists()


def test_default_processor_cleanup_keeps_coverage_raw_times(tmp_path, monkeypatch):
    calls = _install_default_processor_fakes(
        monkeypatch,
        tmp_path,
        {"title": "프레임 정리", "duration": 120.0, "video_id": "frames"},
    )
    captured_raw_times = []
    coverage_input_frame_exists = []
    original_coverage_inputs = coverage.coverage_inputs_from_extraction

    def capture_coverage_inputs(**kwargs):
        captured_raw_times.append(list(kwargs["raw_sample_times"]))
        frame_2 = Path(calls["frames_dir"]) / "frame_00002.png"
        coverage_input_frame_exists.append(frame_2.exists())
        return original_coverage_inputs(**kwargs)

    monkeypatch.setattr(coverage, "coverage_inputs_from_extraction", capture_coverage_inputs)

    result = cli._default_processor(
        "https://youtu.be/frames",
        str(tmp_path / "video_01"),
        force_stt=False,
        model="tiny",
    )

    frames_dir = Path(result["output_dir"]) / "frames"
    assert sorted(p.name for p in frames_dir.glob("*.png")) == ["frame_00001.png", "frame_00003.png"]
    assert not (frames_dir / "raw").exists()
    assert captured_raw_times and all(times == [5.0, 15.0, 25.0] for times in captured_raw_times)
    assert coverage_input_frame_exists and all(coverage_input_frame_exists)


def test_default_processor_keep_frames_archives_raw_without_relinking_slides(tmp_path, monkeypatch):
    _install_default_processor_fakes(
        monkeypatch,
        tmp_path,
        {"title": "원본 보존", "duration": 120.0, "video_id": "keep"},
    )

    result = cli._default_processor(
        "https://youtu.be/keep",
        str(tmp_path / "video_01"),
        force_stt=False,
        model="tiny",
        keep_frames=True,
    )

    out_dir = Path(result["output_dir"])
    frames_dir = out_dir / "frames"
    assert sorted(p.name for p in frames_dir.glob("*.png")) == ["frame_00001.png", "frame_00003.png"]
    assert sorted(p.name for p in (frames_dir / "raw").glob("*.png")) == [
        "frame_00001.png",
        "frame_00002.png",
        "frame_00003.png",
    ]
    notes = (out_dir / "notes.md").read_text(encoding="utf-8")
    assert "frames/frame_00001.png" in notes
    assert "frames/raw/" not in notes


def test_default_processor_falls_back_to_video_id_when_title_missing(tmp_path, monkeypatch):
    calls = _install_default_processor_fakes(
        monkeypatch,
        tmp_path,
        {"duration": 45.0, "video_id": "dQw4w9WgXcQ"},
    )

    result = cli._default_processor(
        "https://youtu.be/dQw4w9WgXcQ",
        str(tmp_path / "video_01"),
        force_stt=False,
        model="tiny",
    )

    expected_dir = os.path.join(str(tmp_path), "dQw4w9WgXcQ")
    assert calls["acquire_out_dir"] == expected_dir
    assert result["output_dir"] == expected_dir
    assert "video_01" not in result["output_dir"]

def test_main_exit_2_on_coverage_failure(monkeypatch):
    monkeypatch.setattr(cli, "run", lambda *a, **k: [{"output_dir": "x", "overall_pass": False}])
    assert cli.main(["https://youtu.be/x"]) == 2


def test_main_exit_0_on_success(monkeypatch):
    monkeypatch.setattr(cli, "run", lambda *a, **k: [{"output_dir": "x", "overall_pass": True}])
    assert cli.main(["https://youtu.be/x"]) == 0
def test_main_dispatches_doctor_json(monkeypatch, capsys):
    report = {"schema_version": 1, "items": [], "overall_status": "ready", "exit_code": 0}
    monkeypatch.setattr(doctor, "run", lambda fix=False: report)
    monkeypatch.setattr(doctor, "print_report", lambda actual, json_output=False: print("json" if json_output else "text"))

    assert cli.main(["doctor", "--json"]) == 0
    assert capsys.readouterr().out.strip() == "json"
