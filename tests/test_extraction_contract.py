"""Consumer-facing version negotiation and extraction contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lectural import acquisition, cli, evidence, media, vad, visual


def _coverage(out: Path, *, overall_pass: bool = True, visual: bool = True, ocr_failed: bool = False) -> dict:
    transcript = out / "transcript.md"
    notes = out / "notes.md"
    return {
        "schema_version": 2,
        "duration_sec": 20.0,
        "overall_pass": overall_pass,
        "gap_check": {
            "max_untranscribed_speech_gap_sec": 0 if overall_pass else 61,
            "threshold_sec": 60,
            "pass": overall_pass,
        },
        "scene_coverage": {
            "visual_required": visual,
            "ocr_required": visual and not ocr_failed,
            "ocr_failed": ocr_failed,
            "timeline_pass": overall_pass if visual else True,
            "slide_text_pass": overall_pass if visual and not ocr_failed else not ocr_failed,
            "speech_bins": [0] if visual else [],
            "covered_speech_bins": [0] if visual else [],
            "uncovered_speech_bins": [] if overall_pass else [1],
        },
        "artifacts": {
            "pass": True,
            "transcript_nonempty": True,
            "notes_nonempty": True,
            "transcript_md": str(transcript),
            "notes_md": str(notes),
        },
        "notes_contract": {"pass": True},
    }


def _fake_result(output_dir: Path, *, ocr_status: str = "skipped", overall_pass: bool = True) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript = output_dir / "transcript.md"
    notes = output_dir / "notes.md"
    synthesis = output_dir / "synthesis_input.json"
    coverage = output_dir / "coverage.json"
    frames = output_dir / "frames"
    frame = frames / "frame_00001.png"
    frames.mkdir()
    frame.write_bytes(b"frame")
    for path in (transcript, notes, synthesis, coverage):
        path.write_text("{}", encoding="utf-8")
    has_text = ocr_status == "completed-with-text"
    failed = ocr_status == "failed"
    return {
        "output_dir": str(output_dir),
        "coverage_json": str(coverage),
        "notes_md": str(notes),
        "transcript_md": str(transcript),
        "synthesis_input_json": str(synthesis),
        "source": {
            "kind": "local_video",
            "argument": "lecture.mp4",
            "has_video": True,
            "citation": {"kind": "transcript"},
            "resolution": {"width": 1280, "height": 720},
        },
        "source_kind": "local_video",
        "coverage": _coverage(output_dir, overall_pass=overall_pass, ocr_failed=failed),
        "transcript_segments": [{"t": 0.0, "text": "hello"}],
        "representative_frames": [{
            "timestamp_sec": 1.0,
            "path": str(frame),
            "ocr_text": "Slide title" if has_text else "",
            "is_slide": has_text,
            "reliable": True if has_text else None,
            "width": 1280,
            "height": 720,
        }],
        "frames_dir": str(frames),
        "ocr_status": ocr_status,
        "ocr_engine": "paddleocr" if ocr_status.startswith("completed") else ocr_status,
        "ocr_failed": failed,
        "overall_pass": overall_pass and not failed,
    }


def test_version_json_is_negotiable_and_stdout_is_one_document(capsys):
    assert cli.main(["--version", "--json"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.out.lstrip().startswith("{")
    assert payload["tool"] == "lectural"
    assert payload["result"]["supported_contract_versions"] == [1]
    assert payload["result"]["supported_schema_versions"] == [1]
    assert captured.err == ""


@pytest.mark.parametrize(
    ("ocr_status", "expected_envelope", "expected_exit"),
    [
        ("skipped", "ok", 0),
        ("completed-no-text", "ok", 0),
        ("completed-with-text", "ok", 0),
        ("failed", "error", 1),
    ],
)
def test_extract_reports_all_ocr_states_and_retains_frame(
    monkeypatch, tmp_path: Path, capsys, ocr_status, expected_envelope, expected_exit
):
    source = tmp_path / "lecture.mp4"
    source.write_bytes(b"source")
    out = tmp_path / f"out-{ocr_status}"
    result_holder = {}

    def fake_processor(*_args, exact_output_dir=None, **_kwargs):
        result = _fake_result(Path(exact_output_dir), ocr_status=ocr_status, overall_pass=ocr_status != "failed")
        result_holder["result"] = result
        return result

    monkeypatch.setattr(cli, "_default_processor", fake_processor)
    assert cli.main(["extract", str(source), "--out", str(out), "--json"]) == expected_exit
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == expected_envelope
    manifest = payload["result"]
    assert manifest["extraction"]["ocr"]["status"] == ocr_status
    frame_path = Path(manifest["representative_frames"][0]["path"])
    assert frame_path.is_file()
    assert frame_path.is_relative_to(out)
    assert Path(manifest["artifacts"]["evidence"]).is_file()
    assert "code_scene" not in json.dumps(payload)
    assert "build_eligibility" not in json.dumps(payload)
    assert "resolution" in manifest["source"]


def test_extract_warns_on_incomplete_coverage_and_keeps_stdout_json(monkeypatch, tmp_path: Path, capsys):
    source = tmp_path / "lecture.wav"
    source.write_bytes(b"source")
    out = tmp_path / "warn"

    def fake_processor(*_args, exact_output_dir=None, **_kwargs):
        result = _fake_result(Path(exact_output_dir), ocr_status="skipped", overall_pass=False)
        result["coverage"] = _coverage(Path(exact_output_dir), overall_pass=False, visual=False)
        return result

    monkeypatch.setattr(cli, "_default_processor", fake_processor)
    assert cli.main(["extract", str(source), "--out", str(out), "--skip-ocr", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "partial"
    assert payload["result"]["status"] == "warn"
    assert any(error["code"] == "SPEECH_INCOMPLETE" for error in payload["errors"])


def test_safe_source_preserves_only_nullable_resolution():
    source = evidence._safe_source({
        "kind": "local_video", "argument": "C:/private/deck.mp4", "has_video": True,
        "citation": {"kind": "transcript"},
        "resolution": {"width": 1280, "height": 720, "secret": "discard"},
    })
    assert source["resolution"] == {"width": 1280, "height": 720}
    assert evidence._safe_source({"kind": "local_audio", "resolution": {"width": 0}})["resolution"] == {"width": None, "height": None}


def test_existing_output_is_rejected_as_bounded_json_failure(tmp_path: Path, capsys):
    source = tmp_path / "lecture.wav"
    source.write_bytes(b"source")
    out = tmp_path / "existing"
    out.mkdir()
    assert cli.main(["extract", str(source), "--out", str(out), "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["failure"]["code"] == "OUTPUT_EXISTS"
    assert payload["result"]["output_dir"] is None


def test_path_containment_rejects_escape_and_timestamp_invalid():
    root = Path("C:/safe/out")
    assert not evidence.is_contained(str(root), "C:/safe/outside/frame.png")
    assert evidence.timestamp_integrity(
        10,
        [{"t": 11, "text": "late"}],
        [{"timestamp_sec": 1, "path": "frame.png"}],
    )["status"] == "fail"


def test_extract_redirects_processor_stdout_to_stderr(monkeypatch, tmp_path: Path, capsys):
    source = tmp_path / "lecture.wav"
    source.write_bytes(b"source")
    out = tmp_path / "quiet"

    def fake_processor(*_args, exact_output_dir=None, **_kwargs):
        print("internal diagnostic")
        return _fake_result(Path(exact_output_dir), ocr_status="skipped")

    monkeypatch.setattr(cli, "_default_processor", fake_processor)
    assert cli.main(["extract", str(source), "--out", str(out), "--json"]) == 0
    captured = capsys.readouterr()
    json.loads(captured.out)
    assert "internal diagnostic" not in captured.out
    assert "internal diagnostic" in captured.err


def test_pipeline_ocr_failure_keeps_representative_frame(monkeypatch, tmp_path: Path):
    source_path = tmp_path / "deck.mp4"
    source_path.write_bytes(b"source")
    out = tmp_path / "out"
    out.mkdir()

    monkeypatch.setattr(media, "probe_source", lambda _source: media.SourceMetadata("deck", 20.0, None))

    def fake_acquire(_source, output, force_stt=False, model="medium"):
        audio = Path(output) / "audio.wav"
        audio.write_bytes(b"audio")
        return acquisition.SpeechTrack(
            [acquisition.Segment(0.0, "spoken")],
            "stt",
            meta={"audio_path": str(audio), "duration": 20.0},
        )

    monkeypatch.setattr(acquisition, "acquire_speech", fake_acquire)
    monkeypatch.setattr(media, "resolve_video", lambda _source, _output: str(source_path))
    monkeypatch.setattr(media, "probe_video_resolution", lambda _video: (1280, 720))

    def fake_extract(_video, frames_dir):
        frame_path = Path(frames_dir) / "frame_00001.png"
        frame_path.write_bytes(b"frame")
        return [visual.Frame(1.0, str(frame_path))]

    monkeypatch.setattr(visual, "extract_candidate_frames", fake_extract)
    monkeypatch.setattr(visual, "dedupe_frames", lambda frames: frames)
    monkeypatch.setattr("lectural.ocr.ocr_frames", lambda _frames: (_ for _ in ()).throw(RuntimeError("secret")))
    monkeypatch.setattr(vad, "detect_speech_spans", lambda _audio, duration: [(0.0, duration)])

    result = cli._default_processor(
        str(source_path), str(out), False, "tiny", exact_output_dir=str(out)
    )
    assert result["ocr_status"] == "failed"
    assert result["ocr_failed"] is True
    assert Path(result["representative_frames"][0]["path"]).is_file()
    assert json.loads((out / "coverage.json").read_text(encoding="utf-8"))["scene_coverage"]["ocr_failed"] is True
