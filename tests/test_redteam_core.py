"""Adversarial and boundary tests for deterministic core functions."""

from __future__ import annotations

import json
import random

import pytest

from lectural.acquisition import extract_video_id, parse_json3, parse_vtt
from lectural.config import CUE_MAX_COVER_SEC, DEDUP_HIST_THRESHOLD, DEDUP_SSIM_THRESHOLD, MAX_GAP_SEC
from lectural.ocr import classify_slide_transition, dedupe_incremental_texts
from lectural.vad import (
    max_non_silence_untranscribed_gap,
    merge_spans,
    parse_silencedetect,
    transcript_coverage_spans,
)
from lectural.visual import is_same_slide, select_keyframe_indices


def test_vad_gap_metric_empty_and_misaligned_inputs_are_bounded():
    assert max_non_silence_untranscribed_gap([], []) == 0.0
    assert max_non_silence_untranscribed_gap([(10.0, 20.0)], []) == 10.0
    assert max_non_silence_untranscribed_gap([(10.0, 20.0)], [(-100.0, 0.0), (30.0, 40.0)]) == 10.0


def test_vad_gap_metric_handles_unsorted_overlapping_spans_and_exact_boundary():
    speech = [(80.0, 100.0), (0.0, 40.0), (30.0, 80.0)]
    coverage = [(70.0, 100.0), (0.0, 10.0), (8.0, 10.0)]

    assert max_non_silence_untranscribed_gap(speech, coverage) == pytest.approx(MAX_GAP_SEC)
    assert max_non_silence_untranscribed_gap(speech, coverage) <= MAX_GAP_SEC


def test_vad_gap_metric_randomized_property_never_negative_or_larger_than_speech():
    rng = random.Random(1337)

    for _ in range(30):
        speech = []
        coverage = []
        for _ in range(rng.randint(0, 8)):
            a = rng.uniform(-20.0, 140.0)
            b = a + rng.uniform(-5.0, 60.0)
            speech.append((a, b))
        for _ in range(rng.randint(0, 8)):
            a = rng.uniform(-50.0, 170.0)
            b = a + rng.uniform(-10.0, 80.0)
            coverage.append((a, b))

        gap = max_non_silence_untranscribed_gap(speech, coverage)
        total_speech = sum(end - start for start, end in merge_spans(speech))

        assert gap >= 0.0
        assert gap <= total_speech + 1e-9


def test_transcript_coverage_spans_sorts_clamps_and_ignores_out_of_range_times():
    spans = transcript_coverage_spans([50.0, -1.0, 10.0, 999.0, 0.0], duration=60.0)

    assert spans == [(0.0, 40.0), (50.0, 60.0)]


def test_transcript_coverage_spans_single_cue_and_cap_behavior():
    assert transcript_coverage_spans([7.0], duration=20.0) == [(7.0, 20.0)]
    assert transcript_coverage_spans([7.0], duration=100.0) == [(7.0, 7.0 + CUE_MAX_COVER_SEC)]


def test_parse_silencedetect_empty_and_trailing_silence_contracts():
    assert parse_silencedetect("", duration=12.0) == [(0.0, 12.0)]
    assert parse_silencedetect("[silencedetect] silence_start: 8.0", duration=12.0) == [(0.0, 8.0)]


def test_parse_silencedetect_ignores_malformed_lines_and_handles_unmatched_end():
    stderr = "\n".join(
        [
            "not ffmpeg output",
            "[silencedetect] silence_end: 2.0 | silence_duration: 2.0",
            "[silencedetect] silence_start: not-a-number",
            "[silencedetect] silence_start: 5.0",
            "other filter chatter",
            "[silencedetect] silence_end: 7.5 | silence_duration: 2.5",
        ]
    )

    assert parse_silencedetect(stderr, duration=10.0) == [(2.0, 5.0), (7.5, 10.0)]


def test_select_keyframe_indices_empty_identical_distinct_and_threshold_edges():
    assert select_keyframe_indices([]) == [0]
    assert select_keyframe_indices([(1.0, 1.0), (0.99, 0.99), (0.95, 0.98)]) == [0]
    assert select_keyframe_indices([(0.0, 1.0), (1.0, 0.0), (0.89, 0.91)]) == [0, 1, 2, 3]

    assert is_same_slide(DEDUP_HIST_THRESHOLD, DEDUP_SSIM_THRESHOLD) is True
    assert select_keyframe_indices([(DEDUP_HIST_THRESHOLD, DEDUP_SSIM_THRESHOLD)]) == [0]
    assert select_keyframe_indices([(DEDUP_HIST_THRESHOLD, DEDUP_SSIM_THRESHOLD - 0.001)]) == [0, 1]
    assert select_keyframe_indices([(DEDUP_HIST_THRESHOLD - 0.001, DEDUP_SSIM_THRESHOLD)]) == [0, 1]


@pytest.mark.parametrize(
    ("prev", "cur", "expected"),
    [
        ("", "", "duplicate"),
        ("", "New title with content", "new"),
        ("Existing title with content", "", "new"),
        ("   \n\t", "   ", "duplicate"),
        ("Point A\nPoint B", "Point B\nPoint A\nPoint C adds enough new text", "incremental"),
        ("Point A\nPoint B", "Point B\nPoint A", "duplicate"),
    ],
)
def test_classify_slide_transition_adversarial_text_shapes(prev, cur, expected):
    assert classify_slide_transition(prev, cur) == expected


def test_dedupe_incremental_texts_keeps_long_build_up_with_interleaved_duplicates():
    texts = [
        "Title\nPoint 1 has enough words",
        "Title\nPoint 1 has enough words",
        "Title\nPoint 1 has enough words\nPoint 2 adds lots more context",
        "Title\nPoint 1 has enough words\nPoint 2 adds lots more context",
        "Title\nPoint 1 has enough words\nPoint 2 adds lots more context\nPoint 3 includes a detailed example",
        "Title\nPoint 1 has enough words\nPoint 2 adds lots more context\nPoint 3 includes a detailed example",
        "Appendix unrelated closing topic",
    ]

    assert dedupe_incremental_texts(texts) == [0, 2, 4, 6]


def test_parse_vtt_empty_malformed_comma_dot_and_tags_are_safe():
    assert parse_vtt("") == []
    assert parse_vtt("WEBVTT\n\nthis is not a cue\nno timestamp here") == []

    vtt = (
        "WEBVTT\n\n"
        "00:00:01,250 --> 00:00:02,000 align:start position:0%\n"
        "<v Speaker>Hello <c>world</c></v> <00:00:01.500>\n\n"
        "00:00:02.500 --> 00:00:03.000\n"
        "second cue\n"
    )

    segs = parse_vtt(vtt)
    assert [(seg.t, seg.text) for seg in segs] == [(1.25, "Hello world"), (2.5, "second cue")]


def test_parse_json3_empty_malformed_and_invalid_payload_contracts():
    assert parse_json3("{}") == []
    assert parse_json3(json.dumps({"events": [{"segs": []}, {"tStartMs": 1234, "segs": [{"utf8": "  "}]}]})) == []

    segs = parse_json3(json.dumps({"events": [{"tStartMs": 1250, "segs": [{"utf8": "Hello"}, {"utf8": " "}, {"utf8": "world"}]}]}))
    assert [(seg.t, seg.text) for seg in segs] == [(1.25, "Hello world")]

    with pytest.raises(json.JSONDecodeError):
        parse_json3("{not valid json")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?t=43", "dQw4w9WgXcQ"),
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://example.com/not-youtube", None),
        ("too-short", None),
    ],
)
def test_extract_video_id_adversarial_shapes(url, expected):
    assert extract_video_id(url) == expected
