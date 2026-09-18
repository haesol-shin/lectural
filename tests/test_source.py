"""Offline source classification tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lectural.source import CitationKind, SourceKind, classify_source, extract_video_id


@pytest.mark.parametrize("suffix", [".mp4", ".webm", ".mkv", ".WAV"])
def test_classify_existing_local_suffixes(tmp_path: Path, suffix: str):
    path = tmp_path / f"lecture{suffix}"
    path.write_bytes(b"source")
    source = classify_source(str(path))
    expected_kind = SourceKind.LOCAL_AUDIO if suffix.lower() == ".wav" else SourceKind.LOCAL_VIDEO
    assert source.kind is expected_kind
    assert source.locator == str(path.resolve())
    assert source.title_hint == "lecture"
    assert source.argument == str(path)
    assert source.has_video is (expected_kind is SourceKind.LOCAL_VIDEO)
    assert source.caption_capable is False
    assert source.citation_kind is CitationKind.TRANSCRIPT
    assert path.read_bytes() == b"source"


def test_local_source_as_dict_omits_runtime_locator(tmp_path: Path):
    path = tmp_path / "recording.wav"
    path.write_bytes(b"source")
    descriptor = classify_source(str(path)).as_dict()
    assert descriptor == {
        "kind": "local_audio",
        "argument": str(path),
        "has_video": False,
        "citation": {"kind": "transcript"},
    }
    assert "locator" not in descriptor


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?t=10", "dQw4w9WgXcQ"),
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ],
)
def test_youtube_recognition_is_preserved(value: str, expected: str):
    source = classify_source(value)
    assert source.kind is SourceKind.YOUTUBE
    assert source.locator == value
    assert source.video_id == expected
    assert source.title_hint == ""
    assert source.has_video is True
    assert source.caption_capable is True
    assert source.citation_kind is CitationKind.YOUTUBE
    assert source.as_dict()["citation"] == {"kind": "youtube", "video_id": expected}


def test_extract_video_id_stays_pure_and_rejects_malformed_values(tmp_path: Path):
    assert extract_video_id("not a url") is None
    assert extract_video_id("too-short") is None
    with pytest.raises(ValueError, match="YouTube URL/ID"):
        classify_source("https://example.com/watch?v=dQw4w9WgXcQ")


    with pytest.raises(FileNotFoundError, match="missing.wav"):
        classify_source(str(tmp_path / "missing.wav"))
    directory = tmp_path / "lecture.mp4"
    directory.mkdir()
    with pytest.raises(ValueError, match="YouTube URL/ID"):
        classify_source(str(directory))
    unsupported = tmp_path / "lecture.txt"
    unsupported.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="mp4.*webm.*mkv.*wav"):
        classify_source(str(unsupported))
    with pytest.raises(ValueError, match="YouTube URL/ID"):
        classify_source("not a source")


def test_missing_supported_path_is_not_youtube_even_with_shorts_id(tmp_path: Path):
    missing = tmp_path / "shorts" / "dQw4w9WgXcQ" / "missing.mp4"
    with pytest.raises(FileNotFoundError, match="missing.mp4"):
        classify_source(str(missing))


def test_tilde_and_symlink_normalize_without_modifying_target(tmp_path: Path, monkeypatch):
    target = tmp_path / "target.MKV"
    target.write_bytes(b"unchanged")
    link = tmp_path / "alias.mkv"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    home = str(tmp_path)
    drive, home_path = os.path.splitdrive(home)
    # os.path.expanduser() uses different environment variables on POSIX and
    # Windows.  Isolate every relevant branch so the test never resolves the
    # tilde through the real user's home directory on CI.
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)
    monkeypatch.setenv("HOMEDRIVE", drive)
    monkeypatch.setenv("HOMEPATH", home_path or os.sep)
    source = classify_source("~/alias.mkv")
    assert source.locator == str(target.resolve())
    assert source.title_hint == "target"
    assert target.read_bytes() == b"unchanged"


def test_tilde_path_uses_isolated_expanduser_environment_without_symlink(
    tmp_path: Path, monkeypatch
):
    home = tmp_path / "isolated-home"
    home.mkdir()
    target = home / "lecture.mp4"
    target.write_bytes(b"source")
    drive, home_path = os.path.splitdrive(str(home))

    # Isolate both POSIX and Windows expanduser branches from the real user
    # profile before classifying a real file, without requiring symlinks.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOMEDRIVE", drive)
    monkeypatch.setenv("HOMEPATH", home_path or os.sep)

    source = classify_source("~/lecture.mp4")

    assert source.locator == str(target.resolve())
    assert source.kind is SourceKind.LOCAL_VIDEO
    assert source.title_hint == "lecture"
