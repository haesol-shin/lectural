"""Offline subtitle parsing and source-aware speech acquisition tests."""

from __future__ import annotations

import json
import warnings

import pytest

from lectural import acquisition, media, speech
from lectural.source import classify_source
from lectural.acquisition import captions_are_usable, parse_json3, parse_vtt


def test_parse_vtt_basic():
    vtt = (
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello world\n\n"
        "00:00:03.000 --> 00:00:04.000\nsecond cue\n"
    )
    segs = parse_vtt(vtt)
    assert [seg.text for seg in segs] == ["hello world", "second cue"]
    assert segs[1].t == 3.0


def test_parse_vtt_dedupes_rolling_autocaptions():
    vtt = (
        "00:00:01.000 --> 00:00:02.000\nfoo bar\n\n"
        "00:00:02.000 --> 00:00:03.000\nfoo bar\n\n"
        "00:00:03.000 --> 00:00:04.000\nbaz qux\n"
    )
    segs = parse_vtt(vtt)
    assert [seg.text for seg in segs] == ["foo bar", "baz qux"]


def test_parse_json3():
    payload = json.dumps(
        {
            "events": [
                {"tStartMs": 1000, "segs": [{"utf8": "Hello"}, {"utf8": " world"}]},
                {"tStartMs": 2500, "segs": [{"utf8": "Next"}]},
            ]
        }
    )
    segs = parse_json3(payload)
    assert [(seg.t, seg.text) for seg in segs] == [(1.0, "Hello world"), (2.5, "Next")]


def test_captions_usable_heuristic():
    good = parse_vtt(
        "00:00:01.000 --> 00:00:02.000\nthis is enough\n\n"
        "00:00:03.000 --> 00:00:04.000\nfor captions\n\n"
        "00:00:05.000 --> 00:00:06.000\ntoday\n"
    )
    assert captions_are_usable(good) is True
    assert captions_are_usable([]) is False


def test_youtube_usable_captions_skip_audio_and_stt(monkeypatch):
    source = classify_source("https://youtu.be/dQw4w9WgXcQ")
    segments = [acquisition.Segment(i, f"cue {i} with enough text") for i in range(3)]
    calls = []
    monkeypatch.setattr(acquisition, "fetch_caption_segments", lambda *_args: segments)
    monkeypatch.setattr(media, "resolve_audio", lambda *_args: calls.append("audio"))
    monkeypatch.setattr(speech, "transcribe_audio", lambda *_args, **_kwargs: calls.append("stt"))
    track = acquisition.acquire_speech(source, "/tmp/out")
    assert track.source == "caption"
    assert track.segments == segments
    assert calls == []
    assert track.meta["source_kind"] == "youtube"


def test_youtube_forced_stt_warns_and_forwards_model(monkeypatch, tmp_path):
    source = classify_source("https://youtu.be/dQw4w9WgXcQ")
    calls = []
    audio_path = str(tmp_path / "audio.wav")
    expected = acquisition.SpeechTrack([], "stt", meta={"duration": 11.0})
    monkeypatch.setattr(media, "resolve_audio", lambda source, out: calls.append((source, out)) or audio_path)
    monkeypatch.setattr(speech, "transcribe_audio", lambda path, model_size: calls.append((path, model_size)) or expected)
    with pytest.warns(RuntimeWarning, match="Captions unavailable.*force_stt requested"):
        track = acquisition.acquire_speech(source, str(tmp_path), force_stt=True, model="small")
    assert track is expected
    assert calls == [(source, str(tmp_path)), (audio_path, "small")]
    assert track.meta["audio_path"] == audio_path
    assert track.meta["caption_fallback_reason"] == "force_stt requested"
    assert track.meta["video_id"] == "dQw4w9WgXcQ"


def test_unusable_youtube_captions_preserve_fallback_reason(monkeypatch, tmp_path):
    source = classify_source("https://youtu.be/dQw4w9WgXcQ")
    monkeypatch.setattr(acquisition, "fetch_caption_segments", lambda *_args: [acquisition.Segment(1, "x")])
    monkeypatch.setattr(media, "resolve_audio", lambda *_args: str(tmp_path / "audio.wav"))
    monkeypatch.setattr(speech, "transcribe_audio", lambda *_args, **_kwargs: acquisition.SpeechTrack([], "stt", meta={}))
    with pytest.warns(RuntimeWarning, match="captions present but unusable"):
        track = acquisition.acquire_speech(source, str(tmp_path))
    assert track.meta["caption_fallback_reason"] == "captions present but unusable (1 cues)"


@pytest.mark.parametrize("filename", ["lecture.mp4", "recording.wav"])
def test_local_sources_directly_select_stt_without_caption_warning(monkeypatch, tmp_path, filename):
    path = tmp_path / filename
    path.write_bytes(b"local")
    source = classify_source(str(path))
    calls = []
    audio_path = str(tmp_path / "resolved.wav")
    monkeypatch.setattr(acquisition, "fetch_caption_segments", lambda *_args: calls.append("captions"))
    monkeypatch.setattr(media, "resolve_audio", lambda actual, out: calls.append(("audio", actual.kind)) or audio_path)
    expected = acquisition.SpeechTrack([], "stt", meta={})
    monkeypatch.setattr(speech, "transcribe_audio", lambda actual, model_size: calls.append(("stt", actual, model_size)) or expected)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        track = acquisition.acquire_speech(source, str(tmp_path / "out"), model="tiny")
    assert track is expected
    assert calls == [("audio", source.kind), ("stt", audio_path, "tiny")]
    assert not [warning for warning in caught if "Captions unavailable" in str(warning.message)]
    assert track.meta["audio_path"] == audio_path
    assert track.meta["source_kind"] == source.kind.value
    assert track.meta["input_source"]["citation"] == {"kind": "transcript"}
