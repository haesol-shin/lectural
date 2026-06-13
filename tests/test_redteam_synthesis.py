"""Adversarial synthesis + coverage tests for G002 pure functions."""

from __future__ import annotations

import json
import random

import pytest

from lectural.config import MAX_GAP_SEC, SCHEMA_VERSION
from lectural.coverage import CoverageInputs, build_coverage, gap_check, scene_coverage, write_coverage
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
    write_synthesis_input,
    write_text,
)


def _video(duration: float = 120.0, title: str = "Redteam # [Lecture] | Δ") -> dict:
    return {
        "title": title,
        "url": "https://example.invalid/watch?v=redteam",
        "duration_sec": duration,
        "language": "ko",
        "source": "caption",
    }


def _coverage(duration: float = 120.0, slide_total: int = 0, slide_text: int = 0) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "duration_sec": duration,
        "ocr_engine": "none",
        "gap_check": {
            "max_untranscribed_speech_gap_sec": 0,
            "threshold_sec": MAX_GAP_SEC,
            "pass": True,
        },
        "scene_coverage": {
            "speech_bins": [],
            "uncovered_speech_bins": [],
            "slide_frames_total": slide_total,
            "slide_frames_with_text": slide_text,
            "pass": slide_text >= slide_total,
        },
        "artifacts": {"transcript_nonempty": True, "summary_nonempty": True, "pass": True},
    }


def _summary_for(video: dict, segments: list[dict], slides: list[dict]) -> str:
    synthesis_input = build_synthesis_input(video, segments, slides)
    return render_summary_md(
        synthesis_input,
        _coverage(video["duration_sec"], len(slides), len([s for s in slides if s.get("ocr_text", "").strip()])),
    )


def test_render_transcript_md_property_captures_all_speech_fixed_seed():
    rng = random.Random(90210)
    video = _video(duration=90.0)
    segments = [
        {"t": 0.0, "text": "edge-at-zero"},
        {"t": -7.25, "text": "edge-before-first-slide"},
        {"t": 140.0, "text": "edge-beyond-last-slide"},
        {"t": 12.0, "text": "duplicate-text"},
        {"t": 12.0, "text": "duplicate-text"},
        {"t": 33.0, "text": ""},
    ]
    alphabet = ["alpha", "베타", "# heading", "[link]", "pipe|char", "emoji-없는-문장"]
    for i in range(80):
        t = rng.uniform(-30.0, 150.0)
        text = "" if i % 17 == 0 else f"seg-{i:02d}-{rng.choice(alphabet)}"
        segments.append({"t": t, "text": text})
    rng.shuffle(segments)

    md = render_transcript_md(video, segments)

    for segment in segments:
        timestamp = f"[{format_timestamp(float(segment['t']))}]"
        text = segment["text"].strip()
        rendered_line = f"{timestamp} {text}" if text else timestamp
        assert rendered_line in md
    assert md.count("[00:00:12] duplicate-text") == 2


def test_render_summary_md_assigns_each_in_duration_segment_once_and_boundary_to_one_section():
    video = _video(duration=100.0)
    slides = [
        {"t": 0.0, "frame": "frames/0001.png", "ocr_text": "Intro", "is_slide": True},
        {"t": 50.0, "frame": "frames/0002.png", "ocr_text": "Boundary # [x] | y", "is_slide": True},
    ]
    segments = [
        {"t": 0.0, "text": "summary-seg-zero"},
        {"t": 49.999, "text": "summary-seg-before-boundary"},
        {"t": 50.0, "text": "summary-seg-on-boundary"},
        {"t": 99.999, "text": "summary-seg-before-end"},
    ]

    md = _summary_for(video, segments, slides)

    for segment in segments:
        assert md.count(segment["text"]) == 1
    sec1 = md[md.index('<a id="sec-0"></a>') : md.index('<a id="sec-1"></a>')]
    sec2 = md[md.index('<a id="sec-1"></a>') :]
    assert "summary-seg-on-boundary" not in sec1
    assert "summary-seg-on-boundary" in sec2


def test_render_summary_md_does_not_drop_in_duration_segments_before_first_slide_or_at_duration():
    video = _video(duration=100.0)
    slides = [
        {"t": 25.0, "frame": "frames/0025.png", "ocr_text": "Starts late", "is_slide": True},
        {"t": 80.0, "frame": "frames/0080.png", "ocr_text": "Last section", "is_slide": True},
    ]
    segments = [
        {"t": 0.0, "text": "dropped-before-first-slide-at-zero"},
        {"t": 24.999, "text": "dropped-before-first-slide-nearby"},
        {"t": 100.0, "text": "dropped-at-duration-boundary"},
    ]

    md = _summary_for(video, segments, slides)

    for segment in segments:
        assert md.count(segment["text"]) == 1


def test_render_summary_md_no_slides_keeps_required_anchors_and_single_section():
    video = _video(duration=75.0, title="No slides # [empty] | unicode 한글")
    segments = [{"t": 0.0, "text": "no-slides-segment"}, {"t": 74.999, "text": "no-slides-tail"}]

    md = _summary_for(video, segments, [])

    assert md.splitlines()[0] == ENRICH_MARKER
    assert COVERAGE_ANCHOR in md
    assert TOC_ANCHOR in md
    assert md.count(SECTION_PREFIX) == 1
    assert md.count('<a id="sec-') == 1
    for segment in segments:
        assert segment["text"] in md


@pytest.mark.parametrize(
    "slides",
    [
        [],
        [{"t": 0.0, "frame": "frames/empty.png", "ocr_text": "", "is_slide": True}],
        [{"t": 0.0, "frame": "frames/special.png", "ocr_text": "# Title [brackets] | pipe\n본문", "is_slide": True}],
    ],
)
def test_anchor_stability_across_no_empty_and_markdown_special_slides(slides):
    video = _video(duration=60.0, title="Anchor # [stability] | Δ")
    segments = [{"t": 0.0, "text": "anchor-stability-segment"}]

    md = _summary_for(video, segments, slides)

    assert md.startswith(ENRICH_MARKER + "\n")
    assert COVERAGE_ANCHOR in md
    assert TOC_ANCHOR in md
    assert SECTION_PREFIX in md
    assert '<a id="sec-0"></a>' in md
    if slides and slides[0].get("frame"):
        assert slides[0]["frame"] in md


def test_build_section_hints_adversarial_order_single_duplicate_and_past_duration():
    unsorted = [
        {"t": 60.0, "frame": "frames/60.png", "ocr_text": "Third", "is_slide": True},
        {"t": 0.0, "frame": "frames/00.png", "ocr_text": "First", "is_slide": True},
        {"t": 30.0, "frame": "frames/30.png", "ocr_text": "Second", "is_slide": True},
    ]
    unsorted_hints = build_section_hints(unsorted, 90.0)
    assert [hint["t"] for hint in unsorted_hints] == [0.0, 30.0, 60.0]
    assert [hint["t_end"] for hint in unsorted_hints] == [30.0, 60.0, 90.0]

    single = build_section_hints([{"t": 12.5, "frame": None, "ocr_text": "Only", "is_slide": True}], 80.0)
    # First slide starts after 0 -> an intro section is prepended so pre-slide
    # speech is never dropped; the slide becomes the second section.
    assert single == [
        {"index": 0, "t": 0.0, "win_start": 0.0, "t_end": 12.5, "title": "도입", "frame": None},
        {"index": 1, "t": 12.5, "win_start": 12.5, "t_end": 80.0, "title": "Only", "frame": None},
    ]

    duplicate = build_section_hints(
        [
            {"t": 0.0, "frame": "frames/a.png", "ocr_text": "A", "is_slide": True},
            {"t": 0.0, "frame": "frames/b.png", "ocr_text": "B", "is_slide": True},
            {"t": 40.0, "frame": "frames/c.png", "ocr_text": "C", "is_slide": True},
        ],
        100.0,
    )
    assert [hint["index"] for hint in duplicate] == [0, 1, 2]
    assert [hint["t"] for hint in duplicate] == [0.0, 0.0, 40.0]
    assert [hint["t_end"] for hint in duplicate] == [0.0, 40.0, 100.0]

    past_duration = build_section_hints(
        [
            {"t": 0.0, "frame": "frames/in.png", "ocr_text": "Inside", "is_slide": True},
            {"t": 125.0, "frame": "frames/past.png", "ocr_text": "Past duration", "is_slide": True},
        ],
        100.0,
    )
    assert [hint["t"] for hint in past_duration] == [0.0, 125.0]
    assert past_duration[-1]["t_end"] == 100.0


def test_gap_check_empty_speech_zero_duration_and_exact_threshold_boundary():
    empty = gap_check([], [], duration=100.0)
    assert empty["pass"] is True
    assert empty["max_untranscribed_speech_gap_sec"] == 0.0

    zero_duration = gap_check([(0.0, 0.0)], [], duration=0.0)
    assert zero_duration["pass"] is True
    assert zero_duration["max_untranscribed_speech_gap_sec"] == 0.0

    exactly_threshold = gap_check([(0.0, MAX_GAP_SEC)], [], duration=MAX_GAP_SEC)
    assert exactly_threshold["max_untranscribed_speech_gap_sec"] == MAX_GAP_SEC
    assert exactly_threshold["pass"] is True

    just_over_threshold = gap_check([(0.0, MAX_GAP_SEC + 0.001)], [], duration=MAX_GAP_SEC + 0.001)
    assert just_over_threshold["pass"] is False


def test_scene_coverage_empty_zero_duration_slide_text_fail_and_all_bins_pass():
    empty = scene_coverage([], [], duration=120.0, bins=20)
    assert empty["pass"] is True
    assert empty["speech_bins"] == []

    zero_duration = scene_coverage([0.0], [(0.0, 10.0)], duration=0.0, bins=0)
    assert zero_duration["pass"] is True
    assert zero_duration["bins"] == 1
    assert zero_duration["speech_bins"] == []

    missing_slide_text = scene_coverage(
        [5.0, 15.0, 25.0, 35.0],
        [(0.0, 40.0)],
        duration=40.0,
        bins=4,
        slide_frames_total=4,
        slide_frames_with_text=3,
    )
    assert missing_slide_text["pass"] is False

    all_bins_covered = scene_coverage(
        [5.0, 15.0, 25.0, 35.0],
        [(0.0, 40.0)],
        duration=40.0,
        bins=4,
        slide_frames_total=4,
        slide_frames_with_text=4,
    )
    assert all_bins_covered["pass"] is True
    assert all_bins_covered["covered_speech_bins"] == [0, 1, 2, 3]
    assert all_bins_covered["uncovered_speech_bins"] == []


def test_format_timestamp_adversarial_boundaries():
    assert format_timestamp(-0.49) == "00:00:00"
    assert format_timestamp(-90.0) == "00:00:00"
    assert format_timestamp(59.6) == "00:01:00"
    assert format_timestamp(3599.6) == "01:00:00"
    assert format_timestamp(7322.4) == "02:02:02"


def test_write_helpers_round_trip_with_tmp_path_and_schema_reload(tmp_path):
    video = _video(duration=40.0)
    segments = [{"t": 0.0, "text": "round-trip-start"}, {"t": 39.9, "text": "round-trip-end"}]
    slides = [{"t": 0.0, "frame": "frames/0000.png", "ocr_text": "Round trip", "is_slide": True}]
    synthesis_input = build_synthesis_input(video, segments, slides)

    synthesis_path = tmp_path / "synthesis_input.json"
    write_synthesis_input(synthesis_input, str(synthesis_path))
    reloaded_synthesis = json.loads(synthesis_path.read_text(encoding="utf-8"))
    assert reloaded_synthesis["schema_version"] == 1

    transcript_path = tmp_path / "transcript.md"
    transcript = render_transcript_md(video, segments)
    write_text(transcript, str(transcript_path))
    assert transcript_path.read_text(encoding="utf-8") == transcript

    summary_path = tmp_path / "summary.md"
    summary = render_summary_md(synthesis_input, _coverage(40.0, slide_total=1, slide_text=1))
    write_text(summary, str(summary_path))
    assert summary_path.read_text(encoding="utf-8").startswith(ENRICH_MARKER)

    coverage = build_coverage(
        CoverageInputs(
            video_title=video["title"],
            duration_sec=40.0,
            speech_spans=[(0.0, 40.0)],
            segment_times=[segment["t"] for segment in segments],
            frame_times=[i * 2.0 + 1.0 for i in range(20)],
            transcript_path=str(transcript_path),
            summary_path=str(summary_path),
            ocr_engine="none",
            slide_frames_total=1,
            slide_frames_with_text=1,
        )
    )
    coverage_path = tmp_path / "coverage.json"
    write_coverage(coverage, str(coverage_path))
    reloaded_coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    assert reloaded_coverage["schema_version"] == 1
    assert reloaded_coverage["overall_pass"] is True
