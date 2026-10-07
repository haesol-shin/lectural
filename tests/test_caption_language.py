"""Synthetic caption listings and audio-language signals; no network."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from lectural import acquisition, media, speech
from lectural.source import InputSource, SourceKind


VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nOriginal speech one\n\n00:00:01.000 --> 00:00:02.000\nOriginal speech two\n\n00:00:02.000 --> 00:00:03.000\nOriginal speech three\n"


def install_listing(monkeypatch, metadata):
    monkeypatch.setattr(acquisition, "require_binary", lambda *_: None, raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(metadata)))
    downloads = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def read(self):
            return VTT.encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda url: downloads.append(url) or Response())
    return downloads


def track(url):
    return [{"ext": "vtt", "url": url}]


def test_mislabeled_original_falls_back_with_detected_language(monkeypatch, tmp_path):
    downloads = install_listing(monkeypatch, {
        "automatic_captions": {
            "ar-orig": track("https://captions.invalid/original?lang=ar"),
            "ko": track("https://captions.invalid/translated?tlang=ko"),
        },
    })
    source = InputSource(argument="https://video.invalid/watch", kind=SourceKind.YOUTUBE, locator="https://video.invalid/watch", title_hint="Synthetic", video_id="synthetic01")
    monkeypatch.setattr(media, "resolve_audio", lambda *_: "synthetic.wav")
    monkeypatch.setattr(speech, "detect_audio_language", lambda *_args, **_kwargs: "en", raising=False)
    monkeypatch.setattr(speech, "transcribe_audio", lambda *_args, **_kwargs: acquisition.SpeechTrack([], "stt", "en"))
    with pytest.warns(RuntimeWarning):
        result = acquisition.acquire_speech(source, str(tmp_path))
    assert result.source == "stt"
    assert result.language == "en"
    assert result.meta["fallback_code"] == "captions_language_mismatch"
    assert all("tlang" not in url for url in downloads)


def test_translated_only_tracks_rejected(monkeypatch):
    downloads = install_listing(monkeypatch, {
        "language": "en", "automatic_captions": {
            "en": track("https://captions.invalid/sub?tlang=en"),
            "ko-orig": track("https://captions.invalid/sub?tlang=ko"),
        },
    })
    with pytest.raises(Exception, match="original"):
        acquisition.fetch_caption_segments("synthetic01")
    assert downloads == []


@pytest.mark.parametrize("collection,key", [("subtitles", "en"), ("automatic_captions", "en-orig")])
def test_matching_original_records_language_without_probe(monkeypatch, collection, key):
    downloads = install_listing(monkeypatch, {
        "language": "en-US", collection: {key: track("https://captions.invalid/original?lang=en")},
        "automatic_captions": {"en-orig": track("https://captions.invalid/original?lang=en"), "ko": track("https://captions.invalid/sub?tlang=ko")},
    })
    result = acquisition.fetch_caption_segments("synthetic01")
    assert result.source == "caption"
    assert result.language == "en"
    assert result.meta["language_verified"] is True
    assert len(result.segments) == 3
    assert downloads == ["https://captions.invalid/original?lang=en"]


@pytest.mark.parametrize("metadata_language,detected,expected", [
    (None, "en", None), ("ar", "en", None),
    (None, None, "captions_language_unverified"),
])
def test_probe_verifies_original_or_falls_back(monkeypatch, tmp_path, metadata_language, detected, expected):
    install_listing(monkeypatch, {
        "language": metadata_language,
        "automatic_captions": {"en-orig": track("https://captions.invalid/original")},
    })
    source = InputSource(argument="https://video.invalid/watch", kind=SourceKind.YOUTUBE,
                         locator="https://video.invalid/watch", title_hint="Synthetic", video_id="synthetic01")
    calls = []
    monkeypatch.setattr(media, "resolve_audio", lambda *_: calls.append("audio") or "synthetic.wav")
    monkeypatch.setattr(speech, "detect_audio_language", lambda *_args, **_kwargs: detected)
    monkeypatch.setattr(speech, "transcribe_audio", lambda *_args, **_kwargs: acquisition.SpeechTrack([], "stt", "en"))
    if expected:
        with pytest.warns(RuntimeWarning):
            result = acquisition.acquire_speech(source, str(tmp_path))
        assert result.meta["fallback_code"] == expected
    else:
        result = acquisition.acquire_speech(source, str(tmp_path))
        assert result.source == "caption"
        assert result.language == "en"
    assert calls == ["audio"]


@pytest.mark.parametrize("probability,expected", [(0.998, "en"), (0.4, None)])
def test_language_probe_is_bounded_and_confidence_gated(monkeypatch, probability, expected):
    calls = []
    monkeypatch.setattr(speech, "require_binary", lambda *_: None)
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: calls.append(args) or SimpleNamespace(stdout=b"synthetic"))
    class Model:
        def __init__(self, *args, **kwargs):
            pass
        def transcribe(self, audio, **kwargs):
            assert audio.read() == b"synthetic"
            assert kwargs["language"] is None
            return iter(()), SimpleNamespace(language="en", language_probability=probability)
    import sys
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    assert speech.detect_audio_language("synthetic.wav", model_size="tiny") == expected
    assert calls[0][calls[0].index("-t") + 1] == "30"


def test_detected_language_reselects_matching_original(monkeypatch, tmp_path):
    downloads = install_listing(monkeypatch, {
        "subtitles": {"ko": track("https://captions.invalid/manual-ko")},
        "automatic_captions": {"en-orig": track("https://captions.invalid/original-en")},
    })
    source = InputSource(argument="https://video.invalid/watch", kind=SourceKind.YOUTUBE,
                         locator="https://video.invalid/watch", title_hint="Synthetic", video_id="synthetic01")
    monkeypatch.setattr(media, "resolve_audio", lambda *_: "synthetic.wav")
    monkeypatch.setattr(speech, "detect_audio_language", lambda *_args, **_kwargs: "en")
    result = acquisition.acquire_speech(source, str(tmp_path))
    assert result.source == "caption"
    assert result.language == "en"
    assert downloads[-1] == "https://captions.invalid/original-en"
