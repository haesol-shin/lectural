"""Unit tests for frame dedup selection (AC-5). Pure, offline."""

from lectural import visual
from lectural.visual import (
    PHASH_HAMMING_THRESHOLD,
    Frame,
    is_same_phash,
    is_same_slide,
    parse_frame_timestamp_from_filename,
    phash_hamming_distance,
    select_keyframe_indices,
    select_phash_keyframe_indices,
)


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
def test_phash_threshold_edges():
    base = 0
    near = (1 << 10) - 1
    edge = (1 << PHASH_HAMMING_THRESHOLD) - 1
    far = (1 << (PHASH_HAMMING_THRESHOLD + 1)) - 1

    assert phash_hamming_distance(base, near) == 10
    assert phash_hamming_distance(base, far) == 13
    assert is_same_phash(base, edge) is True
    assert is_same_phash(base, far) is False


def test_phash_duplicate_pair_within_ten_collapses():
    base = 0
    near_dup = (1 << 10) - 1

    assert select_phash_keyframe_indices([base, near_dup, near_dup]) == [0]


def test_phash_distinct_slide_distance_seventeen_stays_separate_after_persistence():
    slide_a = 0
    slide_b = (1 << 17) - 1

    assert phash_hamming_distance(slide_a, slide_b) == 17
    assert select_phash_keyframe_indices([slide_a, slide_b, slide_b]) == [0, 1]


def test_phash_candidate_requires_two_consecutive_changed_samples():
    slide_a = 0
    transient = (1 << 17) - 1
    slide_b = ((1 << 17) - 1) << 17

    assert select_phash_keyframe_indices([slide_a, transient, slide_a]) == [0]
    assert select_phash_keyframe_indices([slide_a, transient, slide_b, slide_b]) == [0, 2]


def test_frame_timestamp_parsing_from_extracted_names():
    assert parse_frame_timestamp_from_filename("frames/frame_00042.png", fps=2.0) == (
        21.0,
        "filename_pts_over_fps",
    )
    assert parse_frame_timestamp_from_filename("frames/frame_12.5.png", fps=2.0) == (
        12.5,
        "filename_seconds",
    )
    assert parse_frame_timestamp_from_filename("frames/not-a-frame.png", fps=2.0) == (
        0.0,
        "fallback_unparseable",
    )


def test_dedupe_frames_routes_through_phash_with_metadata(monkeypatch):
    slide_a = 0
    slide_b = (1 << 17) - 1
    hashes = {"a.png": slide_a, "b1.png": slide_b, "b2.png": slide_b}
    frames = [
        Frame(timestamp=0.0, image_path="a.png"),
        Frame(timestamp=10.0, image_path="b1.png"),
        Frame(timestamp=10.5, image_path="b2.png"),
    ]

    monkeypatch.setattr(visual, "_image_phash", lambda path: hashes[path])

    assert visual.dedupe_frames(frames) == [frames[0], frames[1]]
    assert frames[1].meta["phash"] == f"{slide_b:016x}"
    assert frames[1].meta["phash_hamming_from_previous"] == 17
    assert frames[1].meta["phash_hamming_threshold"] == PHASH_HAMMING_THRESHOLD
