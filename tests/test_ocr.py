"""Unit tests for OCR slide classification + re-split (AC-6). Pure, offline."""

from lectural.ocr import (
    classify_slide_transition,
    dedupe_incremental_texts,
    is_slide,
)


def test_is_slide_threshold():
    assert is_slide("Chapter 1: Introduction to Systems") is True
    assert is_slide("  ") is False
    assert is_slide("ok") is False  # too short


def test_duplicate_collapses():
    assert classify_slide_transition("A B C line", "A B C line") == "duplicate"


def test_incremental_buildup_kept():
    prev = "Title\nPoint one"
    cur = "Title\nPoint one\nPoint two added here"
    assert classify_slide_transition(prev, cur) == "incremental"


def test_unrelated_is_new():
    prev = "Topic A overview and details"
    cur = "Completely different topic B content"
    assert classify_slide_transition(prev, cur) == "new"


def test_incremental_below_growth_is_duplicate():
    prev = "Some long stable slide body text that barely changes"
    cur = prev + " ."  # negligible growth
    assert classify_slide_transition(prev, cur) == "duplicate"


def test_incremental_slide_resplit_keeps_each_step():
    # A slide built up line by line must NOT collapse to one frame.
    texts = [
        "Agenda",
        "Agenda\nItem 1 introduction",
        "Agenda\nItem 1 introduction\nItem 2 main concept",
        "Agenda\nItem 1 introduction\nItem 2 main concept",  # duplicate of prev
        "New section header entirely different",
    ]
    kept = dedupe_incremental_texts(texts)
    # indices 0,1,2 (build-up) + 4 (new); index 3 (dup) dropped.
    assert kept == [0, 1, 2, 4]
