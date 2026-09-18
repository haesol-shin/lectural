"""Unit tests for lectural_bench.metrics with hand-computed test fixtures."""

from __future__ import annotations

import math
from pathlib import Path
import sys
import pytest

# Safeguard: allow importing lectural_bench without re-installing editable package
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from lectural_bench.metrics import (
    frame_recall_and_duplicate_rate,
    levenshtein_distance,
    merge_spans,
    normalize_basic,
    normalize_korean,
    ocr_quality,
    subtract_spans,
    terminology_recall,
    timestamp_error,
    voiced_recall_and_gap,
    wer_cer,
)


# --- 1. wer_cer Tests --------------------------------------------------------


def test_wer_cer_exact_match_en():
    res = wer_cer("the cat sat", "the cat sat", "en")
    assert res == {"wer": 0.0, "cer": 0.0}


def test_wer_cer_single_substitution_en():
    # gt: "the cat sat" (3 words, 11 chars)
    # hyp: "the dog sat" (3 words, 11 chars)
    # word diff: "cat" -> "dog" (1 substitution / 3 words = 1/3)
    # char diff: 'c','a','t' -> 'd','o','g' (3 char substitutions / 11 chars = 3/11)
    res = wer_cer("the cat sat", "the dog sat", "en")
    assert math.isclose(res["wer"], 1 / 3, rel_tol=1e-5)
    assert math.isclose(res["cer"], 3 / 11, rel_tol=1e-5)


def test_wer_cer_punctuation_and_case_normalization():
    res = wer_cer("The Cat Sat!", "the cat sat", "en")
    assert res == {"wer": 0.0, "cer": 0.0}


def test_wer_cer_empty_strings():
    assert wer_cer("", "", "en") == {"wer": 0.0, "cer": 0.0}
    assert wer_cer("the cat", "", "en") == {"wer": 1.0, "cer": 1.0}
    assert wer_cer("", "the cat", "en") == {"wer": 1.0, "cer": 1.0}


def test_wer_cer_korean_exact():
    res = wer_cer("인공지능 개론", "인공지능 개론", "ko")
    assert res == {"wer": 0.0, "cer": 0.0}


def test_wer_cer_korean_space_insensitivity():
    # In Korean, Hangul syllable CER must be space-insensitive
    res = wer_cer("인공지능개론", "인공 지능 개론", "ko")
    assert res["cer"] == 0.0


def test_wer_cer_korean_substitution():
    # gt: "인공지능 개론" -> syllables: "인공지능개론" (6 syllables)
    # hyp: "인공지능 심화" -> syllables: "인공지능심화" (6 syllables)
    # CER: "개론" -> "심화" (2 edits / 6 = 1/3)
    # WER: 1 word substituted / 2 words = 0.5
    res = wer_cer("인공지능 개론", "인공지능 심화", "ko")
    assert math.isclose(res["cer"], 2 / 6, rel_tol=1e-5)
    assert math.isclose(res["wer"], 0.5, rel_tol=1e-5)


def test_wer_cer_mixed_language():
    res = wer_cer("Python 3.11 프로그래밍", "Python 3.11 프로그래밍", "mixed")
    assert res == {"wer": 0.0, "cer": 0.0}


# --- 2. terminology_recall Tests ---------------------------------------------


def test_terminology_recall_empty_terms():
    assert terminology_recall([], "Some hypothesis text.", "en") == 1.0


def test_terminology_recall_all_recalled():
    terms = ["gradient descent", "backpropagation"]
    hyp = "Today we study gradient descent and backpropagation."
    assert terminology_recall(terms, hyp, "en") == 1.0


def test_terminology_recall_case_and_punctuation():
    terms = ["Gradient Descent", "Back-Propagation"]
    hyp = "Today we study gradient descent and back propagation."
    assert terminology_recall(terms, hyp, "en") == 1.0


def test_terminology_recall_partial():
    terms = ["gradient descent", "transformer", "attention"]
    hyp = "Gradient descent and attention mechanisms are critical."
    assert math.isclose(terminology_recall(terms, hyp, "en"), 2 / 3, rel_tol=1e-5)


def test_terminology_recall_korean():
    terms = ["경사하강법", "오차역전파"]
    hyp = "경사하강법 알고리즘을 사용합니다."
    assert math.isclose(terminology_recall(terms, hyp, "ko"), 0.5, rel_tol=1e-5)


def test_terminology_recall_none_recalled():
    terms = ["convolutional layer", "pooling"]
    hyp = "Pure recurrent network without convolution."
    assert terminology_recall(terms, hyp, "en") == 0.0


# --- 3. timestamp_error Tests ------------------------------------------------


def test_timestamp_error_empty_gt():
    res = timestamp_error([], [1.0, 2.0, 3.0])
    assert res == {"median_sec": 0.0, "p95_sec": 0.0}


def test_timestamp_error_empty_hyp():
    res = timestamp_error([1.0, 2.0], [])
    assert res == {"median_sec": float("inf"), "p95_sec": float("inf")}


def test_timestamp_error_hand_computed():
    # gt:  [10.0, 20.0, 30.0]
    # hyp: [10.2, 20.0, 30.5]
    # nearest errors:
    #   gt 10.0 -> nearest 10.2 -> error = 0.2
    #   gt 20.0 -> nearest 20.0 -> error = 0.0
    #   gt 30.0 -> nearest 30.5 -> error = 0.5
    # sorted errors: [0.0, 0.2, 0.5]
    # median: 0.2
    # p95: linear interpolation index k = (3 - 1) * 0.95 = 1.9
    #      val = 0.2 * 0.1 + 0.5 * 0.9 = 0.02 + 0.45 = 0.47
    res = timestamp_error([10.0, 20.0, 30.0], [10.2, 20.0, 30.5])
    assert math.isclose(res["median_sec"], 0.2, rel_tol=1e-5)
    assert math.isclose(res["p95_sec"], 0.47, rel_tol=1e-5)


def test_timestamp_error_exact_single_cue():
    res = timestamp_error([5.0], [5.0])
    assert res == {"median_sec": 0.0, "p95_sec": 0.0}


# --- 4. voiced_recall_and_gap Tests -----------------------------------------


def test_voiced_recall_and_gap_empty_gt():
    res = voiced_recall_and_gap([], [(0.0, 5.0)])
    assert res == {"recall": 1.0, "max_untranscribed_gap_sec": 0.0}


def test_voiced_recall_and_gap_empty_det():
    res = voiced_recall_and_gap([(0.0, 10.0)], [])
    assert res == {"recall": 0.0, "max_untranscribed_gap_sec": 10.0}


def test_voiced_recall_and_gap_two_intervals():
    # gt: [(0.0, 10.0), (15.0, 25.0)] -> total gt duration = 20.0s
    # det: [(0.0, 10.0), (18.0, 25.0)]
    # overlap: (0..10) = 10.0s, (18..25) = 7.0s -> total overlap = 17.0s
    # recall = 17.0 / 20.0 = 0.85
    # uncovered gt: (15.0..18.0) -> gap = 3.0s
    res = voiced_recall_and_gap([(0.0, 10.0), (15.0, 25.0)], [(0.0, 10.0), (18.0, 25.0)])
    assert math.isclose(res["recall"], 0.85, rel_tol=1e-5)
    assert math.isclose(res["max_untranscribed_gap_sec"], 3.0, rel_tol=1e-5)


def test_voiced_recall_and_gap_full_coverage():
    res = voiced_recall_and_gap([(1.0, 5.0)], [(0.0, 6.0)])
    assert res == {"recall": 1.0, "max_untranscribed_gap_sec": 0.0}


# --- 5. frame_recall_and_duplicate_rate Tests -------------------------------


def test_frame_recall_and_duplicate_rate_empty_gt():
    res = frame_recall_and_duplicate_rate([], [1.0, 2.0], [1.0, 2.0, 3.0])
    assert res["recall"] == 1.0
    assert math.isclose(res["duplicate_rate"], 1.0 - 2 / 3, rel_tol=1e-5)


def test_frame_recall_and_duplicate_rate_hand_computed():
    # gt slide changes: [0.0, 15.0, 30.0]
    # kept frames: [0.2, 14.9, 45.0] (3 frames)
    # all candidates: 10 frames
    # tolerance: 1.0s
    # 0.0 matched by 0.2 (diff 0.2 <= 1.0) -> Yes
    # 15.0 matched by 14.9 (diff 0.1 <= 1.0) -> Yes
    # 30.0 not matched (nearest 45.0, diff 15.0 > 1.0) -> No
    # recall = 2 / 3
    # duplicate_rate = 1 - 3 / 10 = 0.7
    gt = [0.0, 15.0, 30.0]
    kept = [0.2, 14.9, 45.0]
    candidates = [0.0, 0.2, 5.0, 10.0, 14.9, 20.0, 25.0, 30.0, 40.0, 45.0]
    res = frame_recall_and_duplicate_rate(gt, kept, candidates, tolerance_sec=1.0)
    assert math.isclose(res["recall"], 2 / 3, rel_tol=1e-5)
    assert math.isclose(res["duplicate_rate"], 0.7, rel_tol=1e-5)


def test_frame_recall_and_duplicate_rate_no_candidates():
    res = frame_recall_and_duplicate_rate([1.0], [], [])
    assert res == {"recall": 0.0, "duplicate_rate": 0.0}


# --- 6. ocr_quality Tests ---------------------------------------------------


def test_ocr_quality_exact_match():
    key_fields = {"title": "Gradient Descent", "formula": "w = w - lr * dw"}
    ocr_text = "Gradient Descent\nw = w - lr * dw"
    res = ocr_quality(key_fields, ocr_text, usable_threshold_chars=8)
    assert math.isclose(res["cer"], 0.0, rel_tol=1e-5)
    assert res["key_field_recall_exact"] == 1.0
    assert res["key_field_recall_fuzzy"] == 1.0
    assert res["usable"] is True


def test_ocr_quality_fuzzy_vs_exact():
    key_fields = {"title": "Gradient Descent", "formula": "w = w - lr * dw"}
    # OCR corrupted "Gradient" to "Graclient"
    ocr_text = "Graclient Descent\nw = w - lr * dw"
    res = ocr_quality(key_fields, ocr_text, usable_threshold_chars=8)
    # "w = w - lr * dw" is exact (1/2 = 0.5)
    # "Graclient Descent" matches fuzzy (> 0.8 ratio), so both match fuzzy (2/2 = 1.0)
    assert math.isclose(res["key_field_recall_exact"], 0.5, rel_tol=1e-5)
    assert math.isclose(res["key_field_recall_fuzzy"], 1.0, rel_tol=1e-5)
    assert res["usable"] is True
    assert res["cer"] > 0.0


def test_ocr_quality_unusable_threshold():
    key_fields = {"title": "Slide Title"}
    ocr_text = "ab"  # 2 chars < usable_threshold_chars=8
    res = ocr_quality(key_fields, ocr_text, usable_threshold_chars=8)
    assert res["usable"] is False


def test_ocr_quality_empty_key_fields():
    res = ocr_quality({}, "Some OCR text", usable_threshold_chars=5)
    assert res["key_field_recall_exact"] == 1.0
    assert res["key_field_recall_fuzzy"] == 1.0
    assert res["usable"] is True


# --- 7. Pure Helper Unit Tests -----------------------------------------------


def test_levenshtein_distance():
    assert levenshtein_distance("kitten", "sitting") == 3
    assert levenshtein_distance("", "abc") == 3
    assert levenshtein_distance("abc", "") == 3
    assert levenshtein_distance("same", "same") == 0
    assert levenshtein_distance(["a", "b"], ["a", "c"]) == 1


def test_normalize_korean():
    assert normalize_korean("안녕하세요, 반갑습니다! 123") == "안녕하세요반갑습니다"


def test_normalize_basic():
    assert normalize_basic("  Hello,  World!  ") == "hello world"


def test_merge_and_subtract_spans():
    spans = [(0.0, 5.0), (3.0, 8.0), (10.0, 12.0)]
    merged = merge_spans(spans)
    assert merged == [(0.0, 8.0), (10.0, 12.0)]

    cut = [(2.0, 4.0), (11.0, 15.0)]
    sub = subtract_spans(merged, cut)
    assert sub == [(0.0, 2.0), (4.0, 8.0), (10.0, 11.0)]


# --- 8. Lazy Import Branch Tests ---------------------------------------------


def test_wer_cer_lazy_import_jiwer_and_whisper_normalizer(monkeypatch):
    from unittest.mock import MagicMock

    mock_jiwer = MagicMock()
    mock_jiwer.wer.return_value = 0.125
    mock_jiwer.cer.return_value = 0.05
    monkeypatch.setitem(sys.modules, "jiwer", mock_jiwer)

    mock_wn_mod = MagicMock()
    mock_wn_class = MagicMock()
    mock_wn_instance = MagicMock(side_effect=lambda x: x.lower())
    mock_wn_class.return_value = mock_wn_instance
    mock_wn_mod.EnglishTextNormalizer = mock_wn_class
    monkeypatch.setitem(sys.modules, "whisper_normalizer", MagicMock())
    monkeypatch.setitem(sys.modules, "whisper_normalizer.english", mock_wn_mod)

    res = wer_cer("Hello World", "hello world", "en")
    assert res == {"wer": 0.125, "cer": 0.05}


def test_ocr_quality_lazy_import_levenshtein(monkeypatch):
    from unittest.mock import MagicMock

    mock_lev = MagicMock()
    mock_lev.distance.return_value = 1
    mock_lev.ratio.return_value = 0.92
    monkeypatch.setitem(sys.modules, "Levenshtein", mock_lev)

    key_fields = {"term": "Gradient Descent"}
    ocr_text = "Graclient Descent"
    res = ocr_quality(key_fields, ocr_text, usable_threshold_chars=5)
    assert res["key_field_recall_fuzzy"] == 1.0
    assert math.isclose(res["cer"], 1 / len("Gradient Descent"), rel_tol=1e-5)
