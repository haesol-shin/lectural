"""Offline tests for source-specific metadata/audio/video resolution."""

from __future__ import annotations

import os
from pathlib import Path

from lectural import media
from lectural.source import SourceKind, classify_source


def test_probe_youtube_uses_existing_metadata_command(monkeypatch):
    calls = []

    def fake_require(name):
        calls.append(("require", name))

    def fake_run(command, **kwargs):
        calls.append(("run", command, kwargs))
        return type("Completed", (), {"stdout": '{"title":"Lecture","duration":12.5,"id":"dQw4w9WgXcQ"}'})()

    monkeypatch.setattr(media, "require_binary", fake_require)
    monkeypatch.setattr(media.subprocess, "run", fake_run)
    source = classify_source("https://youtu.be/dQw4w9WgXcQ")
    metadata = media.probe_source(source)
    assert metadata.title == "Lecture"
    assert metadata.duration == 12.5
    assert metadata.video_id == "dQw4w9WgXcQ"
    assert calls[1][1] == [
        "yt-dlp", "--quiet", "--no-warnings", "--skip-download", "--dump-json",
        "--extractor-args", "youtube:player_client=android", source.locator,
    ]
    assert calls[1][2] == {"check": True, "capture_output": True, "text": True}


def test_youtube_audio_and_video_commands_remain_current(monkeypatch, tmp_path: Path):
    calls = []

    def fake_ready():
        calls.append(("ready",))

    def fake_run(command, **kwargs):
        calls.append(("run", command, kwargs))
        if command[0] == "yt-dlp" and "-x" in command:
            (tmp_path / "audio.wav").write_bytes(b"audio")
        elif command[0] == "yt-dlp":
            (tmp_path / "video.mp4").write_bytes(b"video")

    monkeypatch.setattr(media, "assert_acquisition_ready", fake_ready)
    monkeypatch.setattr(media.subprocess, "run", fake_run)
    source = classify_source("https://youtu.be/dQw4w9WgXcQ")
    assert media.resolve_audio(source, str(tmp_path)) == str(tmp_path / "audio.wav")
    assert media.resolve_video(source, str(tmp_path)) == str(tmp_path / "video.mp4")
    assert calls[0] == ("ready",)
    assert calls[1][1] == [
        "yt-dlp", "--quiet", "--no-warnings", "--no-progress",
        "--extractor-args", "youtube:player_client=android",
        "-x", "--audio-format", "wav", "-o", str(tmp_path / "audio.%(ext)s"), source.locator,
    ]
    assert calls[2] == ("ready",)
    assert calls[3][1] == [
        "yt-dlp", "--quiet", "--no-warnings", "--no-progress",
        "--extractor-args", "youtube:player_client=android",
        "-f", "bestvideo[height<=720]+bestaudio/best",
        "-o", str(tmp_path / "video.%(ext)s"), source.locator,
    ]


def test_local_wav_resolves_in_place_and_has_no_video(tmp_path: Path):
    path = tmp_path / "recording.WAV"
    path.write_bytes(b"original")
    source = classify_source(str(path))
    assert source.kind is SourceKind.LOCAL_AUDIO
    assert media.resolve_audio(source, str(tmp_path / "out")) == str(path.resolve())
    assert media.resolve_video(source, str(tmp_path / "out")) is None
    assert path.read_bytes() == b"original"
    assert not (tmp_path / "out").exists()


def test_local_video_extracts_only_generated_audio_and_never_uses_ytdlp(monkeypatch, tmp_path: Path):
    path = tmp_path / "recording.mp4"
    path.write_bytes(b"original-video")
    source = classify_source(str(path))
    calls = []

    def fake_require(name):
        calls.append(("require", name))

    def fake_run(command, **kwargs):
        calls.append(("run", command, kwargs))
        output = Path(command[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"generated-audio")

    monkeypatch.setattr(media, "require_binary", fake_require)
    monkeypatch.setattr(media.subprocess, "run", fake_run)
    assert media.resolve_video(source, str(tmp_path / "out")) == str(path.resolve())
    output = media.resolve_audio(source, str(tmp_path / "out"))
    assert output == str(tmp_path / "out" / "audio.wav")
    assert calls[0] == ("require", "ffmpeg")
    assert calls[1][1] == [
        "ffmpeg", "-y", "-i", str(path.resolve()), "-vn", "-acodec", "pcm_s16le", output,
    ]
    assert all("yt-dlp" not in call[1] for call in calls if call[0] == "run")
    assert path.read_bytes() == b"original-video"


def test_all_source_kinds_have_explicit_resolver_entries():
    assert set(media._PROBE_RESOLVERS) == set(SourceKind)
    assert set(media._AUDIO_RESOLVERS) == set(SourceKind)
    assert set(media._VIDEO_RESOLVERS) == set(SourceKind)


def test_probe_video_resolution_uses_processed_file(monkeypatch):
    calls = []
    monkeypatch.setattr(media, "require_binary", lambda name: calls.append(name))
    monkeypatch.setattr(
        media.subprocess, "run",
        lambda command, **_kwargs: type("Result", (), {"stdout": '{"streams":[{"width":1280,"height":720}]}'})(),
    )
    assert media.probe_video_resolution("processed.mp4") == (1280, 720)
    assert calls == ["ffprobe"]
