"""Unit tests for subtitle parsing + source selection (AC-3). Pure, offline."""

from lectural.acquisition import (
    captions_are_usable,
    extract_video_id,
    parse_json3,
    parse_vtt,
)


def test_extract_video_id_variants():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ?t=10") == "dQw4w9WgXcQ"
    assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("not a url") is None


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
