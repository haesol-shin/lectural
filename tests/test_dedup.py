"""Unit tests for frame dedup selection (AC-5). Pure, offline."""

import pytest

from lectural import visual
from lectural.visual import (
    PHASH_HAMMING_THRESHOLD,
    Frame,
    advance_dedupe_state,
    cleanup_raw_frames,
    initial_dedupe_state,
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


def test_advance_dedupe_state_replays_persistence_and_fails_closed_without_evaluator():
    state = initial_dedupe_state(0)
    changed = (1 << 17) - 1
    state, pending = advance_dedupe_state(state, 1, changed)
    assert pending["event"] == "phash_change_pending"
    state, terminal = advance_dedupe_state(state, 2, changed)
    assert terminal["event"] == "persistent_candidate"
    assert terminal["evaluator_result"] == "not_same"
    assert state["kept_index"] == 1


def test_advance_dedupe_state_keeps_reference_when_shared_evaluator_accepts():
    state = initial_dedupe_state(0)
    changed = (1 << 17) - 1
    state, _ = advance_dedupe_state(state, 1, changed)
    state, terminal = advance_dedupe_state(state, 2, changed, evaluate=lambda *_: "same")
    assert terminal["evaluator_result"] == "same"
    assert state["kept_index"] == 0


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


def test_dedupe_frames_confirms_persistent_change_with_bounded_decodes(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    base = Image.new("RGB", (80, 40), "white")
    changed = Image.new("RGB", (80, 40), "black")
    paths = [tmp_path / name for name in ("a.png", "b1.png", "b2.png")]
    base.save(paths[0]); changed.save(paths[1]); changed.save(paths[2])
    frames = [Frame(float(index), str(path)) for index, path in enumerate(paths)]

    assert visual.dedupe_frames(frames) == [frames[0], frames[1]]
    assert frames[1].meta["dedupe_decision"] == "kept_distinct"
    assert frames[1].meta["width"] == 80
    assert frames[1].meta["height"] == 40
    assert "hist_corr" in frames[1].meta and "ssim" in frames[1].meta


def test_structural_duplicate_decodes_each_host_frame_once(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    base = Image.new("RGB", (80, 40), "white")
    drift = base.copy()
    for x in range(15):
        drift.putpixel((x, 0), (0, 0, 0))
    paths = [tmp_path / f"{index}.png" for index in range(4)]
    base.save(paths[0]); drift.save(paths[1]); drift.save(paths[2]); base.save(paths[3])
    frames = [Frame(float(index), str(path)) for index, path in enumerate(paths)]
    decoded = []
    real_decode = visual._decode_image
    monkeypatch.setattr(visual, "_decode_image", lambda path: decoded.append(path) or real_decode(path))

    visual.dedupe_frames(frames)

    assert decoded.count(str(paths[1])) == 1
    assert frames[1].meta["dedupe_decision"] == "structural_duplicate"


def test_phash_near_sequence_never_starts_alignment_worker(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    path = tmp_path / "same.png"
    Image.new("RGB", (80, 40), "white").save(path)
    frames = [Frame(float(index), str(path)) for index in range(3)]

    def fail_worker(*_args, **_kwargs):
        raise AssertionError("pHash-near frames must not start ORB")

    monkeypatch.setattr(visual, "AlignmentWorker", fail_worker)

    assert visual.dedupe_frames(frames) == [frames[0]]


def test_dedupe_reuses_one_worker_and_fails_closed(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    path = tmp_path / "frame.png"
    Image.new("RGB", (80, 40), "white").save(path)
    frames = [Frame(float(index), str(path)) for index in range(5)]
    hashes = iter([0, (1 << 17) - 1, (1 << 17) - 1, (1 << 34) - (1 << 17), (1 << 34) - (1 << 17)])
    monkeypatch.setattr(visual, "_image_phash_from_array", lambda *_args: next(hashes))
    instances = []

    class FakeWorker:
        def __init__(self, thresholds):
            self.thresholds = thresholds
            self.comparisons = []
            self.closed = False
            instances.append(self)

        def compare(self, reference, candidate):
            self.comparisons.append((reference, candidate))
            return {
                "result": "unavailable",
                "first_failed_gate": "opencv",
                "opencv_available": False,
                "direct_same": False,
                "direct_metrics": {"hist_corr": 0.0, "ssim": 0.0},
                "source_phash": {"reference": 0, "candidate": 0},
                "identity_content_change": {"by_pixel_delta": {"64": None}},
                "aligned_content_change": {"by_pixel_delta": {"64": None}},
            }

        def close(self):
            self.closed = True

    monkeypatch.setattr(visual, "AlignmentWorker", FakeWorker)

    assert visual.dedupe_frames(frames) == [frames[0], frames[1], frames[3]]
    assert len(instances) == 1
    assert len(instances[0].comparisons) == 2
    assert instances[0].closed is True
    assert frames[1].meta["alignment_result"] == "unavailable"
    assert frames[3].meta["alignment_first_failed_gate"] == "opencv"


def test_image_phash_reads_non_ascii_path(tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")

    frames_dir = tmp_path / "96강-강박장애-프레임"
    frames_dir.mkdir()
    image_path = frames_dir / "frame_00000.png"
    image = Image.new("L", (48, 48))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            pixels[x, y] = (x * 5 + y * 3) % 256
    image.save(image_path)

    assert isinstance(visual._image_phash(str(image_path)), int)


def test_cleanup_raw_frames_default_removes_non_final_images(tmp_path):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    paths = [frames_dir / f"frame_{index:05d}.png" for index in range(1, 4)]
    for path in paths:
        path.write_text(path.name, encoding="utf-8")
    stale_raw = frames_dir / "raw"
    stale_raw.mkdir()
    (stale_raw / "stale.png").write_text("stale", encoding="utf-8")

    raw_frames = [Frame(timestamp=float(index), image_path=str(path)) for index, path in enumerate(paths)]
    final_slides = [raw_frames[1]]

    result = cleanup_raw_frames(raw_frames, final_slides)

    assert paths[1].read_text(encoding="utf-8") == "frame_00002.png"
    assert not paths[0].exists()
    assert not paths[2].exists()
    assert not (frames_dir / "raw").exists()
    assert result["removed"] == [str(paths[0].resolve()), str(paths[2].resolve())]


def test_cleanup_raw_frames_keep_mode_archives_raw_and_keeps_final_links(tmp_path):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    paths = [frames_dir / f"frame_{index:05d}.png" for index in range(1, 4)]
    for path in paths:
        path.write_text(path.name, encoding="utf-8")

    raw_frames = [Frame(timestamp=float(index), image_path=str(path)) for index, path in enumerate(paths)]
    final_slides = [raw_frames[1]]

    result = cleanup_raw_frames(raw_frames, final_slides, keep_frames=True)

    assert sorted(p.name for p in frames_dir.glob("*.png")) == ["frame_00002.png"]
    assert sorted(p.name for p in (frames_dir / "raw").glob("*.png")) == [
        "frame_00001.png",
        "frame_00002.png",
        "frame_00003.png",
    ]
    assert (frames_dir / "raw" / "frame_00002.png").read_text(encoding="utf-8") == "frame_00002.png"
    assert result["raw_dir"] == str((frames_dir / "raw").resolve())
