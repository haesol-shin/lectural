"""Unit tests for the speech-coverage gap metric (AC-9). Pure, offline.

Critical contract: legitimate silence must PASS; a real untranscribed
speech span longer than MAX_GAP_SEC must FAIL.
"""

from lectural.config import MAX_GAP_SEC
from lectural.vad import (
    invert_spans,
    max_non_silence_untranscribed_gap,
    merge_spans,
    parse_silencedetect,
    subtract_spans,
    transcript_coverage_spans,
)


def test_merge_and_invert_spans():
    assert merge_spans([(0, 5), (4, 8), (10, 12)]) == [(0, 8), (10, 12)]
    assert invert_spans([(0, 5), (10, 12)], 0, 20) == [(5, 10), (12, 20)]


def test_subtract_spans():
    assert subtract_spans([(0, 100)], [(10, 20), (30, 40)]) == [
        (0, 10),
        (20, 30),
        (40, 100),
    ]


def test_long_silence_passes():
    # Speech only in [0,30] and [600,630]; the [30,600] gap is SILENCE.
    speech = [(0, 30), (600, 630)]
    # Transcript covers both speech spans fully.
    coverage = transcript_coverage_spans([0, 10, 20, 600, 610, 620], duration=630)
    gap = max_non_silence_untranscribed_gap(speech, coverage)
    assert gap <= MAX_GAP_SEC  # PASS: silence is not a gap


def test_real_speech_gap_fails():
    # Continuous speech 0..300, but transcript stops at 100 and resumes 280.
    speech = [(0, 300)]
    coverage = transcript_coverage_spans([0, 50, 100, 280, 290], duration=300)
    gap = max_non_silence_untranscribed_gap(speech, coverage)
    assert gap > MAX_GAP_SEC  # FAIL: ~180s of speech untranscribed


def test_quiet_speech_fixture_small_gap_passes():
    # Speech with brief (<60s) untranscribed pockets between cues -> PASS.
    speech = [(0, 200)]
    coverage = transcript_coverage_spans([0, 30, 70, 110, 150, 190], duration=200)
    gap = max_non_silence_untranscribed_gap(speech, coverage)
    assert gap <= MAX_GAP_SEC


def test_parse_silencedetect_inverts_to_speech():
    stderr = (
        "[silencedetect @ 0x1] silence_start: 30.0\n"
        "[silencedetect @ 0x1] silence_end: 600.0 | silence_duration: 570\n"
    )
    speech = parse_silencedetect(stderr, duration=630.0)
    assert speech == [(0.0, 30.0), (600.0, 630.0)]
