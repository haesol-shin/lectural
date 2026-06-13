"""Unit tests for subtitle parsing + source selection (AC-3). Pure, offline."""
import json


from lectural import acquisition
from lectural.acquisition import (
    captions_are_usable,
    extract_video_id,
    fetch_video_metadata,
    parse_json3,
    parse_vtt,
    parse_ytdlp_metadata,
)


def test_extract_video_id_variants():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ?t=10") == "dQw4w9WgXcQ"
    assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("not a url") is None


def test_parse_ytdlp_metadata_extracts_title_duration_and_id():
    payload = json.dumps(
        {
            "title": "운영체제 1강: 프로세스/스레드",
            "duration": 3723,
            "id": "dQw4w9WgXcQ",
        }
    )

    assert parse_ytdlp_metadata(payload) == {
        "title": "운영체제 1강: 프로세스/스레드",
        "duration": 3723.0,
        "video_id": "dQw4w9WgXcQ",
    }


def test_fetch_video_metadata_uses_skip_download(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(cmd, *, check, capture_output, text):
        captured["cmd"] = cmd
        captured["check"] = check
        captured["capture_output"] = capture_output
        captured["text"] = text

        class Proc:
            stdout = json.dumps({"title": "Lecture", "duration": 12.5, "id": "abc123XYZ09"})

        return Proc()

    monkeypatch.setattr(acquisition.subprocess, "run", fake_run)

    metadata = fetch_video_metadata("https://youtu.be/abc123XYZ09")

    cmd = captured["cmd"]
    assert metadata == {"title": "Lecture", "duration": 12.5, "video_id": "abc123XYZ09"}
    assert cmd == ["yt-dlp", "--skip-download", "--dump-json", "https://youtu.be/abc123XYZ09"]
    assert "--skip-download" in cmd
    assert "-x" not in cmd and "--audio-format" not in cmd
    assert captured["check"] is True
    assert captured["capture_output"] is True
    assert captured["text"] is True


def test_parse_vtt_basic():
    vtt = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "Hello <c>everyone</c>\n\n"
        "00:00:03.000 --> 00:00:05.500\n"
        "welcome to the lecture\n"
    )
    segs = parse_vtt(vtt)
    assert [s.text for s in segs] == ["Hello everyone", "welcome to the lecture"]
    assert segs[1].t == 3.0


def test_parse_vtt_dedupes_rolling_autocaptions():
    vtt = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.000\nfoo bar\n\n"
        "00:00:02.000 --> 00:00:03.000\nfoo bar\n\n"
        "00:00:03.000 --> 00:00:04.000\nbaz qux\n"
    )
    segs = parse_vtt(vtt)
    assert [s.text for s in segs] == ["foo bar", "baz qux"]


def test_parse_json3():
    payload = (
        '{"events":['
        '{"tStartMs":1000,"segs":[{"utf8":"안녕"},{"utf8":"하세요"}]},'
        '{"tStartMs":2500,"segs":[{"utf8":"강의입니다"}]},'
        '{"tStartMs":4000,"segs":[{"utf8":"\\n"}]}'
        "]}"
    )
    segs = parse_json3(payload)
    assert [s.text for s in segs] == ["안녕하세요", "강의입니다"]
    assert segs[0].t == 1.0


def test_captions_usable_heuristic():
    good = parse_vtt(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nthis is a real caption line\n\n"
        "00:00:03.000 --> 00:00:05.000\nwith enough content here\n\n"
        "00:00:05.000 --> 00:00:07.000\nand a third cue\n"
    )
    assert captions_are_usable(good) is True
    assert captions_are_usable([]) is False
