"""Quality and accuracy metrics for LecturAL benchmark evaluation.

This module provides reproducible offline evaluation metrics for speech recognition,
technical terminology recall, timestamp alignment, voice-activity detection (VAD),
slide frame selection, and OCR extraction quality.

Fallback Strategy:
------------------
To support offline development and test environments without heavy benchmark
dependencies (such as jiwer, whisper-normalizer, or Levenshtein):
1. wer_cer: Lazy-imports jiwer and whisper_normalizer inside the function body.
   If unavailable, falls back cleanly to pure-Python text normalization and
   Levenshtein-based edit distance for WER/CER. For Korean ('ko'), a dedicated
   normalization path (normalize_korean) strips punctuation and whitespace to compute
   space-insensitive Hangul syllable CER independently of whisper_normalizer.
2. ocr_quality: Lazy-imports Levenshtein inside the function body. If unavailable,
   falls back cleanly to difflib.SequenceMatcher.ratio() for fuzzy key-field matching
   and the internal pure-Python levenshtein_distance for Character Error Rate (CER).
3. All other metrics (terminology_recall, timestamp_error, voiced_recall_and_gap,
   frame_recall_and_duplicate_rate) are implemented purely in Python using only the
   standard library.
"""

from __future__ import annotations

import bisect
import math
import re
import statistics
from typing import Sequence

Span = tuple[float, float]


# --- Pure Helpers (String & Edit Distance) -----------------------------------


def levenshtein_distance(s1: Sequence, s2: Sequence) -> int:
    """Pure: compute standard Levenshtein edit distance between two sequences."""
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)

    if len(s1) < len(s2):
        s1, s2 = s2, s1

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1] * (len(s2) + 1)
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (0 if c1 == c2 else 1)
            curr_row[j + 1] = min(insertions, deletions, substitutions)
        prev_row = curr_row
    return prev_row[-1]


def normalize_korean(text: str) -> str:
    """Pure: normalize Korean text: strip punctuation/whitespace, keep Hangul syllables, digits, and ASCII letters."""
    if not text:
        return ""
    # Modern Hangul syllables reside in Unicode range U+AC00..U+D7A3.
    # Preserves digits and ASCII letters for technical terms (e.g. 1956, 256, AI).
    return re.sub(r"[^\uac00-\ud7a30-9a-zA-Z]", "", text)

def normalize_basic(text: str) -> str:
    """Pure: basic text normalization: lowercase, strip punctuation, collapse whitespace."""
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _percentile(sorted_data: list[float], p: float) -> float:
    """Pure: compute the p-th percentile (0 <= p <= 100) using linear interpolation."""
    if not sorted_data:
        return 0.0
    if len(sorted_data) == 1:
        return float(sorted_data[0])
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_data[int(k)])
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return float(d0 + d1)


def _fuzzy_match_ratio(query: str, target: str) -> float:
    """Pure: compute the best similarity ratio between query and candidate substrings in target."""
    if not query:
        return 1.0 if not target else 0.0
    if not target:
        return 0.0

    q_norm = re.sub(r"\s+", " ", query.lower()).strip()
    t_norm = re.sub(r"\s+", " ", target.lower()).strip()
    if q_norm in t_norm:
        return 1.0

    def calc_ratio(s1: str, s2: str) -> float:
        try:
            import Levenshtein

            return float(Levenshtein.ratio(s1, s2))
        except ImportError:
            import difflib

            return float(difflib.SequenceMatcher(None, s1, s2).ratio())

    best = calc_ratio(q_norm, t_norm)
    if best >= 0.99:
        return best

    # Line candidates
    for line in target.splitlines():
        ln_norm = re.sub(r"\s+", " ", line.lower()).strip()
        if ln_norm:
            best = max(best, calc_ratio(q_norm, ln_norm))
            if best >= 0.99:
                return best

    # Sliding word window candidates matching query word count
    q_words = q_norm.split()
    t_words = t_norm.split()
    w_count = len(q_words)
    if w_count > 0 and len(t_words) >= w_count:
        window_sizes = [w for w in (w_count - 1, w_count, w_count + 1) if 1 <= w <= len(t_words)]
        for ws in window_sizes:
            for i in range(len(t_words) - ws + 1):
                candidate = " ".join(t_words[i : i + ws])
                best = max(best, calc_ratio(q_norm, candidate))
                if best >= 0.99:
                    return best

    # Single-word candidate check against tokens
    if w_count == 1 and len(q_norm) >= 3 and len(t_norm) > len(q_norm):
        tokens = re.findall(r"\w+", t_norm)
        for tok in tokens:
            if abs(len(tok) - len(q_norm)) <= 3:
                best = max(best, calc_ratio(q_norm, tok))
                if best >= 0.99:
                    return best

    return best


# --- Pure Helpers (Interval Algebra) -----------------------------------------


def merge_spans(spans: list[Span]) -> list[Span]:
    """Pure: sort and merge overlapping/adjacent intervals."""
    norm = [(min(a, b), max(a, b)) for a, b in spans if b > a or b == a]
    norm = [s for s in norm if s[1] > s[0]]
    norm.sort()
    merged: list[Span] = []
    for s, e in norm:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def subtract_spans(base: list[Span], cut: list[Span]) -> list[Span]:
    """Pure: base minus cut: portions of base not covered by cut."""
    cut_m = merge_spans(cut)
    out: list[Span] = []
    for b0, b1 in merge_spans(base):
        cursor = b0
        for c0, c1 in cut_m:
            if c1 <= cursor or c0 >= b1:
                continue
            if c0 > cursor:
                out.append((cursor, min(c0, b1)))
            cursor = max(cursor, c1)
            if cursor >= b1:
                break
        if cursor < b1:
            out.append((cursor, b1))
    return [s for s in out if s[1] > s[0]]


# --- Public Metric Functions (Contract) --------------------------------------


def wer_cer(ground_truth_text: str, hypothesis_text: str, language: str) -> dict:
    """Pure: compute WER and CER after language-appropriate normalization.

    Returns {"wer": float, "cer": float}.
    For English ('en') and mixed ('mixed') languages, uses whisper-normalizer and jiwer
    if installed, or falls back to pure-Python normalization and Levenshtein edit distance.
    For Korean ('ko'), uses space-insensitive Hangul syllable normalization (normalize_korean)
    that does not depend on whisper-normalizer.
    """
    lang = (language or "").strip().lower()

    if lang in ("ko", "korean"):
        gt_cer_norm = normalize_korean(ground_truth_text)
        hyp_cer_norm = normalize_korean(hypothesis_text)

        # CER computation (space-insensitive Hangul syllables). Guard the
        # empty-reference case before calling jiwer: an empty reference
        # against a non-empty hypothesis is conventionally 100% error, not
        # jiwer's raw insertions-over-empty-reference ratio (which is
        # unbounded and was only ever exercised by the pure-Python fallback
        # in offline testing, since jiwer is not installed there).
        if not gt_cer_norm:
            cer = 0.0 if not hyp_cer_norm else 1.0
        else:
            try:
                import jiwer

                cer = float(jiwer.cer(gt_cer_norm, hyp_cer_norm))
            except ImportError:
                cer = float(levenshtein_distance(gt_cer_norm, hyp_cer_norm) / len(gt_cer_norm))

        # WER computation on space-separated tokens
        gt_words = [w for w in re.sub(r"[^\w\s]", "", ground_truth_text or "").split() if w]
        hyp_words = [w for w in re.sub(r"[^\w\s]", "", hypothesis_text or "").split() if w]
        if not gt_words:
            wer = 0.0 if not hyp_words else 1.0
        else:
            wer = float(levenshtein_distance(gt_words, hyp_words) / len(gt_words))

        return {"wer": wer, "cer": cer}

    # English / mixed / other languages
    gt_norm: str | None = None
    hyp_norm: str | None = None

    try:
        if lang in ("en", "english"):
            from whisper_normalizer.english import EnglishTextNormalizer

            norm = EnglishTextNormalizer()
            gt_norm = norm(ground_truth_text or "")
            hyp_norm = norm(hypothesis_text or "")
        else:
            from whisper_normalizer.basic import BasicTextNormalizer

            norm = BasicTextNormalizer()
            gt_norm = norm(ground_truth_text or "")
            hyp_norm = norm(hypothesis_text or "")
    except ImportError:
        gt_norm = normalize_basic(ground_truth_text or "")
        hyp_norm = normalize_basic(hypothesis_text or "")

    if not gt_norm:
        wer = 0.0 if not (hyp_norm or "").strip() else 1.0
        cer = 0.0 if not hyp_norm else 1.0
    else:
        try:
            import jiwer

            wer = float(jiwer.wer(gt_norm, hyp_norm))
            cer = float(jiwer.cer(gt_norm, hyp_norm))
        except ImportError:
            gt_tokens = gt_norm.split()
            hyp_tokens = hyp_norm.split()
            wer = float(levenshtein_distance(gt_tokens, hyp_tokens) / len(gt_tokens))
            cer = float(levenshtein_distance(gt_norm, hyp_norm) / len(gt_norm))

    return {"wer": wer, "cer": cer}


def terminology_recall(
    ground_truth_terms: list[str], hypothesis_text: str, language: str
) -> float:
    """Pure: compute technical terminology recall (0.0 to 1.0).

    Checks whether each ground-truth technical term is present in the hypothesis text
    using case-insensitive substring and normalized-token matching.
    """
    if not ground_truth_terms:
        return 1.0

    hyp = hypothesis_text or ""
    hyp_lower = hyp.lower()
    clean_hyp = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", hyp_lower)).strip()

    recalled = 0
    for term in ground_truth_terms:
        if not term or not term.strip():
            continue
        t_lower = term.strip().lower()
        if t_lower in hyp_lower:
            recalled += 1
            continue
        clean_t = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t_lower)).strip()
        if clean_t and clean_t in clean_hyp:
            recalled += 1

    return float(recalled / len(ground_truth_terms))


def timestamp_error(
    ground_truth_cue_times: list[float], hypothesis_cue_times: list[float]
) -> dict:
    """Pure: compute cue-level nearest-neighbor absolute timestamp error.

    Returns {"median_sec": float, "p95_sec": float}.
    If ground_truth_cue_times is empty, returns 0.0 for both.
    If hypothesis_cue_times is empty while ground truth is non-empty, returns inf.
    """
    if not ground_truth_cue_times:
        return {"median_sec": 0.0, "p95_sec": 0.0}
    if not hypothesis_cue_times:
        return {"median_sec": float("inf"), "p95_sec": float("inf")}

    hyp_sorted = sorted(hypothesis_cue_times)
    errors: list[float] = []

    for gt_t in ground_truth_cue_times:
        idx = bisect.bisect_left(hyp_sorted, gt_t)
        candidates: list[float] = []
        if idx < len(hyp_sorted):
            candidates.append(abs(hyp_sorted[idx] - gt_t))
        if idx > 0:
            candidates.append(abs(hyp_sorted[idx - 1] - gt_t))
        errors.append(min(candidates))

    errors.sort()
    med = float(statistics.median(errors))
    p95 = float(_percentile(errors, 95.0))
    return {"median_sec": med, "p95_sec": p95}


def voiced_recall_and_gap(
    ground_truth_speech_spans: list[tuple[float, float]],
    detected_spans: list[tuple[float, float]],
) -> dict:
    """Pure: compute speech recall and max untranscribed speech gap.

    Returns {"recall": float, "max_untranscribed_gap_sec": float}.
    Interval overlap recall measures fraction of ground-truth speech duration
    covered by detected spans. max_untranscribed_gap_sec is the largest contiguous
    span of ground-truth speech without detection coverage.
    """
    gt_m = merge_spans(ground_truth_speech_spans)
    det_m = merge_spans(detected_spans)

    total_gt = sum(e - s for s, e in gt_m)
    if total_gt <= 0.0:
        return {"recall": 1.0, "max_untranscribed_gap_sec": 0.0}

    overlap_sec = 0.0
    for gs, ge in gt_m:
        for ds, de in det_m:
            inter = max(0.0, min(ge, de) - max(gs, ds))
            overlap_sec += inter

    recall = min(1.0, overlap_sec / total_gt)
    uncovered = subtract_spans(gt_m, det_m)
    max_gap = max((e - s for s, e in uncovered), default=0.0)

    return {"recall": float(recall), "max_untranscribed_gap_sec": float(max_gap)}


def frame_recall_and_duplicate_rate(
    ground_truth_slide_change_timestamps: list[float],
    kept_frame_timestamps: list[float],
    all_candidate_timestamps: list[float],
    tolerance_sec: float = 1.0,
    near_duplicate_timestamps: list[float] | None = None,
    incremental_timestamps: list[float] | None = None,
) -> dict:
    """Pure: compute slide-change recall, candidate drop rate, and near-dup/incremental retention.

    Returns {"recall": float, "duplicate_rate": float, "drop_rate": float, "near_duplicate_dropped": bool, "incremental_retained": bool}.
    For each ground-truth slide change, checks if any kept frame is within
    tolerance_sec. duplicate_rate is candidate drop rate: 1 - (len(kept) / len(all_candidates)).
    """
    if not ground_truth_slide_change_timestamps:
        recall = 1.0
    else:
        matched = sum(
            1
            for gt_t in ground_truth_slide_change_timestamps
            if any(abs(kf_t - gt_t) <= tolerance_sec for kf_t in kept_frame_timestamps)
        )
        recall = matched / len(ground_truth_slide_change_timestamps)

    if not all_candidate_timestamps:
        drop_rate = 0.0
    else:
        drop_rate = max(
            0.0,
            1.0 - (len(kept_frame_timestamps) / len(all_candidate_timestamps)),
        )

    if near_duplicate_timestamps:
        near_duplicate_dropped = not any(
            any(abs(kf_t - nd_t) <= tolerance_sec for kf_t in kept_frame_timestamps)
            for nd_t in near_duplicate_timestamps
        )
    else:
        near_duplicate_dropped = True

    if incremental_timestamps:
        incremental_retained = all(
            any(abs(kf_t - inc_t) <= tolerance_sec for kf_t in kept_frame_timestamps)
            for inc_t in incremental_timestamps
        )
    else:
        incremental_retained = True

    return {
        "recall": float(recall),
        "duplicate_rate": float(drop_rate),
        "drop_rate": float(drop_rate),
        "near_duplicate_dropped": bool(near_duplicate_dropped),
        "incremental_retained": bool(incremental_retained),
    }


def ocr_quality(
    ground_truth_key_fields: dict[str, str],
    ocr_text: str,
    usable_threshold_chars: int,
    fuzzy_threshold: float = 0.8,
    slide_reference_text: str | None = None,
) -> dict:
    """Pure: evaluate OCR quality metrics against ground truth slide text and key fields.

    Returns {"cer": float, "key_field_recall_exact": float, "key_field_recall_fuzzy": float, "usable": bool}.
    - usable: whether non-whitespace OCR character count >= usable_threshold_chars.
    - cer: Character Error Rate between reference slide text (or concatenated key fields) and OCR text.
    - key_field_recall_exact: fraction of key fields found verbatim (case-insensitive) in OCR text.
    - key_field_recall_fuzzy: fraction of key fields matching OCR text with similarity ratio >= fuzzy_threshold.
    Lazy-imports Levenshtein; falls back cleanly to difflib.SequenceMatcher.ratio() and pure-Python edit distance.
    """
    clean_chars = len(re.sub(r"\s+", "", ocr_text or ""))
    usable = clean_chars >= usable_threshold_chars

    if slide_reference_text is not None:
        ref_norm = re.sub(r"\s+", " ", slide_reference_text).strip()
    else:
        ref_norm = re.sub(r"\s+", " ", " ".join(str(v) for v in ground_truth_key_fields.values())).strip()
    hyp_norm = re.sub(r"\s+", " ", ocr_text or "").strip()

    if not ref_norm:
        cer = 0.0 if not hyp_norm else 1.0
    else:
        try:
            import Levenshtein

            dist = Levenshtein.distance(ref_norm, hyp_norm)
        except ImportError:
            dist = levenshtein_distance(ref_norm, hyp_norm)
        cer = float(dist / len(ref_norm))
    if not ground_truth_key_fields:
        return {
            "cer": cer,
            "key_field_recall_exact": 1.0,
            "key_field_recall_fuzzy": 1.0,
            "usable": usable,
        }

    exact_matches = 0
    fuzzy_matches = 0
    norm_ocr = re.sub(r"\s+", " ", (ocr_text or "").lower()).strip()

    for field_name, field_val in ground_truth_key_fields.items():
        val_str = str(field_val).strip()
        if not val_str:
            exact_matches += 1
            fuzzy_matches += 1
            continue

        norm_val = re.sub(r"\s+", " ", val_str.lower()).strip()
        if norm_val in norm_ocr:
            exact_matches += 1
            fuzzy_matches += 1
        else:
            best_ratio = _fuzzy_match_ratio(val_str, ocr_text or "")
            if best_ratio >= fuzzy_threshold:
                fuzzy_matches += 1

    total_fields = len(ground_truth_key_fields)
    return {
        "cer": cer,
        "key_field_recall_exact": float(exact_matches / total_fields),
        "key_field_recall_fuzzy": float(fuzzy_matches / total_fields),
        "usable": bool(usable),
    }
