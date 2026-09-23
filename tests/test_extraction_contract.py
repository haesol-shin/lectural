"""Consumer-facing v2 negotiation, extraction, and evidence-bundle tests."""

from __future__ import annotations

import builtins
import hashlib
import json
from pathlib import Path
import shutil


from lectural import acquisition, cli, evidence, media, notes, speech, vad, visual


SCHEMA_PATH = Path("docs/contracts/evidence.schema.json")
FALLBACK_CODES = {"captions_unavailable", "captions_unusable", "forced_stt", "local_source"}


def _install_fake_pipeline(monkeypatch, tmp_path: Path, *, audio_only: bool = False, duration: float = 20.0, ocr: str = "completed-with-text") -> Path:
    source_path = tmp_path / ("recording.wav" if audio_only else "lecture.mp4")
    source_path.write_bytes(b"input-media")
    monkeypatch.setattr(media, "probe_source", lambda _source: media.SourceMetadata("Lecture", duration, None))

    def fake_acquire(source, out_dir, force_stt=False, model="medium"):
        audio = Path(out_dir) / "audio.wav"
        audio.write_bytes(b"audio")
        return acquisition.SpeechTrack(
            [
                acquisition.Segment(0.0, "First sentence", end=min(4.0, duration)),
                acquisition.Segment(min(5.0, duration), "Second sentence", end=duration),
            ],
            "stt",
            language="en",
            meta={"audio_path": str(audio), "duration": duration, "model": model, "fallback_code": "local_source"},
        )

    monkeypatch.setattr(acquisition, "acquire_speech", fake_acquire)
    monkeypatch.setattr(vad, "detect_speech_spans", lambda _audio, length: [(0.0, length)] if length > 0 else [])
    monkeypatch.setattr(media, "probe_video_resolution", lambda _path: (640, 360))
    monkeypatch.setattr(media, "resolve_video", lambda _source, _out: str(tmp_path / "video.bin"))

    def fake_frames(_video, frames_dir):
        root = Path(frames_dir)
        root.mkdir(parents=True, exist_ok=True)
        frames = []
        for index, stamp in enumerate((1.0, min(10.0, duration)), start=1):
            path = root / f"frame_{index:05d}.png"
            path.write_bytes(f"frame-{index}".encode())
            frames.append(visual.Frame(stamp, str(path), meta={"width": 640, "height": 360}))
        return frames

    monkeypatch.setattr(visual, "extract_candidate_frames", fake_frames)
    monkeypatch.setattr(visual, "dedupe_frames", lambda frames: list(frames))

    def fake_ocr(frames):
        if ocr == "failed":
            raise RuntimeError("private OCR details")
        if ocr == "completed-with-text":
            for index, frame in enumerate(frames, start=1):
                frame.ocr_text = f"Slide title {index} contains enough text"
                frame.ocr_confidence = 0.99
                frame.is_slide = True
            return frames, "paddleocr"
        for frame in frames:
            frame.ocr_text = ""
            frame.is_slide = False
        return [], "paddleocr"

    monkeypatch.setattr("lectural.ocr.ocr_frames", fake_ocr)
    return source_path


def _invoke_cli(argv: list[str]) -> tuple[int, str]:
    from contextlib import redirect_stdout
    from io import StringIO
    stream = StringIO()
    with redirect_stdout(stream):
        exit_code = cli.main(argv)
    return exit_code, stream.getvalue()


def _run_extract(monkeypatch, tmp_path: Path, *, audio_only: bool = False, duration: float = 20.0, ocr: str = "completed-with-text", skip_ocr: bool = False):
    source_path = _install_fake_pipeline(monkeypatch, tmp_path, audio_only=audio_only, duration=duration, ocr=ocr)
    output_dir = tmp_path / "bundle"
    argv = ["extract", str(source_path), "--out", str(output_dir), "--json"]
    if skip_ocr:
        argv.append("--skip-ocr")
    exit_code, stdout = _invoke_cli(argv)
    return source_path, output_dir, exit_code, json.loads(stdout)

def _validate_evidence_shape(manifest: dict, schema: dict) -> None:
    assert set(manifest) == set(schema["required"])
    for key in ("schema_version", "contract_version", "tool"):
        assert manifest[key] == schema["properties"][key]["const"]
    assert set(manifest["source"]) == set(schema["$defs"]["source"]["required"])
    assert set(manifest["speech"]) == set(schema["$defs"]["speech"]["required"])
    assert set(manifest["transcript"]) == {"segments"}
    assert set(manifest["artifacts"]) == set(schema["$defs"]["artifacts"]["required"])
    assert set(manifest["resources"]) == set(schema["$defs"]["resources"]["required"])
    assert set(manifest["extraction"]) == set(schema["$defs"]["extraction"]["required"])
    for segment in manifest["transcript"]["segments"]:
        assert set(segment) == set(schema["$defs"]["segment"]["required"])
        assert 0 <= segment["start"] <= segment["end"] <= manifest["source"]["duration_sec"] + 0.001
    for frame in manifest["frames"]:
        assert set(frame) == set(schema["$defs"]["frame"]["required"])
        assert set(frame["ocr"]) == set(schema["$defs"]["frame"]["properties"]["ocr"]["required"])


def test_version_json_negotiates_only_contract_and_schema_v2():
    exit_code, stdout = _invoke_cli(["--version", "--json"])
    assert exit_code == 0
    payload = json.loads(stdout)
    assert payload["result"]["supported_contract_versions"] == [2]
    assert payload["result"]["supported_schema_versions"] == [2]


def test_extract_emits_v2_evidence_ids_hashes_and_local_source_identity(monkeypatch, tmp_path):
    source_path, output_dir, exit_code, payload = _run_extract(monkeypatch, tmp_path)
    assert exit_code == 0
    manifest = payload["result"]
    segments = manifest["transcript"]["segments"]
    frames = manifest["frames"]
    assert [segment["id"] for segment in segments] == ["s0001", "s0002"]
    assert [frame["id"] for frame in frames] == ["f0001", "f0002"]
    assert len({segment["id"] for segment in segments}) == len(segments)
    assert len({frame["id"] for frame in frames}) == len(frames)
    assert [item["start"] for item in segments] == sorted(item["start"] for item in segments)
    assert [item["start"] for item in frames] == sorted(item["start"] for item in frames)
    assert manifest["source"]["id"] == "sha256:" + hashlib.sha256(source_path.read_bytes()).hexdigest()
    for frame in frames:
        assert frame["sha256"] == hashlib.sha256(Path(frame["path"]).read_bytes()).hexdigest()
    assert set(manifest["artifacts"]) == {"evidence", "transcript", "frames_dir", "output_dir"}
    assert not set(manifest) & {"representative_frames", "source_kind", "status", "extraction_status"}
    assert not set(manifest["artifacts"]) & {"notes", "synthesis_input", "coverage", "notes_md", "synthesis_input_json", "coverage_json"}
    assert Path(manifest["artifacts"]["evidence"]).is_file()
    assert Path(manifest["artifacts"]["transcript"]).is_file()
    assert not any((output_dir / name).exists() for name in ("notes.md", "synthesis_input.json", "coverage.json"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    _validate_evidence_shape(manifest, schema)


def test_extract_has_resources_and_missing_psutil_does_not_change_status(monkeypatch, tmp_path):
    source_path = _install_fake_pipeline(monkeypatch, tmp_path, audio_only=True)
    first_out = tmp_path / "normal"
    baseline_exit, baseline_text = _invoke_cli(["extract", str(source_path), "--out", str(first_out), "--json"])
    assert baseline_exit == 0
    baseline = json.loads(baseline_text)["result"]
    assert baseline["resources"]["wall_sec"] >= 0
    assert set(baseline["resources"]["stages"]) == {"speech", "frames", "dedupe", "ocr"}
    assert baseline["resources"]["frames_retained"] == 0

    original_import = builtins.__import__

    def without_psutil(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("psutil intentionally unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_psutil)
    second_out = tmp_path / "without-psutil"
    second_exit, second_text = _invoke_cli(["extract", str(source_path), "--out", str(second_out), "--json"])
    assert second_exit == 0
    measured = json.loads(second_text)["result"]
    assert measured["resources"]["peak_rss_mb"] is None
    assert measured["extraction"]["status"] == baseline["extraction"]["status"] == "pass"


def test_extract_keeps_frame_on_ocr_failure_and_emits_fail_status(monkeypatch, tmp_path):
    _source, _output, exit_code, payload = _run_extract(monkeypatch, tmp_path, ocr="failed")
    assert exit_code == 1
    manifest = payload["result"]
    assert manifest["extraction"]["status"] == "fail"
    assert manifest["extraction"]["ocr"]["status"] == "failed"
    assert all(Path(frame["path"]).is_file() for frame in manifest["frames"])
    assert all(frame["ocr"]["status"] == "failed" for frame in manifest["frames"])


def test_extract_warning_is_not_a_notes_contract_failure(monkeypatch, tmp_path):
    source_path = _install_fake_pipeline(monkeypatch, tmp_path, audio_only=True, duration=200.0)
    monkeypatch.setattr(vad, "detect_speech_spans", lambda _audio, duration: [(0.0, duration)])
    monkeypatch.setattr(acquisition, "acquire_speech", lambda _source, output, **_kwargs: acquisition.SpeechTrack(
        [acquisition.Segment(0.0, "Only one cue", end=1.0)], "stt", language="en",
        meta={"audio_path": str(source_path), "duration": 200.0, "model": "tiny", "fallback_code": "local_source"},
    ))
    output = tmp_path / "warn"
    exit_code, stdout = _invoke_cli(["extract", str(source_path), "--out", str(output), "--json"])
    assert exit_code == 1
    manifest = json.loads(stdout)["result"]
    assert manifest["extraction"]["status"] == "warn"
    assert "NOTES_CONTRACT_INVALID" not in {item["code"] for item in manifest["extraction"]["reasons"]}
    assert not (output / "notes.md").exists()


def test_bounded_caption_fallback_excludes_exception_text_from_json(monkeypatch, tmp_path):
    monkeypatch.setattr(media, "probe_source", lambda _source: media.SourceMetadata("Lecture", 20.0, "dQw4w9WgXcQ"))
    monkeypatch.setattr(acquisition, "fetch_caption_segments", lambda *_args: (_ for _ in ()).throw(RuntimeError("secret-token=private-value")))

    def resolve_audio(_source, output):
        audio = Path(output) / "audio.wav"
        audio.write_bytes(b"audio")
        return str(audio)

    monkeypatch.setattr(media, "resolve_audio", resolve_audio)
    monkeypatch.setattr(speech, "transcribe_audio", lambda path, model_size: acquisition.SpeechTrack(
        [acquisition.Segment(0.0, "A transcript segment", end=20.0)], "stt", language="en",
        meta={"audio_path": path, "duration": 20.0, "model": model_size},
    ))
    monkeypatch.setattr(media, "resolve_video", lambda _source, _out: str(tmp_path / "video.bin"))
    monkeypatch.setattr(media, "probe_video_resolution", lambda _video: (640, 360))

    def fake_frame(_video, frames_dir):
        root = Path(frames_dir)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "frame_00001.png"
        path.write_bytes(b"frame")
        return [visual.Frame(0.0, str(path))]

    monkeypatch.setattr(visual, "extract_candidate_frames", fake_frame)
    monkeypatch.setattr(visual, "dedupe_frames", lambda frames: frames)
    monkeypatch.setattr(vad, "detect_speech_spans", lambda _audio, duration: [(0.0, duration)])
    output = tmp_path / "youtube"
    exit_code, serialized = _invoke_cli(["extract", "https://youtu.be/dQw4w9WgXcQ", "--out", str(output), "--skip-ocr", "--json"])
    assert exit_code == 0
    manifest = json.loads(serialized)["result"]
    assert manifest["speech"]["fallback"] == {"code": "captions_unavailable"}
    assert "secret-token=private-value" not in serialized


def test_notes_generate_from_bundle_containing_only_manifest_transcript_and_frames(monkeypatch, tmp_path):
    _source_path, original, exit_code, payload = _run_extract(monkeypatch, tmp_path)
    assert exit_code == 0
    manifest = payload["result"]
    bundle = tmp_path / "portable-bundle"
    (bundle / "frames").mkdir(parents=True)
    transcript = Path(manifest["artifacts"]["transcript"])
    shutil.copyfile(transcript, bundle / "transcript.md")
    manifest["artifacts"].update({
        "evidence": str(bundle / "evidence.json"),
        "transcript": str(bundle / "transcript.md"),
        "frames_dir": str(bundle / "frames"),
        "output_dir": str(bundle),
    })
    for frame in manifest["frames"]:
        copied = bundle / "frames" / Path(frame["path"]).name
        shutil.copyfile(frame["path"], copied)
        frame["path"] = str(copied)
    (bundle / "evidence.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert {path.name for path in bundle.iterdir()} == {"evidence.json", "transcript.md", "frames"}

    result = notes.generate_notes(str(bundle))
    assert result["overall_pass"] is True
    assert (bundle / "notes.md").is_file()
    assert (bundle / "coverage.json").is_file()
    assert (bundle / "synthesis_input.json").is_file()
    assert not (bundle / "audio.wav").exists()
    assert "notes_contract" in json.loads((bundle / "coverage.json").read_text(encoding="utf-8"))
    assert original.is_dir()


def test_notes_from_evidence_is_byte_identical_to_legacy_notes_output(tmp_path):
    bundle = tmp_path / "legacy-equivalence"
    bundle.mkdir()
    transcript = bundle / "transcript.md"
    transcript.write_text("# Recording — Full transcript (raw)\n\n- Source: stt\n\n<a id=\"t000000\"></a> [00:00:00] Hello from the lecture\n", encoding="utf-8")
    manifest = {
        "schema_version": 2,
        "contract_version": 2,
        "tool": "lectural",
        "tool_version": "0.2.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "source": {
            "id": "sha256:" + "0" * 64,
            "kind": "local_audio",
            "argument": "recording.wav",
            "title": "Recording",
            "duration_sec": 30.0,
            "has_video": False,
            "resolution": {"width": None, "height": None},
            "citation": {"kind": "transcript"},
        },
        "speech": {"source": "stt", "language": "en", "model": "tiny", "fallback": {"code": "local_source"}},
        "transcript": {"segments": [{"id": "s0001", "start": 0.0, "end": 30.0, "text": "Hello from the lecture"}]},
        "frames": [],
        "artifacts": {"evidence": str(bundle / "evidence.json"), "transcript": str(transcript), "frames_dir": None, "output_dir": str(bundle)},
        "extraction": {
            "status": "pass",
            "reasons": [],
            "speech_completeness": {"status": "pass", "pass": True, "speech_spans": [[0.0, 30.0]]},
            "visual_completeness": {"status": "not-applicable", "pass": True, "visual_required": False, "ocr_required": False, "raw_sample_times": [], "notes_frame_ids": []},
            "timestamp_integrity": {"status": "pass", "pass": True},
            "ocr": {"status": "not_applicable", "engine": "not_applicable", "annotation_only": True},
        },
        "resources": {"wall_sec": 0.1, "stages": {"speech": 0.1, "frames": 0.0, "dedupe": 0.0, "ocr": 0.0}, "peak_rss_mb": None, "artifact_bytes": 1, "frames_candidate": 0, "frames_retained": 0},
        "failure": None,
    }
    (bundle / "evidence.json").write_text(json.dumps(manifest), encoding="utf-8")
    notes.generate_notes(str(bundle))
    expected = """<!-- lectural:notes -->
# Recording — 학습 정리

## 3줄 요약
<!-- 미보강 -->
- 미보강: 핵심 메시지 한 줄.
- 미보강: 핵심 메시지 한 줄.
- 미보강: 핵심 메시지 한 줄.

## 목차
- [전체](#sec-1)

## 흐름
<!-- 미보강 -->
- 미보강: 도입→전개→마무리 흐름을 짧게 정리하세요.
- 미보강: 핵심 전개를 한 줄씩 정리하세요.

## 핵심 개념·이론
<!-- 미보강 -->
- 미보강: 핵심 용어 → 정의를 전사 타임스탬프 링크와 함께 정리하세요.

## 정리 노트
<!-- 미보강 -->
<a id="sec-1"></a>
### 전체
- 미보강: 이 슬라이드 핵심을 요약 글머리표로 정리하세요.

## 복습 질문
<!-- 미보강 -->
- 미보강 질문: 핵심 확인 질문과 답을 작성하세요.

## 정리 커버리지
- 전체 길이: 00:00:30
- 대사 공백: 최대 0.0s (임계 60.0s) → 통과
- Scene coverage: not applicable (audio source)
- OCR: not applicable (audio source)
- OCR 엔진: not_applicable
- 산출물: transcript=O, notes=O
"""
    assert (bundle / "notes.md").read_text(encoding="utf-8") == expected


def test_safe_source_keeps_identity_and_nullable_resolution():
    source = evidence._safe_source({
        "id": "sha256:" + "a" * 64,
        "kind": "local_video",
        "argument": "C:/private/deck.mp4",
        "title": "Deck",
        "duration_sec": 10,
        "has_video": True,
        "citation": {"kind": "transcript"},
        "resolution": {"width": 1280, "height": 720, "secret": "discard"},
    })
    assert source["id"] == "sha256:" + "a" * 64
    assert source["resolution"] == {"width": 1280, "height": 720}
    assert source["argument"] == "deck.mp4"
    assert evidence._safe_source({"kind": "local_audio", "resolution": {"width": 0}})["resolution"] == {"width": None, "height": None}


def test_existing_output_is_rejected_as_bounded_json_failure(tmp_path):
    source = tmp_path / "lecture.wav"
    source.write_bytes(b"source")
    output = tmp_path / "existing"
    output.mkdir()
    exit_code, stdout = _invoke_cli(["extract", str(source), "--out", str(output), "--json"])
    assert exit_code == 2
    payload = json.loads(stdout)
    assert payload["result"]["failure"]["code"] == "OUTPUT_EXISTS"
    assert "source_kind" not in payload["result"]
    assert payload["result"]["source"] is None
    assert payload["result"]["artifacts"] == {
        "evidence": None, "transcript": None, "frames_dir": None, "output_dir": None,
    }


def test_timestamp_integrity_checks_interval_endpoints_and_frame_starts():
    valid = evidence.timestamp_integrity(10, [{"start": 0, "end": 10}], [{"start": 10}])
    assert valid["pass"] is True
    invalid = evidence.timestamp_integrity(10, [{"start": 3, "end": 2}], [{"start": 11}])
    assert invalid["pass"] is False
    assert invalid["transcript_segments"]["valid"] is False
    assert invalid["frames"]["valid"] is False


def test_fallback_codes_are_bounded_and_local_sources_are_marked(monkeypatch, tmp_path):
    source = _install_fake_pipeline(monkeypatch, tmp_path, audio_only=True)
    output = tmp_path / "local"
    exit_code, stdout = _invoke_cli(["extract", str(source), "--out", str(output), "--json"])
    assert exit_code == 0
    fallback = json.loads(stdout)["result"]["speech"]["fallback"]
    assert fallback == {"code": "local_source"}
    assert fallback["code"] in FALLBACK_CODES
