"""Unit tests for synthesis renderers + required anchors (AC-7, AC-8, AC-12)."""

from lectural.synthesis import (
    COVERAGE_ANCHOR,
    ENRICH_MARKER,
    SECTION_PREFIX,
    TOC_ANCHOR,
    build_section_hints,
    build_synthesis_input,
    format_timestamp,
    render_summary_md,
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


def test_summary_md_required_anchors_present():
    video, segments, slides = _fixture()
    si = build_synthesis_input(video, segments, slides)
    coverage = {
        "duration_sec": 300.0,
        "ocr_engine": "paddleocr",
        "gap_check": {"max_untranscribed_speech_gap_sec": 10, "threshold_sec": 60, "pass": True},
        "scene_coverage": {"speech_bins": [0, 1, 2], "uncovered_speech_bins": [],
                            "slide_frames_total": 2, "slide_frames_with_text": 2, "pass": True},
        "artifacts": {"transcript_nonempty": True, "summary_nonempty": True, "pass": True},
    }
    md = render_summary_md(si, coverage)
    assert md.splitlines()[0] == ENRICH_MARKER
    assert COVERAGE_ANCHOR in md
    assert TOC_ANCHOR in md
    assert SECTION_PREFIX in md
    assert "frames/00001.png" in md  # slide link
    assert "(#sec-0)" in md          # TOC intra-doc link
    assert "[00:03:20]" in md        # 200s utterance timestamp present


def test_summary_md_assigns_segments_to_sections():
    video, segments, slides = _fixture()
    si = build_synthesis_input(video, segments, slides)
    coverage = {"duration_sec": 300.0, "ocr_engine": "none",
                "gap_check": {"max_untranscribed_speech_gap_sec": 0, "threshold_sec": 60, "pass": True},
                "scene_coverage": {"speech_bins": [], "uncovered_speech_bins": [],
                                   "slide_frames_total": 2, "slide_frames_with_text": 2, "pass": True},
                "artifacts": {"transcript_nonempty": True, "summary_nonempty": True, "pass": True}}
    md = render_summary_md(si, coverage)
    # 200s utterance must land under section 2 (starts 180s), not section 1.
    sec2_idx = md.index("섹션 2")
    assert md.index("스케줄링 알고리즘") > sec2_idx


def test_summary_escapes_markdown_special_titles():
    video = {"title": "x", "url": "u", "duration_sec": 100.0, "source": "stt"}
    segments = [{"t": 0.0, "text": "\ubcf8\ubb38"}]
    slides = [{"t": 0.0, "frame": "frames/a.png",
               "ocr_text": "Topic [draft] | v2\n\uc138\ubd80", "is_slide": True}]
    si = build_synthesis_input(video, segments, slides)
    coverage = {"duration_sec": 100.0, "ocr_engine": "none",
                "gap_check": {"max_untranscribed_speech_gap_sec": 0, "threshold_sec": 60, "pass": True},
                "scene_coverage": {"speech_bins": [], "uncovered_speech_bins": [],
                                   "slide_frames_total": 1, "slide_frames_with_text": 1, "pass": True},
                "artifacts": {"transcript_nonempty": True, "summary_nonempty": True, "pass": True}}
    md = render_summary_md(si, coverage)
    toc_line = next(ln for ln in md.splitlines() if ln.startswith("- [00:00:00"))
    link_text = toc_line.split("](")[0]
    assert "]" not in link_text.split("\u00b7 ", 1)[1]
    assert "|" not in link_text


def test_summary_skips_empty_intro_section_but_keeps_pre_slide_speech():
    video = {"title": "x", "url": "u", "duration_sec": 200.0, "source": "stt"}
    slides = [{"t": 60.0, "frame": "frames/a.png", "ocr_text": "Slide", "is_slide": True}]
    si = build_synthesis_input(video, [{"t": 120.0, "text": "\ud6c4\ubc18\ubd80"}], slides)
    cov = {"duration_sec": 200.0, "ocr_engine": "none",
           "gap_check": {"max_untranscribed_speech_gap_sec": 0, "threshold_sec": 60, "pass": True},
           "scene_coverage": {"speech_bins": [], "uncovered_speech_bins": [],
                              "slide_frames_total": 1, "slide_frames_with_text": 1, "pass": True},
           "artifacts": {"transcript_nonempty": True, "summary_nonempty": True, "pass": True}}
    md = render_summary_md(si, cov)
    assert "\ub3c4\uc785" not in md
    si2 = build_synthesis_input(video, [{"t": 5.0, "text": "\ub3c4\uc785\ubd80 \ubc1c\ud654"}, {"t": 120.0, "text": "\ud6c4\ubc18\ubd80"}], slides)
    md2 = render_summary_md(si2, cov)
    assert "\ub3c4\uc785\ubd80 \ubc1c\ud654" in md2
