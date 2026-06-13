"""Unit tests for frame dedup selection (AC-5). Pure, offline."""

from lectural.visual import is_same_slide, select_keyframe_indices


def test_identical_consecutive_frames_collapse():
    # Three frames, second & third identical to predecessor -> keep only first.
    metrics = [(0.99, 0.99), (0.995, 0.98)]
    assert select_keyframe_indices(metrics) == [0]


def test_distinct_slides_all_kept():
    # Each transition is clearly different -> keep every frame.
    metrics = [(0.10, 0.20), (0.05, 0.10), (0.30, 0.40)]
    assert select_keyframe_indices(metrics) == [0, 1, 2, 3]


def test_mixed_sequence_under_dedup_guard():
    # frame1 dup of 0, frame2 new, frame3 dup of 2 -> keep [0, 2].
    metrics = [(0.97, 0.96), (0.10, 0.10), (0.98, 0.95)]
    assert select_keyframe_indices(metrics) == [0, 2]


def test_over_dedup_guard_requires_both_metrics():
    # High histogram but low SSIM (e.g. same palette, different layout) ->
    # NOT the same slide, must be kept (guards against over-dedup).
    assert is_same_slide(0.99, 0.50) is False
    metrics = [(0.99, 0.50)]
    assert select_keyframe_indices(metrics) == [0, 1]


def test_single_or_empty_frame_sequence():
    assert select_keyframe_indices([]) == [0]
