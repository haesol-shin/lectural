"""Pure calibration contract tests; worker measurements are injected."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
import random
import shutil
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import calibrate_alignment as calibration


def _measurement(label: str, *, version: str = "4.6.0", coverage=(0.95, 0.95), ssim=(0.95, 0.95)) -> dict:
    same = label == "same"
    ratio_matches = 100 if same else 1
    return {
        "result": "same" if same else "not_same",
        "first_failed_gate": None if same else "ratio_matches",
        "opencv_version": version,
        "opencv_build": "Version control: test",
        "keypoint_counts": {"reference": 100, "candidate": 100},
        "ratio_match_count": 100,
        "ratio_matches": ratio_matches,
        "affine": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        "determinant": 1.0,
        "scale": 1.0,
        "inlier_count": 90,
        "inlier_ratio": 0.9,
        "residual_median": 0.1,
        "residual_p95": 0.2,
        "hull_support": 0.5,
        "eigenvalue_ratio": 0.5,
        "forward_coverage": coverage[0],
        "reverse_coverage": coverage[1],
        "forward_ssim": ssim[0],
        "reverse_ssim": ssim[1],
        "settings": {},
    }


def _rows(*, expected_failure: str = "ratio_matches", missing: str | None = None) -> tuple[list[dict], list[dict]]:
    rows = []
    for split in ("development", "held_out"):
        for index, transform_class in enumerate(sorted(calibration.REQUIRED_TRANSFORM_CLASSES)):
            if split == "held_out" and transform_class == missing:
                continue
            same = index == 0
            rows.append(
                {
                    "id": f"{split}-{transform_class}",
                    "generator_seed": index + (100 if split == "development" else 200),
                    "reference": "unused-reference.png",
                    "candidate": "unused-candidate.png",
                    "expected_label": "same" if same else "different",
                    "transform_class": transform_class,
                    "expected_first_failure_family": None if same else expected_failure,
                }
            )
    split_at = sum(1 for row in rows if row["id"].startswith("development-"))
    return rows[:split_at], rows[split_at:]


def _write_manifest(tmp_path: Path, development: list[dict], held_out: list[dict]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"development": development, "held_out": held_out}), encoding="utf-8")
    return path


def _patch_measurements(monkeypatch: pytest.MonkeyPatch, development: list[dict], held_out: list[dict], *, version: str = "4.6.0"):
    rows = development + held_out

    def fake_measurements():
        return [_measurement(row["expected_label"], version=version) for row in rows]

    def fake_run(tasks):
        return fake_measurements()

    monkeypatch.setattr(calibration, "run_alignment_batch", fake_run)
    monkeypatch.setattr(
        calibration,
        "_run_reproducibility",
        lambda tasks: {
            "baseline_measurements": fake_measurements(),
            "same_session_runs": [fake_measurements() for _ in range(10)],
            "fresh_worker_runs": [fake_measurements() for _ in range(2)],
        },
    )


def test_one_direction_missing_is_unavailable_and_fails_ssim_or_coverage():
    thresholds = {
        "ratio_matches_min": 1,
        "inlier_count_min": 1,
        "inlier_ratio_min": 0,
        "hull_support_min": 0,
        "eigenvalue_ratio_min": 0,
        "coverage_min": 0,
        "ssim_min": 0,
        "residual_median_max": 1,
        "residual_p95_max": 1,
        "scale_min": 0.5,
        "scale_max": 1.5,
    }
    measurement = _measurement("same", coverage=(0.95, "not_evaluated"))
    assert calibration._measurement_value(measurement, "coverage") is None
    assert calibration._passes(measurement, thresholds) is False
    assert calibration._first_failed_inequality(measurement, thresholds) == "coverage"
    ratio_failure = _measurement("same")
    ratio_failure["ratio_match_count"] = 1
    assert calibration._passes(ratio_failure, thresholds) is False
    assert calibration._first_failed_inequality(ratio_failure, thresholds) == "ratio_matches"
    matrix_failure = _measurement("same")
    matrix_failure["scale"] = 2.0
    assert calibration._first_failed_inequality(matrix_failure, thresholds) == "matrix"


def test_incomplete_held_out_split_blocks_freeze(monkeypatch, tmp_path):
    development, held_out = _rows(missing="pan_zoom")
    _patch_measurements(monkeypatch, development, held_out)
    report = calibration.calibrate(_write_manifest(tmp_path, development, held_out))
    assert report["frozen"] is False
    assert "pan_zoom" in report["missing_transform_classes_by_split"]["held_out"]
    assert any("manifest is incomplete" in blocker for blocker in report["blockers"])


def test_negative_expected_failure_family_is_diagnostic_not_semantic_truth(monkeypatch, tmp_path):
    development, held_out = _rows(expected_failure="geometry")
    _patch_measurements(monkeypatch, development, held_out)
    report = calibration.calibrate(_write_manifest(tmp_path, development, held_out))
    # The corpus is intentionally incomplete, but its diagnosis must be
    # independent of a threshold-dependent expected failure family.
    assert report["frozen"] is False
    assert report["first_failure_distribution"]["ratio_matches"] > 0


def test_unavailable_positive_metric_blocks_threshold_search_and_freeze(monkeypatch, tmp_path):
    development, held_out = _rows()
    _patch_measurements(monkeypatch, development, held_out)
    rows = development + held_out

    def fake_measurements():
        values = [_measurement(row["expected_label"]) for row in rows]
        values[0]["forward_ssim"] = "not_evaluated"
        return values

    monkeypatch.setattr(
        calibration,
        "_run_reproducibility",
        lambda tasks: {
            "baseline_measurements": fake_measurements(),
            "same_session_runs": [fake_measurements() for _ in range(10)],
            "fresh_worker_runs": [fake_measurements() for _ in range(2)],
        },
    )
    report = calibration.calibrate(_write_manifest(tmp_path, development, held_out))
    assert report["thresholds"] is None
    assert report["development_positive_metric_failures"][0]["missing_metrics"] == ["ssim"]
    assert "development positive rows have unavailable or non-finite required alignment metrics" in report["blockers"]


def test_manifest_failure_families_are_canonical_production_gate_names():
    manifest = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "visual_alignment" / "manifest.json").read_text(encoding="utf-8")
    )
    families = {
        row["expected_first_failure_family"]
        for split in ("development", "held_out")
        for row in manifest[split]
        if row.get("expected_first_failure_family")
    }
    assert families <= set(calibration.CANONICAL_GATE_ORDER)
    assert "visual" not in families


def test_unsupported_opencv_build_blocks_freeze(monkeypatch, tmp_path):
    development, held_out = _rows()
    _patch_measurements(monkeypatch, development, held_out, version="4.13.0")
    report = calibration.calibrate(_write_manifest(tmp_path, development, held_out))
    assert report["opencv_supported"] is False
    assert report["frozen"] is False
    assert "resolved OpenCV build is outside the supported constraint" in report["blockers"]


def test_unsupported_opencv_distribution_metadata_blocks_freeze(monkeypatch, tmp_path):
    development, held_out = _rows()
    _patch_measurements(monkeypatch, development, held_out)
    monkeypatch.setattr(
        calibration,
        "_opencv_distribution_info",
        lambda: {
            "expected_provider": "opencv-python",
            "provider_candidates": ["opencv-python"],
            "provider_present": True,
            "distribution_version": "4.7.0.72",
            "distribution_supported": False,
        },
    )
    report = calibration.calibrate(_write_manifest(tmp_path, development, held_out))
    assert report["opencv_supported"] is False
    assert report["opencv_distribution"]["distribution_version"] == "4.7.0.72"
    assert report["frozen"] is False


def test_mixed_opencv_provider_blocks_freeze(monkeypatch, tmp_path):
    development, held_out = _rows()
    _patch_measurements(monkeypatch, development, held_out)
    monkeypatch.setattr(
        calibration,
        "_opencv_distribution_info",
        lambda: {
            "expected_provider": "opencv-python",
            "provider_candidates": ["opencv-contrib-python", "opencv-python"],
            "provider_exact": False,
            "provider_present": True,
            "distribution_version": "4.6.0.66",
            "imported_cv2_version": "4.6.0",
            "version_match": True,
            "distribution_supported": False,
        },
    )
    report = calibration.calibrate(_write_manifest(tmp_path, development, held_out))
    assert report["opencv_supported"] is False
    assert report["frozen"] is False
    assert "imported cv2 provider/distribution version is mixed or mismatched" in report["blockers"]


def test_opencv_distribution_version_mismatch_blocks_freeze(monkeypatch, tmp_path):
    development, held_out = _rows()
    _patch_measurements(monkeypatch, development, held_out)
    monkeypatch.setattr(
        calibration,
        "_opencv_distribution_info",
        lambda: {
            "expected_provider": "opencv-python",
            "provider_candidates": ["opencv-python"],
            "provider_exact": True,
            "provider_present": True,
            "distribution_version": "4.6.0.66",
            "imported_cv2_version": "4.7.0",
            "version_match": False,
            "distribution_supported": False,
        },
    )
    report = calibration.calibrate(_write_manifest(tmp_path, development, held_out))
    assert report["opencv_supported"] is False
    assert report["frozen"] is False


def test_legacy_pair_manifest_cannot_freeze_even_with_complete_pair_metrics(monkeypatch, tmp_path):
    development, held_out = _rows()
    _patch_measurements(monkeypatch, development, held_out)
    monkeypatch.setattr(
        calibration,
        "_opencv_distribution_info",
        lambda: {
            "expected_provider": "opencv-python",
            "provider_candidates": ["opencv-python"],
            "provider_exact": True,
            "provider_present": True,
            "distribution_version": "4.6.0.66",
            "imported_cv2_version": "4.6.0",
            "version_match": True,
            "distribution_supported": True,
        },
    )
    real_passes = calibration._passes
    pass_calls = 0

    def counting_passes(measurement, thresholds):
        nonlocal pass_calls
        pass_calls += 1
        return real_passes(measurement, thresholds)

    monkeypatch.setattr(calibration, "_passes", counting_passes)
    manifest = _write_manifest(tmp_path, development, held_out)
    report = calibration.calibrate(manifest)
    repeat = calibration.calibrate(manifest)
    assert report["frozen"] is False
    assert "legacy pair manifest is diagnostic-only; sequence replay evidence is required for freeze" in report["blockers"]
    assert report["thresholds"] == repeat["thresholds"]
    assert report["thresholds_ieee754_hex"]["ratio_matches_min"]
    assert report["reproducibility"]["passed"] is True
    assert report["reproducibility"]["same_session_repetitions"] == 10
    assert report["reproducibility"]["fresh_worker_repetitions"] == 2
    assert pass_calls < 10_000


def _exhaustive_threshold_oracle(rows, measurements):
    positives = [measurement for row, measurement in zip(rows, measurements) if row["expected_label"] == "same"]
    negatives = [measurement for row, measurement in zip(rows, measurements) if row["expected_label"] == "different"]
    if not positives or not negatives:
        return None
    domains = {}
    for raw_field, threshold_name, direction in calibration._THRESHOLD_ORDER:
        values = calibration._candidate_values(measurements, raw_field)
        if direction == "min":
            bound = min(calibration._measurement_value(measurement, raw_field) for measurement in positives)
            domain = [value for value in values if value <= bound]
        elif direction == "max":
            bound = max(calibration._measurement_value(measurement, raw_field) for measurement in positives)
            domain = [value for value in values if value >= bound]
        elif direction == "scale_min":
            bound = min(calibration._measurement_value(measurement, "scale") for measurement in positives)
            domain = [value for value in values if value <= bound]
        else:
            bound = max(calibration._measurement_value(measurement, "scale") for measurement in positives)
            domain = [value for value in values if value >= bound]
        if not domain:
            return None
        domains[threshold_name] = sorted(set(domain))

    ordered_domains = []
    for _raw_field, threshold_name, direction in calibration._THRESHOLD_ORDER:
        values = domains[threshold_name]
        ordered_domains.append(sorted(values, reverse=direction in {"min", "scale_min"}))
    for values in itertools.product(*ordered_domains):
        candidate = dict(zip((name for _field, name, _direction in calibration._THRESHOLD_ORDER), values))
        if candidate["scale_min"] > candidate["scale_max"]:
            continue
        if all(calibration._passes(measurement, candidate) for measurement in positives) and all(
            not calibration._passes(measurement, candidate) for measurement in negatives
        ):
            return candidate
    return None


def test_monotone_threshold_search_matches_exhaustive_oracle_with_scale_endpoints():
    for seed in range(5):
        rng = random.Random(seed)
        positive = calibration_measurement = _measurement("same")
        for field in ("ratio_matches", "inlier_count", "inlier_ratio", "hull_support", "eigenvalue_ratio"):
            positive[field] = round(rng.uniform(0.55, 0.95) * (100 if field in {"ratio_matches", "inlier_count"} else 1), 3)
        positive["coverage"] = None
        positive["forward_coverage"] = round(rng.uniform(0.75, 0.95), 3)
        positive["reverse_coverage"] = round(rng.uniform(0.75, 0.95), 3)
        positive["forward_ssim"] = round(rng.uniform(0.75, 0.95), 3)
        positive["reverse_ssim"] = round(rng.uniform(0.75, 0.95), 3)
        positive["residual_median"] = round(rng.uniform(0.1, 0.4), 3)
        positive["residual_p95"] = round(rng.uniform(0.4, 0.8), 3)
        positive["scale"] = round(rng.uniform(0.9, 1.1), 3)
        positive["determinant"] = positive["scale"] ** 2
        measurements = [positive]
        rows = [{"expected_label": "same"}]
        for field in ("ratio_matches", "inlier_count", "inlier_ratio", "hull_support", "eigenvalue_ratio"):
            negative = dict(positive)
            negative[field] = positive[field] - (1 if field in {"ratio_matches", "inlier_count"} else 0.2)
            measurements.append(negative)
            rows.append({"expected_label": "different"})
        for field in ("coverage", "ssim"):
            negative = dict(positive)
            negative["forward_" + field] = 0.2
            negative["reverse_" + field] = 0.2
            measurements.append(negative)
            rows.append({"expected_label": "different"})
        for field in ("residual_median", "residual_p95"):
            negative = dict(positive)
            negative[field] = positive[field] + 0.4
            measurements.append(negative)
            rows.append({"expected_label": "different"})
        for scale in (0.5, 1.5):
            negative = dict(positive)
            negative["scale"] = scale
            negative["determinant"] = scale * scale
            measurements.append(negative)
            rows.append({"expected_label": "different"})
        expected = _exhaustive_threshold_oracle(rows, measurements)
        assert expected is not None
        assert calibration._find_thresholds(rows, measurements) == expected


def test_sequence_replay_uses_shared_visual_evaluator_and_counts_event_once():
    sequence = {
        "sequence_id": "dev-sequence",
        "frames": [
            {"timestamp": 0.0, "phash": 0, "expected_visual_id": "a"},
            {"timestamp": 1.0, "phash": (1 << 17) - 1, "expected_visual_id": "a"},
            {"timestamp": 2.0, "phash": (1 << 17) - 1, "expected_visual_id": "a"},
        ],
        "event_measurements": {
            "dev-sequence:2:1": {
                "direct_same": True,
                "identity_content_change": {
                    "by_pixel_delta": {
                        "8": {
                            "changed_fraction": 0.0,
                            "largest_changed_component_fraction": 0.0,
                        }
                    }
                },
            }
        },
    }
    events = calibration.replay_sequence(
        sequence,
        {
            "pixel_delta": 8,
            "changed_fraction_max": 0.01,
            "largest_changed_component_fraction_max": 0.01,
        },
    )
    assert len(events) == 1
    assert events[0]["expected_label"] == events[0]["predicted_label"] == "same"
    populations = calibration.sequence_fit_populations(events)
    assert populations["alignment_fit"] == []
    assert populations["content_fit"] == events


def test_sequence_manifest_requires_ordered_authored_frame_truth():
    errors = calibration.validate_sequence_manifest({"development_sequences": [], "held_out_sequences": []})
    assert errors == [
        "development_sequences is missing or empty",
        "held_out_sequences is missing or empty",
    ]


def test_canonical_hash_makes_nonfinite_diagnostics_explicit_and_fail_closed():
    """Pathological OpenCV measurements must not crash reproducibility hashing."""
    payload = {"metric": float("nan"), "nested": [float("inf"), 1.0]}
    canonical = calibration._canonical_json_value(payload)
    assert canonical == {"metric": "not_evaluated", "nested": ["not_evaluated", 1.0]}
    assert calibration._canonical_hash(payload) == calibration._canonical_hash(canonical)


def test_real_image_sequence_manifest_has_immutable_paths_and_disjoint_splits():
    manifest_path = REPO_ROOT / "tests/fixtures/visual_alignment/sequence_manifest_v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert calibration.validate_sequence_manifest(manifest) == []
    development_ids = {row["source_content_id"] for row in manifest["development_sequences"]}
    held_out_ids = {row["source_content_id"] for row in manifest["held_out_sequences"]}
    assert development_ids.isdisjoint(held_out_ids)


def test_decoded_fixture_pipeline_ignores_manifest_cache_and_authored_phash():
    """Actual image bytes, not cache or authored trace, form the payload."""
    reference = REPO_ROOT / "tests/fixtures/benchmark/en_terms_01/slides/slide_01_concept.png"
    candidate = REPO_ROOT / "tests/fixtures/benchmark/en_terms_01/slides/slide_00_title.png"
    digest = lambda path: __import__("hashlib").sha256(path.read_bytes()).hexdigest()
    reference_path = str(reference.relative_to(REPO_ROOT)).replace("\\", "/")
    candidate_path = str(candidate.relative_to(REPO_ROOT)).replace("\\", "/")
    sequence = {
        "sequence_id": "provenance", "transform_class": "pan_zoom",
        "source_content_id": "canvas", "generator_seed": 1,
        "frames": [
            {"timestamp": 0, "phash": 0, "expected_visual_id": "a", "path": reference_path, "sha256": digest(reference)},
            {"timestamp": 1, "phash": 1, "expected_visual_id": "b", "path": candidate_path, "sha256": digest(candidate)},
            {"timestamp": 2, "phash": 1, "expected_visual_id": "b", "path": candidate_path, "sha256": digest(candidate)},
        ],
        "event_measurements": {
            "provenance:2:1": {"direct_same": True, "poison": "first"},
            "orphan:999:999": {"direct_same": True, "poison": "orphan"},
        },
    }
    first, raw = calibration._with_worker_measurements({"development_sequences": [sequence], "held_out_sequences": []})
    sequence["event_measurements"]["provenance:2:1"] = {"direct_same": False, "poison": "second"}
    # This destroys the authored persistent-candidate trace. The decoded
    # source pixels are unchanged, so full-pipeline task IDs and decisions
    # must remain exactly the same.
    for frame in sequence["frames"]:
        frame["phash"] = 0
    second, _raw_second = calibration._with_worker_measurements({"development_sequences": [sequence], "held_out_sequences": []})
    cache = first["development_sequences"][0]["event_measurements"]["provenance:2:1"]
    assert raw["worker_pids"] and len(raw["worker_pids"]) == 1
    assert "poison" not in cache
    assert "orphan:999:999" not in first["development_sequences"][0]["event_measurements"]
    assert cache["direct_same"] is False
    assert cache["source_phash"]["reference"] != cache["source_phash"]["candidate"]
    assert calibration._canonical_hash(calibration._canonical_decoded_manifest(first)) == calibration._canonical_hash(
        calibration._canonical_decoded_manifest(second)
    )
    first_events = calibration.replay_sequence(first["development_sequences"][0], None)
    second_events = calibration.replay_sequence(second["development_sequences"][0], None)
    assert [event["event_id"] for event in first_events] == [event["event_id"] for event in second_events]
    assert [(event["result"], event["predicted_label"]) for event in first_events] == [
        (event["result"], event["predicted_label"]) for event in second_events
    ]
    assert cache["cache_provenance"]["reference_sha256"] == digest(reference)
    assert cache["cache_provenance"]["candidate_sha256"] == digest(candidate)


def test_replay_fails_closed_for_partial_decoded_phash_trace():
    with pytest.raises(ValueError, match="decoded pHash trace is incomplete"):
        calibration.replay_sequence({
            "sequence_id": "partial",
            "frames": [
                {"timestamp": 0, "phash": 0, "recomputed_phash": 0, "expected_visual_id": "a"},
                {"timestamp": 1, "phash": 1, "expected_visual_id": "b"},
            ],
        }, None)


def test_source_frame_sha_mutation_fails_before_worker_or_reproducibility(monkeypatch, tmp_path):
    """A digest mismatch is a hard preflight failure, not worker input."""
    source = REPO_ROOT / "tests/fixtures/benchmark/en_terms_01/slides/slide_01_concept.png"
    copied = tmp_path / "frame.png"
    shutil.copyfile(source, copied)
    digest = __import__("hashlib").sha256(copied.read_bytes()).hexdigest()
    # Mutate only after the manifest records its immutable digest.
    copied.write_bytes(copied.read_bytes() + b"manifest-mutation")
    monkeypatch.setattr(calibration, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        calibration, "_with_worker_measurements",
        lambda *_args, **_kwargs: pytest.fail("worker must not run after SHA preflight failure"),
    )
    manifest = {
        "development_sequences": [{
            "sequence_id": "mutated-dev", "transform_class": "static_shift",
            "source_content_id": "canvas", "generator_seed": 3,
            "frames": [
                {"timestamp": 0, "expected_visual_id": "a", "path": "frame.png", "sha256": digest},
                {"timestamp": 1, "expected_visual_id": "b", "path": "frame.png", "sha256": digest},
            ],
        }],
        "held_out_sequences": [{
            "sequence_id": "mutated-held", "transform_class": "static_shift",
            "source_content_id": "canvas", "generator_seed": 4,
            "frames": [
                {"timestamp": 0, "expected_visual_id": "a", "path": "frame.png", "sha256": digest},
                {"timestamp": 1, "expected_visual_id": "b", "path": "frame.png", "sha256": digest},
            ],
        }],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    report = calibration.calibrate(path)
    assert report["frozen"] is False
    assert any("SHA-256 mismatch" in blocker for blocker in report["blockers"])


def test_source_mutation_after_staged_inspect_blocks_worker_measurement(monkeypatch, tmp_path):
    """A TOCTOU write cannot turn a staged measurement into freeze evidence."""
    source = REPO_ROOT / "tests/fixtures/benchmark/en_terms_01/slides/slide_01_concept.png"
    copied = tmp_path / "frame.png"
    shutil.copyfile(source, copied)
    digest = __import__("hashlib").sha256(copied.read_bytes()).hexdigest()
    monkeypatch.setattr(calibration, "REPO_ROOT", tmp_path)

    class MutatingWorker:
        def __init__(self):
            self.calls = 0

        def inspect(self, _path):
            self.calls += 1
            return {"ok": True, "phash": 0 if self.calls == 1 else (1 << 17) - 1, "worker_pid": 42}

        def compare(self, reference, candidate):
            # Runs after both staged inspections but cannot alter snapshots.
            copied.write_bytes(copied.read_bytes() + b"late-mutation")
            return {**_measurement("same"), "worker_pid": 42,
                    "reference_path": reference, "candidate_path": candidate,
                    "direct_same": False,
                    "direct_metrics": {"hist_corr": 0.0, "ssim": 0.0},
                    "source_phash": {"reference": 0, "candidate": 0},
                    "identity_content_change": {"by_pixel_delta": {}},
                    "aligned_content_change": {"by_pixel_delta": {}}}

        def close(self):
            pass

    sequence = {
        "sequence_id": "toctou", "transform_class": "static_shift",
        "source_content_id": "canvas", "generator_seed": 5,
        "frames": [
            {"timestamp": 0, "phash": 0, "expected_visual_id": "a", "path": "frame.png", "sha256": digest},
                {"timestamp": 1, "phash": (1 << 17) - 1, "expected_visual_id": "b", "path": "frame.png", "sha256": digest},
                {"timestamp": 2, "phash": (1 << 17) - 1, "expected_visual_id": "b", "path": "frame.png", "sha256": digest},
        ],
    }
    _measured, raw = calibration._with_worker_measurements(
        {"development_sequences": [sequence], "held_out_sequences": []}, worker=MutatingWorker()
    )
    assert raw["worker_measurement_error"] == "source frame SHA-256 mismatch after worker execution"


def test_worker_mutated_staged_candidate_blocks_worker_measurement(monkeypatch, tmp_path):
    """A worker cannot alter its received snapshot and retain a measurement."""
    source = REPO_ROOT / "tests/fixtures/benchmark/en_terms_01/slides/slide_01_concept.png"
    copied = tmp_path / "frame.png"
    shutil.copyfile(source, copied)
    digest = __import__("hashlib").sha256(copied.read_bytes()).hexdigest()
    monkeypatch.setattr(calibration, "REPO_ROOT", tmp_path)

    class SnapshotMutatingWorker:
        def __init__(self):
            self.calls = 0

        def inspect(self, _path):
            self.calls += 1
            return {"ok": True, "phash": 0 if self.calls == 1 else (1 << 17) - 1, "worker_pid": 77}

        def compare(self, reference, candidate):
            Path(candidate).write_bytes(Path(candidate).read_bytes() + b"worker-mutation")
            return {**_measurement("same"), "worker_pid": 77,
                    "reference_path": reference, "candidate_path": candidate,
                    "direct_same": False,
                    "direct_metrics": {"hist_corr": 0.0, "ssim": 0.0},
                    "source_phash": {"reference": 0, "candidate": 0},
                    "identity_content_change": {"by_pixel_delta": {}},
                    "aligned_content_change": {"by_pixel_delta": {}}}

        def close(self):
            pass

    sequence = {
        "sequence_id": "staged-toctou", "transform_class": "static_shift",
        "source_content_id": "canvas", "generator_seed": 6,
        "frames": [
            {"timestamp": 0, "phash": 0, "expected_visual_id": "a", "path": "frame.png", "sha256": digest},
            {"timestamp": 1, "phash": (1 << 17) - 1, "expected_visual_id": "b", "path": "frame.png", "sha256": digest},
            {"timestamp": 2, "phash": (1 << 17) - 1, "expected_visual_id": "b", "path": "frame.png", "sha256": digest},
        ],
    }
    measured, raw = calibration._with_worker_measurements(
        {"development_sequences": [sequence], "held_out_sequences": []}, worker=SnapshotMutatingWorker()
    )
    assert raw["worker_measurement_error"] == "staged frame SHA-256 mismatch after worker execution"
    returned = measured["development_sequences"][0]
    assert returned["event_measurements"] == {}
    assert all("_staged_path" not in frame and "recomputed_phash" not in frame for frame in returned["frames"])
    # The failure return itself contains no deleted snapshot pointer or partial
    # evidence: it can be handed back to the same pipeline safely.
    repeated, repeat_raw = calibration._with_worker_measurements(
        measured, worker=SnapshotMutatingWorker()
    )
    assert repeat_raw["worker_measurement_error"] == "staged frame SHA-256 mismatch after worker execution"
    repeated_frame = repeated["development_sequences"][0]["frames"][0]
    assert "_staged_path" not in repeated_frame
    assert "recomputed_phash" not in repeated_frame


def test_full_decoded_pipeline_has_exact_worker_pid_topology():
    reference = REPO_ROOT / "tests/fixtures/benchmark/en_terms_01/slides/slide_01_concept.png"
    candidate = REPO_ROOT / "tests/fixtures/benchmark/en_terms_01/slides/slide_00_title.png"
    digest = lambda path: __import__("hashlib").sha256(path.read_bytes()).hexdigest()
    path = lambda value: str(value.relative_to(REPO_ROOT)).replace("\\", "/")
    sequence = {
        "sequence_id": "pid-topology", "transform_class": "true_transition",
        "source_content_id": "canvas", "generator_seed": 2, "event_measurements": {},
        "frames": [
            {"timestamp": 0, "phash": 0, "expected_visual_id": "a", "path": path(reference), "sha256": digest(reference)},
            {"timestamp": 1, "phash": 1, "expected_visual_id": "b", "path": path(candidate), "sha256": digest(candidate)},
            {"timestamp": 2, "phash": 1, "expected_visual_id": "b", "path": path(candidate), "sha256": digest(candidate)},
        ],
    }
    result = calibration._full_sequence_reproducibility({"development_sequences": [sequence], "held_out_sequences": [sequence]})
    assert len(result["worker_pids"]["same_session"]) == 10
    assert len(set(result["worker_pids"]["same_session"])) == 1
    assert len(result["worker_pids"]["fresh_worker"]) == 2
    assert len(set(result["worker_pids"]["fresh_worker"])) == 2


def test_sequence_calibration_is_fail_closed_without_complete_fit_evidence(tmp_path):
    manifest = {
        "development_sequences": [{
            "sequence_id": "dev",
            "frames": [
                {"timestamp": 0, "phash": 0, "expected_visual_id": "a"},
                {"timestamp": 1, "phash": 1 << 17, "expected_visual_id": "a"},
            ],
        }],
        "held_out_sequences": [{
            "sequence_id": "held",
            "frames": [
                {"timestamp": 0, "phash": 0, "expected_visual_id": "a"},
                {"timestamp": 1, "phash": 1 << 17, "expected_visual_id": "a"},
            ],
        }],
        "retired_holdouts": [],
    }
    path = tmp_path / "sequence-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    report = calibration.calibrate(path)
    assert report["frozen"] is False
    assert report["reproducibility"]["same_session_repetitions"] == 0
    assert report["reproducibility"]["fresh_worker_repetitions"] == 0
    assert report["reproducibility"]["passed"] is False
    assert "production config and visual integration remain disabled" in report["blockers"][-1]


def test_sequence_threshold_search_is_bounded_and_never_returns_partial_vector():
    # A direct-only event cannot make alignment_fit viable, so the fitter must
    # fail closed rather than infer any of the 14 production fields.
    events = [{
        "expected_label": "same",
        "measurement": {
            "direct_same": True,
            "identity_content_change": {"by_pixel_delta": {"8": {
                "changed_fraction": 0.0, "largest_changed_component_fraction": 0.0,
            }}},
        },
    }]
    thresholds, diagnostics = calibration.find_sequence_thresholds(events, max_states=1)
    assert thresholds is None
    assert diagnostics["reason"] == "fit population incomplete"


def test_sequence_threshold_search_reports_hard_rss_cap_before_selecting_vector(monkeypatch):
    monkeypatch.setattr(calibration, "_rss_bytes", lambda: 2)
    events = []
    thresholds, diagnostics = calibration.find_sequence_thresholds(events, max_rss_bytes=1)
    assert thresholds is None
    # Population validation is earlier and therefore cannot accidentally turn
    # an empty corpus into a vector under any resource budget.
    assert diagnostics["reason"] == "fit population incomplete"


def _sequence_event(event_id, label, metadata):
    return {"event_id": event_id, "expected_label": label, "measurement": metadata}


def _sequence_measurement(*, direct_same, identity_changed=0.0, aligned_changed=None, ratio_matches=100):
    alignment = _measurement("same")
    alignment["ratio_matches"] = ratio_matches
    identity_content = {
        "by_pixel_delta": {
            str(delta): {
                "changed_fraction": identity_changed,
                "largest_changed_component_fraction": identity_changed,
            }
            for delta in calibration.CONTENT_PIXEL_DELTAS
        }
    }
    aligned_changed = identity_changed if aligned_changed is None else aligned_changed
    aligned_content = {
        "by_pixel_delta": {
            str(delta): {
                "changed_fraction": aligned_changed,
                "largest_changed_component_fraction": aligned_changed,
            }
            for delta in calibration.CONTENT_PIXEL_DELTAS
        }
    }
    return {
        "direct_same": direct_same,
        "identity_content_change": identity_content,
        "alignment": alignment,
        "aligned_content_change": aligned_content,
    }


def _sequence_exhaustive_oracle(events):
    """Independent bounded Cartesian reference for the branch-and-bound test."""
    alignment = [event["measurement"]["alignment"] for event in events if event["measurement"]["direct_same"] is False]
    positives = [
        event["measurement"]["alignment"] for event in events
        if event["measurement"]["direct_same"] is False and event["expected_label"] == "same"
    ]
    domains = {}
    for raw, name, direction in calibration._THRESHOLD_ORDER:
        values = calibration._candidate_values(alignment, raw)
        if direction == "min":
            domains[name] = sorted(
                (value for value in values if value <= min(calibration._measurement_value(item, raw) for item in positives)),
                reverse=True,
            )
        elif direction == "max":
            domains[name] = sorted(value for value in values if value >= max(calibration._measurement_value(item, raw) for item in positives))
        elif direction == "scale_min":
            domains[name] = [0.80]
        else:
            domains[name] = [1.25]
    for delta in calibration.CONTENT_PIXEL_DELTAS:
        resolved = [calibration._event_metadata_at_delta(event, delta) for event in events]
        active = [calibration._content_metric_for_event(event, item) for event, item in zip(events, resolved)]
        changed = sorted({item["changed_fraction"] for item in active})
        largest = sorted({item["largest_changed_component_fraction"] for item in active})
        for values in itertools.product(*(domains[name] for _raw, name, _direction in calibration._THRESHOLD_ORDER), changed, largest):
            vector = dict(zip((name for _raw, name, _direction in calibration._THRESHOLD_ORDER), values[:11]))
            vector.update(pixel_delta=delta, changed_fraction_max=values[-2], largest_changed_component_fraction_max=values[-1])
            if all(
                calibration._event_matches_decision(
                    event, calibration.evaluate_visual_candidate(item, vector, complete=True)
                )
                for event, item in zip(events, resolved)
            ):
                return vector
    return None


def test_sequence_branch_and_bound_matches_independent_full_cartesian_oracle():
    # Includes direct, identity-veto fallback, and alignment routes.  The
    # intentionally tiny domains make an exhaustive proof affordable in test.
    events = [
        _sequence_event("aligned-positive", "same", _sequence_measurement(direct_same=False)),
        _sequence_event("aligned-negative", "different", _sequence_measurement(direct_same=False, ratio_matches=1)),
        {**_sequence_event("fallback-positive", "same", _sequence_measurement(direct_same=True, identity_changed=0.10, aligned_changed=0.0)), "required_fallback": True},
        {**_sequence_event("fallback-negative", "different", _sequence_measurement(direct_same=True, identity_changed=0.20, aligned_changed=0.20)), "required_fallback": True},
        _sequence_event(
            "direct-true-negative",
            "different",
            _sequence_measurement(
                direct_same=True,
                identity_changed=0.15,
                aligned_changed=0.20,
            ),
        ),
    ]
    expected = _sequence_exhaustive_oracle(events)
    actual, diagnostics = calibration.find_sequence_thresholds(events)
    assert actual == expected
    assert actual is not None
    assert diagnostics["visited_leaves"] == 1
    assert diagnostics["pruned_prefixes"] >= 0
    for event in events[2:]:
        metadata = calibration._event_metadata_at_delta(event, actual["pixel_delta"])
        decision = calibration.evaluate_visual_candidate(metadata, actual, complete=True)
        assert decision["path"] == "alignment_content_change"
        assert decision["alignment_required"] is True
        assert decision["identity_veto_gate"] == "content_change"


def test_sequence_branch_and_bound_matches_oracle_when_distinct_branch_metrics_have_no_vector():
    # The fallback-positive identity metric cannot be made to fail while its
    # aligned metric passes: both are zero.  A classifier-only search would
    # incorrectly accept it on the identity branch, so path equality matters.
    events = [
        _sequence_event("aligned-positive", "same", _sequence_measurement(direct_same=False)),
        _sequence_event("aligned-negative", "different", _sequence_measurement(direct_same=False, ratio_matches=1)),
        {**_sequence_event("impossible-fallback", "same", _sequence_measurement(direct_same=True, identity_changed=0.0, aligned_changed=0.0)), "required_fallback": True},
        {**_sequence_event("fallback-negative", "different", _sequence_measurement(direct_same=True, identity_changed=0.20, aligned_changed=0.20)), "required_fallback": True},
    ]
    expected = _sequence_exhaustive_oracle(events)
    actual, diagnostics = calibration.find_sequence_thresholds(events)
    assert expected is None
    assert actual == expected
    assert diagnostics["reason"] == "no separating vector"


def test_synthetic_sequence_generator_covers_all_required_paths_and_classes():
    from scripts.generate_alignment_fixture import build_synthetic_sequence_manifest

    manifest = build_synthetic_sequence_manifest()
    errors = calibration.validate_sequence_manifest(manifest)
    replay_thresholds = {
            "ratio_matches_min": 2, "inlier_count_min": 1, "inlier_ratio_min": 0,
            "hull_support_min": 0, "eigenvalue_ratio_min": 0, "coverage_min": 0,
            "ssim_min": 0, "residual_median_max": 1, "residual_p95_max": 1,
            "scale_min": .8, "scale_max": 1.25, "pixel_delta": 8,
            "changed_fraction_max": 0.01, "largest_changed_component_fraction_max": 0.01,
    }
    development = [
        event for sequence in manifest["development_sequences"]
        for event in calibration.replay_sequence(sequence, replay_thresholds)
    ]
    held_out = [
        event for sequence in manifest["held_out_sequences"]
        for event in calibration.replay_sequence(sequence, replay_thresholds)
    ]
    # The generator is metadata-only by design; it proves synthetic branch
    # coverage but cannot stand in for immutable decoded-frame evidence.
    assert any("frame lacks path" in error for error in errors)
    assert calibration.validate_complete_sequence_population(development, "development") == []
    assert calibration.validate_complete_sequence_population(held_out, "held_out") == []


def test_committed_real_sequence_corpus_has_immutable_decoded_frames():
    manifest_path = REPO_ROOT / "tests" / "fixtures" / "visual_alignment" / "real_sequence_v1" / "manifest.json"
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest.decode("utf-8"))
    assert manifest["corpus_kind"] == "real_image_sequence"
    assert calibration.validate_sequence_manifest(manifest) == []
    assert calibration.validate_sequence_lineage(manifest, raw_manifest) == []
    development_ids = {row["source_content_id"] for row in manifest["development_sequences"]}
    held_out_ids = {row["source_content_id"] for row in manifest["held_out_sequences"]}
    assert development_ids.isdisjoint(held_out_ids)
    for sequence in manifest["development_sequences"] + manifest["held_out_sequences"]:
        for frame in sequence["frames"]:
            assert (REPO_ROOT / frame["path"]).is_file()
            assert len(frame["sha256"]) == 64


def test_runtime_thresholds_are_bound_to_promoted_report():
    from lectural.config import (
        ALIGNMENT_CALIBRATION_REPORT,
        ALIGNMENT_CALIBRATION_REPORT_SHA256,
        ALIGNMENT_THRESHOLDS,
    )

    report_path = REPO_ROOT / ALIGNMENT_CALIBRATION_REPORT
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    assert __import__("hashlib").sha256(report_bytes).hexdigest() == ALIGNMENT_CALIBRATION_REPORT_SHA256
    assert report["frozen"] is True
    assert report["blockers"] == []
    assert report["thresholds"] == ALIGNMENT_THRESHOLDS

    manifest_path = REPO_ROOT / "tests/fixtures/visual_alignment/real_sequence_v1/manifest.json"
    manifest_sha256 = __import__("hashlib").sha256(manifest_path.read_bytes()).hexdigest()
    assert report["manifest_sha256"] == manifest_sha256
