"""Offline CLI parsing, orchestration, and shared-pipeline tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lectural import acquisition, cli, coverage, doctor, media, vad, visual
from lectural.source import SourceKind


def test_slugify():
    assert cli.slugify("운영체제 1강: 프로세스/스레드") == "운영체제-1강-프로세스-스레드"
    assert cli.slugify("   ") == "video"
    assert cli.slugify("a" * 200).startswith("a") and len(cli.slugify("a" * 200)) <= 80


def test_output_dir_for():
    assert cli.output_dir_for("./output", "OS Lecture") == os.path.join("./output", "OS-Lecture")




def test_parse_args_single_and_mixed_batch():
    source = cli.parse_args(["https://youtu.be/abc"])
    assert source.sources == ["https://youtu.be/abc"]
    assert source.force_stt is False and source.model == "medium"
    assert source.keep_frames is False and source.skip_ocr is False
    batch = cli.parse_args([
        "u1", "./lecture.mp4", "sound.wav", "--force-stt", "--model", "small",
        "--out", "./o", "--keep-frames", "--skip-ocr",
    ])
    assert batch.sources == ["u1", "./lecture.mp4", "sound.wav"]
    assert batch.force_stt is True and batch.model == "small" and batch.out == "./o"
    assert batch.keep_frames is True and batch.skip_ocr is True


def test_parse_args_doctor_command():
    args = cli.parse_args(["doctor", "--fix", "--json"])
    assert args.command == "doctor" and args.fix is True and args.json is True


def test_help_works_for_root_and_doctor():
    with pytest.raises(SystemExit) as root_exit:
        cli.parse_args(["--help"])
    assert root_exit.value.code == 0
    with pytest.raises(SystemExit) as doctor_exit:
        cli.parse_args(["doctor", "--help"])
    assert doctor_exit.value.code == 0


def _fake_processor(source, out_dir, force_stt, model, *, keep_frames=False, skip_ocr=False):
    return {
        "output_dir": f"./output/{source[-1]}",
        "coverage_json": f"./output/{source[-1]}/coverage.json",
        "notes_md": f"./output/{source[-1]}/notes.md",
        "transcript_md": f"./output/{source[-1]}/transcript.md",
        "overall_pass": True,
        "received": (source, force_stt, model, keep_frames, skip_ocr),
    }


def test_run_mixed_sources_preserves_order_and_source_state(tmp_path):
    rs = tmp_path / "runstate.json"
    results = cli.run(["u-A", "./lecture.mp4", "sound.wav"], processor=_fake_processor, runstate_file=str(rs), skip_ocr=True)
    assert [result["received"][0] for result in results] == ["u-A", "./lecture.mp4", "sound.wav"]
    assert all(result["received"][-1] is True for result in results)
    state = json.loads(rs.read_text(encoding="utf-8"))
    assert [entry["source"] for entry in state["runs"]] == ["u-A", "./lecture.mp4", "sound.wav"]
    assert all("url" not in entry for entry in state["runs"])


def test_run_continues_after_one_source_failure(tmp_path):
    rs = tmp_path / "runstate.json"
    calls = []

    def processor(source, out_dir, force_stt, model):
        calls.append(source)
        if source == "bad":
            raise RuntimeError("boom")
        return {"output_dir": out_dir, "coverage_json": "c", "notes_md": "n", "transcript_md": "t", "overall_pass": True}

    results = cli.run(["good", "bad", "last"], processor=processor, runstate_file=str(rs))
    assert calls == ["good", "bad", "last"]
    assert results[1]["source"] == "bad" and results[1]["overall_pass"] is False
    state = json.loads(rs.read_text(encoding="utf-8"))
    assert [entry["status"] for entry in state["runs"]] == ["complete", "failed", "complete"]


def test_main_forwards_skip_ocr_and_exit_code(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "run", lambda *args, **kwargs: captured.update(kwargs) or [{"output_dir": "x", "overall_pass": True}])
    assert cli.main(["./deck.mp4", "--skip-ocr"]) == 0
    assert captured["skip_ocr"] is True
    monkeypatch.setattr(cli, "run", lambda *args, **kwargs: [{"output_dir": "x", "overall_pass": False}])
    assert cli.main(["./deck.mp4"]) == 2


_DEFAULT_DURATION = object()


def _install_default_processor_fakes(
    monkeypatch,
    tmp_path: Path,
    *,
    title: str,
    duration: float,
    source_kind: SourceKind,
    metadata_duration: object = _DEFAULT_DURATION,
    stt_duration: object = _DEFAULT_DURATION,
):
    if metadata_duration is _DEFAULT_DURATION:
        metadata_duration = duration
    if stt_duration is _DEFAULT_DURATION:
        stt_duration = duration
    calls = []
    monkeypatch.setattr(
        media,
        "probe_source",
        lambda source: media.SourceMetadata(
            title,
            metadata_duration,
            "dQw4w9WgXcQ" if source_kind is SourceKind.YOUTUBE else None,
        ),
    )

    def fake_acquire(source, out_dir, force_stt=False, model="medium"):
        calls.append(("acquire", source, out_dir, force_stt, model))
        audio = Path(out_dir) / "audio.wav"
        audio.write_bytes(b"audio")
        return acquisition.SpeechTrack(
            [acquisition.Segment(0.0, "첫 번째 문장입니다"), acquisition.Segment(30.0, "두 번째 문장입니다"), acquisition.Segment(60.0, "세 번째 문장입니다")],
            "caption" if source_kind is SourceKind.YOUTUBE else "stt",
            meta={"audio_path": str(audio), "duration": stt_duration},
        )

    monkeypatch.setattr(acquisition, "acquire_speech", fake_acquire)
    monkeypatch.setattr(media, "probe_video_resolution", lambda _path: (1280, 720))
    if source_kind is not SourceKind.LOCAL_AUDIO:
        monkeypatch.setattr(media, "resolve_video", lambda source, out_dir: calls.append(("video", source, out_dir)) or source.locator)

        def fake_extract(video_path, frames_dir):
            calls.append(("extract", video_path, frames_dir))
            Path(frames_dir).mkdir(parents=True, exist_ok=True)
            frames = []
            for index, timestamp in ((1, 0.0), (2, 30.0), (3, 60.0)):
                path = Path(frames_dir) / f"frame_{index:05d}.png"
                path.write_bytes(f"raw {index}".encode())
                frames.append(visual.Frame(timestamp, str(path)))
            return frames

        monkeypatch.setattr(visual, "extract_candidate_frames", fake_extract)
        monkeypatch.setattr(visual, "dedupe_frames", lambda frames: [frames[0], frames[-1]])

        def fake_ocr(frames):
            for frame in frames:
                frame.ocr_text = "슬라이드 제목"
                frame.is_slide = True
            return frames, "paddleocr"

        monkeypatch.setattr("lectural.ocr.ocr_frames", fake_ocr)
    monkeypatch.setattr(vad, "detect_speech_spans", lambda audio, duration: [(0.0, duration)])
    return calls


def test_extract_then_notes_youtube_uses_ocr_and_youtube_citation(monkeypatch, tmp_path):
    calls = _install_default_processor_fakes(monkeypatch, tmp_path, title="운영체제 1강", duration=120.0, source_kind=SourceKind.YOUTUBE)
    result = cli._extract_then_notes_processor("https://youtu.be/dQw4w9WgXcQ", str(tmp_path / "video_01"), False, "tiny")
    out = Path(result["output_dir"])
    assert result["output_dir"] == str(tmp_path / "운영체제-1강")
    assert calls[0][1].kind is SourceKind.YOUTUBE
    assert (out / "synthesis_input.json").exists()
    handoff = json.loads((out / "synthesis_input.json").read_text(encoding="utf-8"))
    assert handoff["schema_version"] == 2
    assert handoff["video"]["speech_source"] == "caption"
    assert handoff["video"]["input_source"]["citation"] == {"kind": "youtube", "video_id": "dQw4w9WgXcQ"}
    assert "영상 딥링크" in (out / "notes.md").read_text(encoding="utf-8")


def test_extract_then_notes_local_video_skip_ocr_keeps_deduplicated_frames(monkeypatch, tmp_path):
    calls = _install_default_processor_fakes(monkeypatch, tmp_path, title="deck", duration=120.0, source_kind=SourceKind.LOCAL_VIDEO)
    monkeypatch.setattr("lectural.ocr.ocr_frames", lambda *_args: (_ for _ in ()).throw(AssertionError("OCR called")))
    source_path = tmp_path / "deck.mp4"
    source_path.write_bytes(b"source")
    result = cli._extract_then_notes_processor(str(source_path), str(tmp_path / "video_01"), False, "tiny", skip_ocr=True)
    out = Path(result["output_dir"])
    handoff = json.loads((out / "synthesis_input.json").read_text(encoding="utf-8"))
    coverage_payload = json.loads((out / "coverage.json").read_text(encoding="utf-8"))
    assert coverage_payload["ocr_engine"] == "skipped"
    assert coverage_payload["scene_coverage"]["ocr_required"] is False
    assert coverage_payload["scene_coverage"]["slide_frames_total"] == 2
    assert coverage_payload["scene_coverage"]["slide_frames_with_text"] == 0
    assert handoff["video"]["input_source"]["citation"] == {"kind": "transcript"}
    notes = (out / "notes.md").read_text(encoding="utf-8")
    assert notes.count("frames/frame_") >= 2
    assert all(path.exists() for path in (out / "frames").glob("frame_*.png"))
    assert source_path.read_bytes() == b"source"
    assert calls[0][1].kind is SourceKind.LOCAL_VIDEO


def test_reliability_gates_synthesis_but_preserves_evidence(monkeypatch, tmp_path):
    calls = _install_default_processor_fakes(monkeypatch, tmp_path, title="deck", duration=120.0, source_kind=SourceKind.LOCAL_VIDEO)
    source_path = tmp_path / "deck.mp4"
    source_path.write_bytes(b"source")

    def fake_ocr(frames):
        for frame in frames:
            frame.ocr_text = "Low confidence slide text"
            frame.ocr_confidence = 0.1
            frame.is_slide = True
        return frames, "paddleocr"

    monkeypatch.setattr("lectural.ocr.ocr_frames", fake_ocr)
    result = cli._extract_then_notes_processor(str(source_path), str(tmp_path / "video_01"), False, "tiny")
    handoff = json.loads((Path(result["output_dir"]) / "synthesis_input.json").read_text(encoding="utf-8"))
    frames = result["manifest"]["frames"]
    assert all(not slide["ocr_text"] for slide in handoff["slides"])
    assert all(frame["ocr"]["reliable"] is False for frame in frames)
    assert all(frame["ocr"]["text"] for frame in frames)
    assert calls[0][1].kind is SourceKind.LOCAL_VIDEO


def test_local_wav_processor_skips_visual_and_has_not_applicable_scene(monkeypatch, tmp_path):
    path = tmp_path / "recording.wav"
    path.write_bytes(b"source")
    _install_default_processor_fakes(monkeypatch, tmp_path, title="recording", duration=30.0, source_kind=SourceKind.LOCAL_AUDIO)
    monkeypatch.setattr(visual, "extract_candidate_frames", lambda *_args: (_ for _ in ()).throw(AssertionError("visual called")))
    result = cli._extract_then_notes_processor(str(path), str(tmp_path / "video_01"), False, "tiny", skip_ocr=True)
    out = Path(result["output_dir"])
    coverage_payload = json.loads((out / "coverage.json").read_text(encoding="utf-8"))
    assert coverage_payload["scene_coverage"]["visual_required"] is False
    assert coverage_payload["scene_coverage"]["timeline_pass"] is True
    notes = (out / "notes.md").read_text(encoding="utf-8")
    assert "### 전체" in notes and "Scene coverage: not applicable (audio source)" in notes
    assert "frames/" not in notes


def test_local_wav_processor_keeps_visual_coverage_not_applicable_without_duration(
    monkeypatch, tmp_path
):
    path = tmp_path / "recording.wav"
    path.write_bytes(b"source")
    _install_default_processor_fakes(
        monkeypatch,
        tmp_path,
        title="recording",
        duration=0.0,
        source_kind=SourceKind.LOCAL_AUDIO,
        metadata_duration=None,
        stt_duration=float("nan"),
    )
    monkeypatch.setattr(
        visual,
        "extract_candidate_frames",
        lambda *_args: (_ for _ in ()).throw(AssertionError("visual called")),
    )
    result = cli._extract_then_notes_processor(
        str(path), str(tmp_path / "video_01"), False, "tiny", skip_ocr=True
    )
    coverage_payload = json.loads(
        (Path(result["output_dir"]) / "coverage.json").read_text(encoding="utf-8")
    )

    assert coverage_payload["duration_sec"] == 0.0
    assert coverage_payload["scene_coverage"]["duration_valid"] is False
    assert coverage_payload["scene_coverage"]["visual_required"] is False
    assert coverage_payload["scene_coverage"]["timeline_pass"] is True
    assert coverage_payload["scene_coverage"]["pass"] is True
    assert result["overall_pass"] is True


@pytest.mark.parametrize(
    "metadata_duration",
    [None, float("nan")],
    ids=["missing-metadata", "invalid-metadata"],
)
def test_default_video_processor_uses_valid_stt_duration_when_metadata_is_unusable(
    monkeypatch, tmp_path, metadata_duration
):
    _install_default_processor_fakes(
        monkeypatch,
        tmp_path,
        title="deck",
        duration=42.0,
        source_kind=SourceKind.LOCAL_VIDEO,
        metadata_duration=metadata_duration,
        stt_duration=42.0,
    )
    source_path = tmp_path / "deck.mp4"
    source_path.write_bytes(b"source")
    result = cli._extract_then_notes_processor(
        str(source_path), str(tmp_path / "video_01"), False, "tiny", skip_ocr=True
    )
    coverage_payload = json.loads(
        (Path(result["output_dir"]) / "coverage.json").read_text(encoding="utf-8")
    )

    assert coverage_payload["duration_sec"] == 42.0
    assert coverage_payload["scene_coverage"]["duration_valid"] is True


@pytest.mark.parametrize(
    ("metadata_duration", "stt_duration"),
    [(None, 0.0), (float("nan"), float("inf"))],
    ids=["missing-and-zero", "nan-and-infinity"],
)
def test_default_video_processor_fails_closed_when_both_durations_are_invalid(
    monkeypatch, tmp_path, metadata_duration, stt_duration
):
    _install_default_processor_fakes(
        monkeypatch,
        tmp_path,
        title="deck",
        duration=0.0,
        source_kind=SourceKind.LOCAL_VIDEO,
        metadata_duration=metadata_duration,
        stt_duration=stt_duration,
    )
    source_path = tmp_path / "deck.mp4"
    source_path.write_bytes(b"source")
    result = cli._extract_then_notes_processor(
        str(source_path), str(tmp_path / "video_01"), False, "tiny", skip_ocr=True
    )
    coverage_payload = json.loads(
        (Path(result["output_dir"]) / "coverage.json").read_text(encoding="utf-8")
    )

    assert result["overall_pass"] is False
    assert coverage_payload["duration_sec"] == 0.0
    assert coverage_payload["scene_coverage"]["duration_valid"] is False
    assert coverage_payload["scene_coverage"]["timeline_pass"] is False


def test_run_default_processor_suffixes_existing_and_reserved_mixed_sources(monkeypatch, tmp_path):
    audio_path = tmp_path / "audio" / "lecture.wav"
    video_path = tmp_path / "video" / "lecture.mp4"
    audio_path.parent.mkdir()
    video_path.parent.mkdir()
    audio_path.write_bytes(b"audio")
    video_path.write_bytes(b"video")

    out_root = tmp_path / "output"
    (out_root / "Lecture-Intro").mkdir(parents=True)
    runstate_path = tmp_path / "runstate.json"

    monkeypatch.setattr(
        media,
        "probe_source",
        lambda source: media.SourceMetadata("Lecture / Intro", 30.0, None),
    )

    def fake_acquire(source, out_dir, force_stt=False, model="medium"):
        audio = Path(out_dir) / "audio.wav"
        audio.write_bytes(b"generated audio")
        return acquisition.SpeechTrack(
            [acquisition.Segment(0.0, "첫 번째 문장입니다")],
            "stt",
            meta={"audio_path": str(audio), "duration": 30.0},
        )

    monkeypatch.setattr(acquisition, "acquire_speech", fake_acquire)
    monkeypatch.setattr(media, "probe_video_resolution", lambda _path: (1280, 720))
    monkeypatch.setattr(media, "resolve_video", lambda source, out_dir: source.locator)

    def fake_extract(video, frames_dir):
        frames_dir = Path(frames_dir)
        frames_dir.mkdir(parents=True, exist_ok=True)
        frame_path = frames_dir / "frame_00001.png"
        frame_path.write_bytes(b"frame")
        return [visual.Frame(0.0, str(frame_path))]

    monkeypatch.setattr(visual, "extract_candidate_frames", fake_extract)
    monkeypatch.setattr(visual, "dedupe_frames", lambda frames: frames[:1])
    monkeypatch.setattr(vad, "detect_speech_spans", lambda audio, duration: [(0.0, duration)])

    results = cli.run(
        [str(audio_path), str(video_path)],
        out_root=str(out_root),
        runstate_file=str(runstate_path),
        skip_ocr=True,
    )
    state = json.loads(runstate_path.read_text(encoding="utf-8"))

    assert [Path(result["output_dir"]).name for result in results] == [
        "Lecture-Intro-2",
        "Lecture-Intro-3",
    ]
    assert len({result["output_dir"] for result in results}) == 2
    assert all(result["overall_pass"] for result in results)
    for result, entry in zip(results, state["runs"]):
        assert entry["status"] == "complete"
        assert entry["output_dir"] == result["output_dir"]
        assert entry["coverage_json"] == result["coverage_json"]
        assert entry["notes_md"] == result["notes_md"]
        assert Path(result["coverage_json"]).is_file()
        assert Path(result["notes_md"]).is_file()


def test_main_dispatches_doctor_json(monkeypatch, capsys):
    report = {"schema_version": 1, "items": [], "overall_status": "ready", "exit_code": 0}
    monkeypatch.setattr(doctor, "run", lambda fix=False: report)
    monkeypatch.setattr(doctor, "print_report", lambda actual, json_output=False: print("json" if json_output else "text"))
    assert cli.main(["doctor", "--json"]) == 0
    assert capsys.readouterr().out.strip() == "json"
