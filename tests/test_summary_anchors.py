"""Unit tests for synthesis helpers still used by notes.md."""

from lectural.synthesis import (
    build_section_hints,
    build_synthesis_input,
    format_timestamp,
    render_transcript_md,
)

def _fixture():
    video = {"title": "운영체제 1강", "url": "u", "duration_sec": 300.0,
             "language": "ko", "source": "caption"}
    segments = [
        {"t": 0.0, "text": "안녕하세요 운영체제 강의입니다"},
        {"t": 65.0, "text": "프로세스와 스레드의 차이"},
        {"t": 200.0, "text": "스케줄링 알고리즘"},
    ]
    slides = [
        {"t": 0.0, "frame": "frames/00001.png", "ocr_text": "운영체제 개요\n학습목표", "is_slide": True},
        {"t": 180.0, "frame": "frames/00002.png", "ocr_text": "CPU 스케줄링", "is_slide": True},
    ]
    return video, segments, slides


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(3661) == "01:01:01"
    assert format_timestamp(-5) == "00:00:00"


def test_section_hints_window_from_slides():
    _, _, slides = _fixture()
    hints = build_section_hints(slides, 300.0)
    assert len(hints) == 2
    assert hints[0]["t"] == 0.0 and hints[0]["t_end"] == 180.0
    assert hints[1]["t"] == 180.0 and hints[1]["t_end"] == 300.0


def test_section_hints_no_slides_single_section():
    hints = build_section_hints([], 120.0)
    assert len(hints) == 1 and hints[0]["t_end"] == 120.0


def test_transcript_md_has_all_utterances():
    video, segments, _ = _fixture()
    md = render_transcript_md(video, segments)
    for s in segments:
        assert s["text"] in md
    assert "[00:01:05]" in md  # 65s


