#!/usr/bin/env python3
"""Calibrate Issue #22 alignment thresholds from an immutable manifest.

This command intentionally produces ``frozen: false`` when the manifest does
not contain the complete development/held-out corpus required by the plan.
It never changes production configuration and never recalibrates at runtime.
"""

from __future__ import annotations

import argparse
import itertools
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import tempfile
import time
import os
from typing import Any

# Keep direct ``python scripts/calibrate_alignment.py`` invocation equivalent
# to running it from the repository root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lectural.alignment import (
    CANONICAL_GATE_ORDER,
    OPENCV_CONSTRAINT,
    PROTOCOL_VERSION,
    AlignmentWorker,
    evaluate_alignment_metadata,
    evaluate_visual_candidate,
    opencv_provenance,
    run_alignment_batch,
)
from lectural.visual import advance_dedupe_state, initial_dedupe_state


DEFAULT_MANIFEST = REPO_ROOT / "tests" / "fixtures" / "visual_alignment" / "manifest.json"
THRESHOLD_FIELDS = (
    "ratio_matches",
    "inlier_count",
    "inlier_ratio",
    "hull_support",
    "eigenvalue_ratio",
    "coverage",
    "ssim",
    "residual_median",
    "residual_p95",
    "scale_min",
    "scale_max",
)
MIN_THRESHOLD_FIELDS = (
    "ratio_matches_min",
    "inlier_count_min",
    "inlier_ratio_min",
    "hull_support_min",
    "eigenvalue_ratio_min",
    "coverage_min",
    "ssim_min",
)
MAX_THRESHOLD_FIELDS = ("residual_median_max", "residual_p95_max")
_THRESHOLD_ORDER = (
    ("ratio_matches", "ratio_matches_min", "min"),
    ("inlier_count", "inlier_count_min", "min"),
    ("inlier_ratio", "inlier_ratio_min", "min"),
    ("hull_support", "hull_support_min", "min"),
    ("eigenvalue_ratio", "eigenvalue_ratio_min", "min"),
    ("coverage", "coverage_min", "min"),
    ("ssim", "ssim_min", "min"),
    ("residual_median", "residual_median_max", "max"),
    ("residual_p95", "residual_p95_max", "max"),
    ("scale", "scale_min", "scale_min"),
    ("scale", "scale_max", "scale_max"),
)
# The frozen vector extends the historical alignment-only fields with the
# identity/aligned content-veto vector.  Pixel delta is an integer domain;
# fractions retain their raw IEEE-754 values in the canonical artifact.
CONTENT_PIXEL_DELTAS = (8, 12, 16, 24, 32, 48, 64)
THRESHOLD_ORDER_14 = _THRESHOLD_ORDER + (
    ("pixel_delta", "pixel_delta", "int"),
    ("changed_fraction", "changed_fraction_max", "max"),
    ("largest_changed_component_fraction", "largest_changed_component_fraction_max", "max"),
)
REQUIRED_TRANSFORM_CLASSES = {
    "static_shift",
    "static_duplicate",
    "pan_zoom",
    "pan_zoom_reverse",
    "true_transition",
    "same_palette_different_layout",
    "incremental_build",
    "pan_zoom_incremental",
    "pan_zoom_shared_template",
    "too_few_descriptors",
    "ransac_failure",
    "outlier_heavy",
    "high_residual",
    "out_of_scale",
    "collinear_inliers",
    "one_way_coverage",
    "low_masked_ssim",
}


def _opencv_version_supported(version: Any) -> bool:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?", str(version or ""))
    if match is None:
        return False
    major, minor, patch, build = (int(value or 0) for value in match.groups())
    if major != 4:
        return False
    if minor == 5:
        return True
    return minor == 6 and patch == 0 and build <= 66


def _opencv_distribution_info() -> dict[str, Any]:
    """Return metadata bound to the cv2 module actually imported by calibration."""
    try:
        import cv2
    except Exception as exc:
        return {
            "expected_provider": "opencv-python",
            "provider_candidates": [],
            "provider_exact": False,
            "provider_present": False,
            "distribution_version": None,
            "imported_cv2_version": None,
            "imported_cv2_path": None,
            "version_match": False,
            "distribution_supported": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return opencv_provenance(cv2)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _measurement_value(measurement: dict[str, Any], field: str) -> float | None:
    if field == "coverage":
        values = (measurement.get("forward_coverage"), measurement.get("reverse_coverage"))
        if not all(_finite(value) for value in values):
            return None
        return min(float(value) for value in values)
    if field == "ssim":
        values = (measurement.get("forward_ssim"), measurement.get("reverse_ssim"))
        if not all(_finite(value) for value in values):
            return None
        return min(float(value) for value in values)
    value = measurement.get(field)
    return float(value) if _finite(value) else None


def _passes(measurement: dict[str, Any], thresholds: dict[str, float]) -> bool:
    decision = evaluate_alignment_metadata(measurement, thresholds, complete=True)
    return decision["result"] == "same"


def _candidate_values(measurements: list[dict[str, Any]], field: str) -> list[float]:
    values = {
        value
        for measurement in measurements
        if (value := _measurement_value(measurement, field)) is not None
    }
    return sorted(values)


def _positive_metric_failures(
    rows: list[dict[str, Any]], measurements: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Report unavailable/non-finite prerequisites before threshold search."""
    failures = []
    required_fields = tuple(dict.fromkeys(raw_field for raw_field, _name, _direction in _THRESHOLD_ORDER))
    for row, measurement in zip(rows, measurements):
        if row.get("expected_label") != "same":
            continue
        missing = []
        ratio_count = measurement.get("ratio_match_count")
        if not _finite(ratio_count) or float(ratio_count) < 2:
            missing.append("ratio_match_count")
        affine = measurement.get("affine")
        if not isinstance(affine, list) or len(affine) != 2 or any(
            not isinstance(line, list) or len(line) != 3 or any(not _finite(value) for value in line)
            for line in affine
        ):
            missing.append("affine")
        determinant = measurement.get("determinant")
        if not _finite(determinant) or float(determinant) <= 0:
            missing.append("determinant")
        for field in required_fields:
            value = _measurement_value(measurement, field)
            if value is None or (field == "scale" and value <= 0):
                missing.append(field)
        if missing:
            failures.append({"id": row.get("id"), "missing_metrics": sorted(set(missing))})
    return failures


def _find_thresholds(rows: list[dict[str, Any]], measurements: list[dict[str, Any]]) -> dict[str, float] | None:
    development = list(zip(rows, measurements))
    positives = [measurement for row, measurement in development if row["expected_label"] == "same"]
    negatives = [measurement for row, measurement in development if row["expected_label"] == "different"]
    if not positives or not negatives:
        return None
    if _positive_metric_failures(rows, measurements):
        return None

    # The threshold vector is monotone: larger minimums and smaller maximums
    # can only turn a passing pair into a failing pair. For each prefix of the
    # fixed lexicographic field order, the component-wise strictest
    # positive-safe completion therefore dominates every other completion. If
    # it cannot reject all negatives, no weaker completion can. This preserves
    # the exact selection contract without enumerating a Cartesian product.
    domains: dict[str, list[float]] = {}
    for raw_field, threshold_name, direction in _THRESHOLD_ORDER:
        values = _candidate_values(measurements, raw_field)
        if direction == "min":
            bound = min((_measurement_value(measurement, raw_field) for measurement in positives), default=None)
            domain = [value for value in values if bound is not None and value <= bound]
        elif direction == "max":
            bound = max((_measurement_value(measurement, raw_field) for measurement in positives), default=None)
            domain = [value for value in values if bound is not None and value >= bound]
        elif direction == "scale_min":
            bound = min((_measurement_value(measurement, "scale") for measurement in positives), default=None)
            domain = [value for value in values if bound is not None and value <= bound]
        else:
            bound = max((_measurement_value(measurement, "scale") for measurement in positives), default=None)
            domain = [value for value in values if bound is not None and value >= bound]
        if not domain:
            return None
        domains[threshold_name] = sorted(set(domain))

    def strictest_completion(selected: dict[str, float]) -> dict[str, float] | None:
        completed = dict(selected)
        for _raw_field, threshold_name, direction in _THRESHOLD_ORDER:
            if threshold_name in completed:
                continue
            domain = domains[threshold_name]
            completed[threshold_name] = max(domain) if direction in {"min", "scale_min"} else min(domain)
        if completed["scale_min"] > completed["scale_max"]:
            return None
        return completed

    def valid(completed: dict[str, float] | None) -> bool:
        return bool(
            completed
            and all(_passes(measurement, completed) for measurement in positives)
            and all(not _passes(measurement, completed) for measurement in negatives)
        )

    selected: dict[str, float] = {}
    for _raw_field, threshold_name, direction in _THRESHOLD_ORDER:
        domain = domains[threshold_name]
        ordered = sorted(domain, reverse=direction in {"min", "scale_min"})
        chosen = None
        for value in ordered:
            candidate = strictest_completion({**selected, threshold_name: value})
            if valid(candidate):
                chosen = value
                break
        if chosen is None:
            return None
        selected[threshold_name] = chosen
    return selected


def _confusion(rows: list[dict[str, Any]], measurements: list[dict[str, Any]], thresholds: dict[str, float] | None) -> dict[str, int]:
    result = {"true_positive": 0, "false_positive": 0, "true_negative": 0, "false_negative": 0}
    for row, measurement in zip(rows, measurements):
        predicted_same = bool(thresholds and _passes(measurement, thresholds))
        expected_same = row["expected_label"] == "same"
        if expected_same and predicted_same:
            result["true_positive"] += 1
        elif expected_same:
            result["false_negative"] += 1
        elif predicted_same:
            result["false_positive"] += 1
        else:
            result["true_negative"] += 1
    return result


def _first_failed_inequality(measurement: dict[str, Any], thresholds: dict[str, float] | None) -> str | None:
    """Return the first failed calibrated predicate in production gate order."""
    if not thresholds:
        return "calibration_not_frozen"
    decision = evaluate_alignment_metadata(measurement, thresholds, complete=True)
    return decision["first_failed_gate"]


_REQUIRED_INTEGER_FIELDS = (
    "ratio_match_count",
    "ratio_matches",
    "inlier_count",
)


def _serialized_measurement_hash(measurements: list[dict[str, Any]]) -> str:
    serialized = json.dumps(
        measurements,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _required_integer_signature(measurements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signature = []
    for index, measurement in enumerate(measurements):
        keypoints = measurement.get("keypoint_counts")
        signature.append(
            {
                "index": index,
                **{
                    field: measurement.get(field) if isinstance(measurement.get(field), int) else None
                    for field in _REQUIRED_INTEGER_FIELDS
                },
                "keypoints_reference": (
                    keypoints.get("reference")
                    if isinstance(keypoints, dict) and isinstance(keypoints.get("reference"), int)
                    else None
                ),
                "keypoints_candidate": (
                    keypoints.get("candidate")
                    if isinstance(keypoints, dict) and isinstance(keypoints.get("candidate"), int)
                    else None
                ),
            }
        )
    return signature


def _decision_signature(
    measurements: list[dict[str, Any]], thresholds: dict[str, float] | None
) -> list[dict[str, Any]]:
    return [
        {
            "result": decision["result"],
            "first_failed_gate": decision["first_failed_gate"],
        }
        for decision in (evaluate_alignment_metadata(measurement, thresholds, complete=True) for measurement in measurements)
    ]


def _run_reproducibility(tasks: list[tuple[str, str]]) -> dict[str, Any]:
    """Measure the corpus repeatedly across one session and fresh workers."""
    same_session_runs: list[list[dict[str, Any]]] = []
    worker = None
    try:
        worker = AlignmentWorker()
        for _ in range(10):
            same_session_runs.append([worker.compare(*task) for task in tasks])
    except (OSError, RuntimeError):
        same_session_runs = []
    finally:
        if worker is not None:
            worker.close()

    fresh_worker_runs = []
    for _ in range(2):
        fresh_worker_runs.append(run_alignment_batch(tasks))
    baseline = fresh_worker_runs[0] if fresh_worker_runs else (same_session_runs[0] if same_session_runs else [])
    return {
        "baseline_measurements": baseline,
        "same_session_runs": same_session_runs,
        "fresh_worker_runs": fresh_worker_runs,
    }


def _finalize_reproducibility(
    reproducibility: dict[str, Any], thresholds: dict[str, float] | None
) -> dict[str, Any]:
    groups = {
        "same_session": reproducibility.get("same_session_runs", []),
        "fresh_worker": reproducibility.get("fresh_worker_runs", []),
    }
    runs = [run for group in groups.values() for run in group]
    hashes = {name: [_serialized_measurement_hash(run) for run in group] for name, group in groups.items()}
    integer_signatures = {
        name: [_required_integer_signature(run) for run in group] for name, group in groups.items()
    }
    decision_signatures = {
        name: [_decision_signature(run, thresholds) for run in group] for name, group in groups.items()
    }
    baseline_hash = _serialized_measurement_hash(runs[0]) if runs else None
    baseline_integer = _required_integer_signature(runs[0]) if runs else None
    baseline_decision = _decision_signature(runs[0], thresholds) if runs else None
    identical = bool(runs) and all(
        _serialized_measurement_hash(run) == baseline_hash
        and _required_integer_signature(run) == baseline_integer
        and _decision_signature(run, thresholds) == baseline_decision
        for run in runs
    )
    return {
        "same_session_repetitions": len(groups["same_session"]),
        "fresh_worker_repetitions": len(groups["fresh_worker"]),
        "measurement_hashes": hashes,
        "required_integer_counts": integer_signatures,
        "decision_signatures": decision_signatures,
        "identical": identical,
        "passed": (
            identical
            and len(groups["same_session"]) == 10
            and len(groups["fresh_worker"]) == 2
        ),
    }


def _sequence_event_id(sequence_id: str, confirmation_index: int, candidate_start_index: int) -> str:
    return f"{sequence_id}:{confirmation_index}:{candidate_start_index}"


def replay_sequence(sequence: dict[str, Any], thresholds: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Replay one authored sequence through the production persistence rules.

    A manifest stores measurements by canonical event id.  This is a cache,
    not a second population: each confirmed candidate contributes once here.
    Missing a measurement is a fail-closed terminal ``not_same`` event.
    """
    frames = list(sequence.get("frames", []))
    if not frames:
        return []
    sequence_id = str(sequence.get("sequence_id", ""))
    hashes = _sequence_replay_hashes(frames)
    state = initial_dedupe_state(hashes[0])
    measurements = dict(sequence.get("event_measurements", {}))
    events: list[dict[str, Any]] = []
    for index, frame in enumerate(frames[1:], start=1):
        def decide(kept_index: int, candidate_index: int) -> str:
            event_id = _sequence_event_id(sequence_id, index, candidate_index)
            measurement = measurements.get(event_id)
            if not isinstance(measurement, dict):
                decision = {"result": "not_same", "first_failed_gate": "measurement"}
            else:
                evaluation_measurement = measurement
                if thresholds is not None and isinstance(thresholds.get("pixel_delta"), int):
                    selected = _event_metadata_at_delta(
                        {"measurement": measurement}, thresholds["pixel_delta"]
                    )
                    if selected is not None:
                        evaluation_measurement = selected
                decision = evaluate_visual_candidate(
                    evaluation_measurement, thresholds, complete=True
                )
            expected = (
                "same"
                if frames[kept_index].get("expected_visual_id") == frames[candidate_index].get("expected_visual_id")
                else "different"
            )
            events.append({
                "event_id": event_id,
                "sequence_id": sequence_id,
                "confirmation_frame_index": index,
                "candidate_start_index": candidate_index,
                "kept_index": kept_index,
                "expected_label": expected,
                "predicted_label": "same" if decision["result"] == "same" else "different",
                "result": decision["result"],
                "first_failed_gate": decision["first_failed_gate"],
                "path": decision.get("path"),
                "alignment_required": decision.get("alignment_required"),
                "transform_class": sequence.get("transform_class"),
                "source_content_id": sequence.get("source_content_id"),
                "required_fallback": bool(sequence.get("required_fallback")),
                "fallback_direction": sequence.get("fallback_direction"),
                "measurement": measurement,
            })
            return "same" if decision["result"] == "same" else "not_same"

        state, _trace = advance_dedupe_state(state, index, hashes[index], evaluate=decide)
    return events


def _sequence_replay_hashes(frames: list[dict[str, Any]]) -> list[Any]:
    """Choose exactly one pHash trace; decoded evidence always wins.

    A partially decoded sequence is unsafe: mixing recomputed and authored
    hashes could generate task IDs unlike the worker's measured candidates.
    Raise instead of silently falling back so calibration remains fail-closed.
    """
    decoded = any("recomputed_phash" in frame for frame in frames)
    field = "recomputed_phash" if decoded else "phash"
    missing = [index for index, frame in enumerate(frames) if field not in frame]
    if missing:
        mode = "decoded" if decoded else "authored"
        raise ValueError(f"{mode} pHash trace is incomplete at frame indexes {missing}")
    return [frame[field] for frame in frames]


def _confusion_events(events: list[dict[str, Any]]) -> dict[str, int]:
    result = {"true_positive": 0, "false_positive": 0, "true_negative": 0, "false_negative": 0}
    for event in events:
        expected = event["expected_label"] == "same"
        predicted = event["predicted_label"] == "same"
        if expected and predicted:
            result["true_positive"] += 1
        elif expected:
            result["false_negative"] += 1
        elif predicted:
            result["false_positive"] += 1
        else:
            result["true_negative"] += 1
    return result


def sequence_fit_populations(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Partition confirmed production events without double-counting cache rows."""
    alignment_fit = []
    content_fit = []
    for event in events:
        measurement = event.get("measurement")
        if not isinstance(measurement, dict):
            continue
        content_fit.append(event)
        if measurement.get("direct_same") is False:
            alignment_fit.append(event)
    return {"alignment_fit": alignment_fit, "content_fit": content_fit}


def _event_metadata_at_delta(event: dict[str, Any], pixel_delta: int) -> dict[str, Any] | None:
    measurement = event.get("measurement")
    if not isinstance(measurement, dict):
        return None
    metadata = json.loads(json.dumps(measurement))
    for key in ("identity_content_change", "aligned_content_change"):
        value = metadata.get(key)
        if isinstance(value, dict) and "by_pixel_delta" in value:
            selected = value["by_pixel_delta"].get(str(pixel_delta))
            if not isinstance(selected, dict):
                return None
            metadata[key] = selected
    return metadata


def _expected_production_path(event: dict[str, Any]) -> str:
    """Return the authored branch contract used for fitting, never a guess."""
    measurement = event.get("measurement") or {}
    if event.get("required_fallback") or (
        measurement.get("direct_same") is True
        and event.get("expected_label") == "different"
    ):
        return "alignment_content_change"
    return "identity_content_change" if measurement.get("direct_same") is True else "alignment_content_change"


def _event_matches_decision(event: dict[str, Any], decision: dict[str, Any]) -> bool:
    """Classification plus mandatory production-path trace contract."""
    if (decision.get("result") == "same") != (event.get("expected_label") == "same"):
        return False
    expected_path = _expected_production_path(event)
    if decision.get("path") != expected_path:
        return False
    if event.get("required_fallback"):
        return (
            event.get("measurement", {}).get("direct_same") is True
            and decision.get("alignment_required") is True
            and decision.get("identity_veto_gate") == "content_change"
        )
    return True


def _content_metric_for_event(event: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Select only the content metric invoked by the authored production path."""
    key = "identity_content_change" if _expected_production_path(event) == "identity_content_change" else "aligned_content_change"
    value = metadata.get(key)
    return value if isinstance(value, dict) else None


def _rss_bytes() -> int | None:
    """Current process RSS on the supported Windows host (best effort)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t)]
        counters = Counters(); counters.cb = ctypes.sizeof(Counters)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        return int(counters.WorkingSetSize) if ok else None
    except Exception:
        return None


def find_sequence_thresholds(
    events: list[dict[str, Any]], *, max_states: int = 1_000_000, max_seconds: float = 120.0,
    max_rss_bytes: int = 512 * 1024 * 1024,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Find the first separating 14-field vector with exact monotone pruning.

    The DFS order is the serialized tie order.  At every prefix, the strictest
    positive-safe completion is a proof obligation: if it still accepts a
    negative, every weaker completion accepts it too.  This is a branch and
    bound proof, not a sampled grid.  Limits deliberately return no vector.
    """
    populations = sequence_fit_populations(events)
    if not populations["alignment_fit"] or not populations["content_fit"]:
        return None, {"search_cap_exceeded": False, "reason": "fit population incomplete", "states": 0}
    start = time.monotonic()
    states = 0
    alignment_events = populations["alignment_fit"]
    alignment_measurements = [event["measurement"].get("alignment", {}) for event in alignment_events]
    alignment_positives = [
        measurement for event, measurement in zip(alignment_events, alignment_measurements)
        if event["expected_label"] == "same"
    ]
    if not alignment_positives:
        return None, {"search_cap_exceeded": False, "reason": "alignment_fit lacks same label", "states": 0}
    domains: dict[str, list[float]] = {}
    for raw, name, direction in _THRESHOLD_ORDER:
        values = _candidate_values(alignment_measurements, raw)
        if not values:
            return None, {"search_cap_exceeded": False, "reason": f"missing {raw}", "states": states}
        if direction == "min":
            bound = min(_measurement_value(measurement, raw) for measurement in alignment_positives)
            domains[name] = sorted(value for value in values if value <= bound)[::-1]
        elif direction == "max":
            bound = max(_measurement_value(measurement, raw) for measurement in alignment_positives)
            domains[name] = sorted(value for value in values if value >= bound)
        elif direction == "scale_min":
            domains[name] = [0.80]
        else:
            domains[name] = [1.25]
        if not domains[name]:
            return None, {"search_cap_exceeded": False, "reason": f"no positive-safe {raw}", "states": states}

    def cap_reason() -> str | None:
        rss = _rss_bytes()
        if states >= max_states:
            return "state_cap"
        if time.monotonic() - start >= max_seconds:
            return "time_cap"
        if rss is not None and rss > max_rss_bytes:
            return "rss_cap"
        return None

    def evaluate_events(resolved_events: list[tuple[dict[str, Any], dict[str, Any]]], vector: dict[str, Any]):
        return [
            evaluate_visual_candidate(metadata, vector, complete=True)
            for _event, metadata in resolved_events
        ]

    diagnostics: dict[str, Any] = {
        "search_cap_exceeded": False,
        "states": 0,
        "visited_leaves": 0,
        "pruned_prefixes": 0,
        "memo_hits": 0,
        "domain_sizes": {},
        "reason": None,
    }
    for pixel_delta in CONTENT_PIXEL_DELTAS:
        resolved = [_event_metadata_at_delta(event, pixel_delta) for event in populations["content_fit"]]
        if any(value is None for value in resolved):
            continue
        resolved_events = list(zip(events, (_event_metadata_at_delta(event, pixel_delta) for event in events)))
        if any(metadata is None for _event, metadata in resolved_events):
            continue
        resolved_events = [(event, metadata) for event, metadata in resolved_events if metadata is not None]
        values = []
        for value in resolved:
            for key in ("identity_content_change", "aligned_content_change"):
                content = value.get(key)
                if isinstance(content, dict):
                    values.append(content)
        changed = sorted({_measurement_value(value, "changed_fraction") for value in values if _measurement_value(value, "changed_fraction") is not None})
        largest = sorted({_measurement_value(value, "largest_changed_component_fraction") for value in values if _measurement_value(value, "largest_changed_component_fraction") is not None})
        if not changed or not largest:
            continue
        content_positives = [
            content for event, metadata in zip(populations["content_fit"], resolved)
            if event["expected_label"] == "same"
            for content in [_content_metric_for_event(event, metadata)]
            if content is not None
        ]
        if not content_positives or any(
            _measurement_value(value, "changed_fraction") is None
            or _measurement_value(value, "largest_changed_component_fraction") is None
            for value in content_positives
        ):
            continue
        changed_bound = max(_measurement_value(value, "changed_fraction") for value in content_positives)
        largest_bound = max(_measurement_value(value, "largest_changed_component_fraction") for value in content_positives)
        full_domains = dict(domains)
        full_domains["pixel_delta"] = [pixel_delta]
        full_domains["changed_fraction_max"] = [value for value in changed if value >= changed_bound]
        full_domains["largest_changed_component_fraction_max"] = [value for value in largest if value >= largest_bound]
        if not full_domains["changed_fraction_max"] or not full_domains["largest_changed_component_fraction_max"]:
            continue
        order = tuple(name for _raw, name, _direction in _THRESHOLD_ORDER)
        directions = {name: direction for _raw, name, direction in _THRESHOLD_ORDER}
        diagnostics["domain_sizes"][str(pixel_delta)] = {
            name: len(full_domains[name])
            for name in tuple(name for _raw, name, _direction in THRESHOLD_ORDER_14)
        }

        def content_passes(metadata: Any, changed_max: float, largest_max: float) -> bool:
            return (
                isinstance(metadata, dict)
                and _finite(metadata.get("changed_fraction"))
                and _finite(metadata.get("largest_changed_component_fraction"))
                and float(metadata["changed_fraction"]) <= changed_max
                and float(metadata["largest_changed_component_fraction"]) <= largest_max
            )

        # Content thresholds are the final two serialized fields. Filter their
        # Cartesian product by path invariants before traversing alignment
        # prefixes; this preserves exact lexicographic order while avoiding
        # hundreds of thousands of leaves that can never route correctly.
        content_pairs = []
        for changed_max in full_domains["changed_fraction_max"]:
            for largest_max in full_domains["largest_changed_component_fraction_max"]:
                viable = True
                for event, metadata in resolved_events:
                    expected_path = _expected_production_path(event)
                    if metadata.get("direct_same") is True:
                        identity_passes = content_passes(
                            metadata.get("identity_content_change"), changed_max, largest_max
                        )
                        if identity_passes != (expected_path == "identity_content_change"):
                            viable = False
                            break
                    if event["expected_label"] == "same" and expected_path == "alignment_content_change":
                        if not content_passes(
                            metadata.get("aligned_content_change"), changed_max, largest_max
                        ):
                            viable = False
                            break
                if viable:
                    content_pairs.append((changed_max, largest_max))
        diagnostics["domain_sizes"][str(pixel_delta)]["viable_content_pairs"] = len(content_pairs)
        if not content_pairs:
            continue


        def complete(prefix: dict[str, Any], *, strictest: bool) -> dict[str, Any]:
            result = dict(prefix)
            for name in order:
                if name in result:
                    continue
                result[name] = full_domains[name][0 if strictest else -1]
            changed_max, largest_max = content_pairs[0 if strictest else -1]
            result.update(
                pixel_delta=pixel_delta,
                changed_fraction_max=changed_max,
                largest_changed_component_fraction_max=largest_max,
            )
            return result

        memo: set[tuple[int, tuple[tuple[str, Any], ...], tuple[str, ...]]] = set()
        aborted: str | None = None

        def visit(position: int, prefix: dict[str, Any]) -> dict[str, Any] | None:
            nonlocal states, aborted
            if aborted:
                return None
            states += 1
            reason = cap_reason()
            if reason:
                aborted = reason
                return None
            weakest = complete(prefix, strictest=False)
            weakest_decisions = evaluate_events(resolved_events, weakest)
            failed_positives = [
                {
                    "event_id": event["event_id"],
                    "result": decision.get("result"),
                    "first_failed_gate": decision.get("first_failed_gate"),
                    "path": decision.get("path"),
                }
                for (event, _metadata), decision in zip(resolved_events, weakest_decisions)
                if event["expected_label"] == "same"
                and not _event_matches_decision(event, decision)
            ]
            if failed_positives:
                if not prefix:
                    diagnostics["weakest_positive_failures"] = failed_positives
                diagnostics["pruned_prefixes"] += 1
                return None
            strictest = complete(prefix, strictest=True)
            unavoidable = []
            for event, metadata in resolved_events:
                if event["expected_label"] != "different":
                    continue
                alignment = evaluate_alignment_metadata(
                    dict(metadata.get("alignment") or {}), strictest, complete=True
                )
                if alignment["result"] != "same":
                    continue
                aligned_content = metadata.get("aligned_content_change")
                if all(
                    content_passes(aligned_content, changed_max, largest_max)
                    for changed_max, largest_max in content_pairs
                ):
                    unavoidable.append(event["event_id"])
            survivors = tuple(unavoidable)
            key = (pixel_delta, tuple((name, prefix[name]) for name in order if name in prefix), survivors)
            if key in memo:
                diagnostics["memo_hits"] += 1
                return None
            memo.add(key)
            if survivors:
                diagnostics["pruned_prefixes"] += 1
                return None
            if position == len(order):
                for changed_max, largest_max in content_pairs:
                    states += 1
                    reason = cap_reason()
                    if reason:
                        aborted = reason
                        return None
                    vector = {
                        **prefix,
                        "pixel_delta": pixel_delta,
                        "changed_fraction_max": changed_max,
                        "largest_changed_component_fraction_max": largest_max,
                    }
                    diagnostics["visited_leaves"] += 1
                    decisions = evaluate_events(resolved_events, vector)
                    if all(
                        _event_matches_decision(event, decision)
                        for (event, _metadata), decision in zip(resolved_events, decisions)
                    ):
                        return vector
                return None
            name = order[position]
            for value in full_domains[name]:
                found = visit(position + 1, {**prefix, name: value})
                if found is not None:
                    return found
                if aborted:
                    return None
            return None

        found = visit(0, {})
        diagnostics["states"] = states
        if aborted:
            diagnostics.update(search_cap_exceeded=True, reason=aborted, rss_bytes=_rss_bytes())
            return None, diagnostics
        if found is not None:
            return found, diagnostics
    diagnostics["states"] = states
    diagnostics["reason"] = "no separating vector"
    return None, diagnostics


def validate_sequence_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return contract failures; never infer sequence truth from metrics."""
    errors: list[str] = []
    for split in ("development_sequences", "held_out_sequences"):
        sequences = manifest.get(split)
        if not isinstance(sequences, list) or not sequences:
            errors.append(f"{split} is missing or empty")
            continue
        for sequence in sequences:
            if not isinstance(sequence.get("sequence_id"), str) or not sequence["sequence_id"]:
                errors.append(f"{split} sequence_id is missing")
                continue
            frames = sequence.get("frames")
            if not isinstance(sequence.get("transform_class"), str) or not sequence["transform_class"]:
                errors.append(f"{sequence['sequence_id']} transform_class is missing")
            if not isinstance(sequence.get("source_content_id"), str) or not sequence["source_content_id"]:
                errors.append(f"{sequence['sequence_id']} source_content_id is missing")
            if not isinstance(sequence.get("generator_seed"), int):
                errors.append(f"{sequence['sequence_id']} generator_seed is missing")
            if not isinstance(frames, list) or len(frames) < 2:
                errors.append(f"{sequence['sequence_id']} has fewer than two frames")
                continue
            timestamps = []
            for frame in frames:
                # An authored pHash is diagnostic-only.  Pixel-backed sequence
                # manifests intentionally omit it: the isolated worker must
                # decode every immutable frame and supply the sole replay
                # trace.  Metadata-only fixtures still fail below for missing
                # paths and digests.
                if not frame.get("expected_visual_id"):
                    errors.append(f"{sequence['sequence_id']} frame lacks expected_visual_id")
                path = frame.get("path")
                digest = frame.get("sha256")
                if not isinstance(path, str) or not path:
                    errors.append(f"{sequence['sequence_id']} frame lacks path")
                elif not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    errors.append(f"{sequence['sequence_id']} frame lacks SHA-256")
                else:
                    resolved = (REPO_ROOT / path).resolve()
                    try:
                        resolved.relative_to(REPO_ROOT.resolve())
                        actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
                    except OSError:
                        errors.append(f"{sequence['sequence_id']} frame path is unreadable")
                    except ValueError:
                        errors.append(f"{sequence['sequence_id']} frame path escapes repository")
                    else:
                        if actual != digest:
                            errors.append(f"{sequence['sequence_id']} frame SHA-256 mismatch")
                timestamps.append(frame.get("timestamp"))
            if any(not _finite(value) for value in timestamps) or timestamps != sorted(timestamps):
                errors.append(f"{sequence['sequence_id']} timestamps are not monotonic")
    return errors


def _sequence_event_tasks(sequences: list[dict[str, Any]]) -> tuple[list[tuple[str, str]], list[tuple[dict[str, Any], str]]]:
    """Derive persistent candidate tasks from the same state machine as replay."""
    tasks: list[tuple[str, str]] = []
    links: list[tuple[dict[str, Any], str]] = []
    for sequence in sequences:
        frames = list(sequence.get("frames", []))
        if not frames:
            continue
        hashes = _sequence_replay_hashes(frames)
        state = initial_dedupe_state(hashes[0])
        for index, frame in enumerate(frames[1:], start=1):
            def collect(kept_index: int, candidate_index: int) -> str:
                event_id = _sequence_event_id(str(sequence["sequence_id"]), index, candidate_index)
                tasks.append((_worker_frame_path(frames[kept_index]), _worker_frame_path(frames[candidate_index])))
                links.append((sequence, event_id))
                return "not_same"
            state, _trace = advance_dedupe_state(state, index, hashes[index], evaluate=collect)
    return tasks, links


def _worker_frame_path(frame: dict[str, Any]) -> str:
    """Use the verified repetition snapshot when decoded calibration is active."""
    return str(frame.get("_staged_path") or (REPO_ROOT / frame["path"]))


def _with_worker_measurements(
    manifest: dict[str, Any], *, worker: AlignmentWorker | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Attach fresh ORB/RANSAC measurements to sequence event cache entries.

    The cache may retain direct/content metadata, but never supplies alignment
    metrics. Every calibration/repro run decodes the manifest frames in the
    isolated worker and records the frame-hash provenance used for that task.
    """
    copied = json.loads(json.dumps(manifest))
    owns_worker = worker is None
    if worker is None:
        worker = AlignmentWorker()
    sequences = copied.get("development_sequences", []) + copied.get("held_out_sequences", [])
    # The authored map is strictly diagnostic. Clearing it before decoding
    # prevents orphan IDs (which no current pHash trace reaches) from leaking
    # into the canonical decoded manifest/hash.
    for sequence in sequences:
        sequence["event_measurements"] = {}
    inspections = []
    source_provenance: dict[str, dict[str, str]] = {}
    staged_hashes: dict[str, str] = {}
    succeeded = False
    try:
        # A full pipeline operates only on these immutable snapshots. The
        # source is checked both while staging and after all worker calls, so
        # a source mutation can neither mix metrics nor be silently frozen.
        with tempfile.TemporaryDirectory(prefix="lectural-alignment-") as staged_root:
            staged = Path(staged_root)
            for sequence_index, sequence in enumerate(sequences):
                for frame_index, frame in enumerate(sequence.get("frames", [])):
                    source = (REPO_ROOT / frame["path"]).resolve()
                    expected = str(frame.get("sha256", ""))
                    try:
                        payload = source.read_bytes()
                    except OSError:
                        return copied, {"worker_measurement_error": "source frame is unreadable before staging"}
                    actual = hashlib.sha256(payload).hexdigest()
                    if actual != expected:
                        return copied, {"worker_measurement_error": "source frame SHA-256 mismatch before staging"}
                    snapshot = staged / f"{sequence_index:04d}-{frame_index:04d}{source.suffix}"
                    snapshot.write_bytes(payload)
                    snapshot_digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
                    if snapshot_digest != expected:
                        return copied, {"worker_measurement_error": "staged frame SHA-256 mismatch after write"}
                    frame["_staged_path"] = str(snapshot)
                    staged_hashes[str(snapshot)] = snapshot_digest
                    source_provenance[str(snapshot)] = {
                        "path": str(frame["path"]), "sha256": expected,
                    }
            for sequence in sequences:
                for frame in sequence.get("frames", []):
                    inspection = worker.inspect(_worker_frame_path(frame))
                    inspections.append(inspection)
                    if not inspection.get("ok") or not isinstance(inspection.get("phash"), int):
                        return copied, {
                            "worker_measurement_error": "worker failed to decode staged frame for pHash",
                            "inspections": inspections,
                        }
                    frame["recomputed_phash"] = inspection["phash"]
            try:
                tasks, links = _sequence_event_tasks(sequences)
            except ValueError as exc:
                return copied, {"worker_measurement_error": str(exc), "inspections": inspections}
            baseline = [worker.compare(*task) for task in tasks]
            for snapshot_path, expected in staged_hashes.items():
                try:
                    actual = hashlib.sha256(Path(snapshot_path).read_bytes()).hexdigest()
                except OSError:
                    return copied, {"worker_measurement_error": "staged frame is unreadable after worker execution"}
                if actual != expected:
                    return copied, {"worker_measurement_error": "staged frame SHA-256 mismatch after worker execution"}
            for source_info in source_provenance.values():
                try:
                    actual = hashlib.sha256((REPO_ROOT / source_info["path"]).read_bytes()).hexdigest()
                except OSError:
                    return copied, {"worker_measurement_error": "source frame is unreadable after worker execution"}
                if actual != source_info["sha256"]:
                    return copied, {"worker_measurement_error": "source frame SHA-256 mismatch after worker execution"}
        raw = {
            "baseline_measurements": baseline,
            "inspections": inspections,
            "worker_pids": sorted({item.get("worker_pid") for item in inspections + baseline if item.get("worker_pid") is not None}),
        }
        if len(baseline) != len(links):
            return copied, {"worker_measurement_error": "worker task/result count mismatch", **raw}
        for (sequence, event_id), result, task in zip(links, baseline, tasks):
            sequence["event_measurements"][event_id] = {}
            cache = sequence["event_measurements"][event_id]
            # Every field below is a worker result derived from decoded source
            # pixels. Existing cache values are overwritten, never consulted.
            for key in (
                "direct_same", "direct_metrics", "source_phash",
                "identity_content_change", "aligned_content_change",
            ):
                cache[key] = result.get(key)
            cache["alignment"] = {key: value for key, value in result.items() if key not in {
                "direct_same", "direct_metrics", "source_phash",
                "identity_content_change", "aligned_content_change", "worker_pid",
                "reference_path", "candidate_path",
            }}
            cache["cache_provenance"] = {
                "reference_path": source_provenance[task[0]]["path"],
                "candidate_path": source_provenance[task[1]]["path"],
                "reference_sha256": source_provenance[task[0]]["sha256"],
                "candidate_sha256": source_provenance[task[1]]["sha256"],
                "measurement_source": "alignment_worker_full_decoded_pipeline",
            }
        succeeded = True
        return copied, raw
    finally:
        # Never return a dead TemporaryDirectory path. A failed pipeline must
        # also not leak partial decoded pHashes or an empty/partial cache that
        # a later caller could mistake for usable evidence.
        for sequence in sequences:
            for frame in sequence.get("frames", []):
                frame.pop("_staged_path", None)
                if not succeeded:
                    frame.pop("recomputed_phash", None)
            if not succeeded:
                sequence["event_measurements"] = {}
        if owns_worker:
            worker.close()


def _full_sequence_reproducibility(manifest: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the complete calibration input in 10+2 decoded-frame runs.

    A result cache is never a reproducibility baseline: each repetition
    revalidates source hashes, decodes frames in the worker, reattaches its
    alignment measurement, refits thresholds, replays sequences, and hashes
    that canonical payload.  Missing real content extraction is itself a
    blocker; it cannot be masked by a stable cache.
    """
    payload_hashes: dict[str, list[str]] = {"same_session": [], "fresh_worker": []}
    threshold_hashes: dict[str, list[str]] = {"same_session": [], "fresh_worker": []}
    decision_hashes: dict[str, list[str]] = {"same_session": [], "fresh_worker": []}
    worker_pids: dict[str, list[int]] = {"same_session": [], "fresh_worker": []}
    errors: list[str] = []
    def run_once(group: str, worker: AlignmentWorker) -> None:
        validation = validate_sequence_manifest(manifest)
        if validation:
            errors.extend(validation)
            return
        measured, raw = _with_worker_measurements(manifest, worker=worker)
        if raw.get("worker_measurement_error"):
            errors.append(raw["worker_measurement_error"])
            return
        pids = raw.get("worker_pids", [])
        if len(pids) != 1:
            errors.append("full decoded-frame pipeline did not use exactly one worker PID")
            return
        worker_pids[group].append(pids[0])
        if any(
            not isinstance(item.get("opencv_provenance"), dict)
            or not item["opencv_provenance"].get("distribution_supported")
            for item in raw.get("baseline_measurements", [])
        ):
            errors.append("reproducibility run did not resolve exactly the pinned opencv-python provider")
            return
        events = [
            event for sequence in measured.get("development_sequences", [])
            for event in replay_sequence(sequence, None)
        ]
        thresholds, search = find_sequence_thresholds(events)
        if thresholds is None or search.get("search_cap_exceeded") or search.get("reason") is not None:
            errors.append("reproducibility run did not complete exact threshold search")
            return
        replay = {
            split: [
                event for sequence in measured.get(f"{split}_sequences", [])
                for event in replay_sequence(sequence, thresholds)
            ]
            for split in ("development", "held_out")
        }
        threshold_hashes[group].append(_canonical_hash(thresholds))
        decision_hashes[group].append(_canonical_hash([
            (split, event["event_id"], event["result"], event["first_failed_gate"])
            for split in ("development", "held_out")
            for event in replay[split]
        ]))
        payload_hashes[group].append(_canonical_hash({
            "manifest": _canonical_decoded_manifest(measured),
            "worker": _canonical_worker_measurements(raw.get("baseline_measurements", [])),
            "thresholds": thresholds,
            "search": search,
            "replay": replay,
        }))

    try:
        same_worker = AlignmentWorker()
        try:
            for _ in range(10):
                run_once("same_session", same_worker)
        finally:
            same_worker.close()
    except (OSError, RuntimeError) as exc:
        errors.append(f"same-session worker failed: {type(exc).__name__}: {exc}")
    for _ in range(2):
        try:
            fresh_worker = AlignmentWorker()
            try:
                run_once("fresh_worker", fresh_worker)
            finally:
                fresh_worker.close()
        except (OSError, RuntimeError) as exc:
            errors.append(f"fresh worker failed: {type(exc).__name__}: {exc}")
    all_hashes = payload_hashes["same_session"] + payload_hashes["fresh_worker"]
    all_threshold_hashes = threshold_hashes["same_session"] + threshold_hashes["fresh_worker"]
    all_decision_hashes = decision_hashes["same_session"] + decision_hashes["fresh_worker"]
    return {
        "same_session_repetitions": len(payload_hashes["same_session"]),
        "fresh_worker_repetitions": len(payload_hashes["fresh_worker"]),
        "canonical_payload_hashes": payload_hashes,
        "threshold_vector_hashes": threshold_hashes,
        "ordered_decision_hashes": decision_hashes,
        "worker_pids": worker_pids,
        "passed": (
            not errors
            and len(all_hashes) == len(all_threshold_hashes) == len(all_decision_hashes) == 12
            and len(set(all_hashes)) == 1
            and len(set(all_threshold_hashes)) == 1
            and len(set(all_decision_hashes)) == 1
            and len(set(worker_pids["same_session"])) == 1
            and len(worker_pids["same_session"]) == 10
            and len(set(worker_pids["fresh_worker"])) == 2
            and len(worker_pids["fresh_worker"]) == 2
        ),
        "errors": sorted(set(errors)),
    }


def validate_complete_sequence_population(events: list[dict[str, Any]], split: str) -> list[str]:
    """Validate corpus coverage before a sequence report can be frozen.

    This intentionally validates authored event coverage, not measured gate
    names.  A semantic negative may legitimately fail at a different earlier
    diagnostic gate after a threshold vector changes.
    """
    errors: list[str] = []
    classes = {event.get("transform_class") for event in events if event.get("transform_class")}
    missing_classes = sorted(REQUIRED_TRANSFORM_CLASSES - classes)
    if missing_classes:
        errors.append(f"{split} is missing transform classes: {', '.join(missing_classes)}")
    labels = {event.get("expected_label") for event in events}
    if labels != {"same", "different"}:
        errors.append(f"{split} lacks both semantic labels")
    direct_values = {
        event["measurement"].get("direct_same")
        for event in events if isinstance(event.get("measurement"), dict)
    }
    if direct_values != {True, False}:
        errors.append(f"{split} lacks both direct_same paths")
    population = sequence_fit_populations(events)
    for name, rows in population.items():
        if {row.get("expected_label") for row in rows} != {"same", "different"}:
            errors.append(f"{split} {name} lacks both semantic labels")
    # A direct-true identity veto must exercise the fallback in both semantic
    # directions.  It is a branch contract, not an optional corpus anecdote.
    fallback_events = [event for event in events if event.get("required_fallback")]
    fallback_labels = {
        event.get("expected_label") for event in fallback_events
        if event.get("measurement", {}).get("direct_same") is True
        and event.get("alignment_required") is True
    }
    if fallback_labels != {"same", "different"}:
        errors.append(f"{split} lacks both identity-veto fallback labels")
    required_fallbacks = {
        ("same", "pan_zoom", "zoom_in"),
        ("same", "pan_zoom_reverse", "zoom_out"),
        ("different", "pan_zoom_incremental", "zoom_in"),
        ("different", "pan_zoom_shared_template", "zoom_out"),
    }
    actual_fallbacks = {
        (event.get("expected_label"), event.get("transform_class"), event.get("fallback_direction"))
        for event in fallback_events
        if event.get("measurement", {}).get("direct_same") is True
        and event.get("alignment_required") is True
    }
    missing_fallbacks = required_fallbacks - actual_fallbacks
    if missing_fallbacks:
        rendered = ", ".join("/".join(item) for item in sorted(missing_fallbacks))
        errors.append(f"{split} lacks required identity-veto fallback cases: {rendered}")
    return errors


def _canonical_json_value(value: Any) -> Any:
    """Make diagnostics hashable without turning NaN/Infinity into evidence.

    OpenCV can emit non-finite diagnostic values for deliberately pathological
    corpus rows.  They must remain explicit unavailable values, not crash the
    reproducibility gate before it can reject the corpus.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return "not_evaluated"
    if isinstance(value, dict):
        return {str(key): _canonical_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    return value


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(_canonical_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _canonical_worker_measurements(measurements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop transport topology from the pixel-derived canonical payload."""
    return [{key: value for key, value in measurement.items() if key not in {"worker_pid", "reference_path", "candidate_path"}} for measurement in measurements]


def _canonical_decoded_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Remove superseded authored pHash trace from decoded-pipeline payloads."""
    copied = json.loads(json.dumps(manifest))
    for split in ("development_sequences", "held_out_sequences"):
        for sequence in copied.get(split, []):
            for frame in sequence.get("frames", []):
                if "recomputed_phash" in frame:
                    frame.pop("phash", None)
    return copied


def validate_sequence_lineage(manifest: dict[str, Any], raw_manifest: bytes) -> list[str]:
    """Validate that final held-out evidence is fresh and disjoint."""
    errors: list[str] = []
    if manifest.get("corpus_kind") != "real_image_sequence":
        errors.append("sequence corpus is not immutable real-image evidence")
    if not isinstance(manifest.get("generator_version"), str) or not manifest["generator_version"]:
        errors.append("sequence corpus generator version is missing")
    development = manifest.get("development_sequences", [])
    held_out = manifest.get("held_out_sequences", [])
    required_classes = set(REQUIRED_TRANSFORM_CLASSES)
    development_counts = manifest.get("development_replica_counts")
    held_out_counts = manifest.get("held_out_replica_counts")
    if not isinstance(development_counts, dict) or set(development_counts) != required_classes:
        errors.append("development replica-count declaration is invalid")
        development_counts = {}
    if not isinstance(held_out_counts, dict) or set(held_out_counts) != required_classes:
        errors.append("held-out replica-count declaration is invalid")
        held_out_counts = {}
    if any(not isinstance(value, int) or value < 2 for value in development_counts.values()):
        errors.append("development corpus must declare at least two sequences per class")
    if any(value != 1 for value in held_out_counts.values()):
        errors.append("held-out corpus must declare exactly one sequence per class")
    if len(development) != sum(development_counts.values()):
        errors.append("development corpus size does not match its replica-count declaration")
    if len(held_out) != sum(held_out_counts.values()):
        errors.append("held-out corpus size does not match its replica-count declaration")
    for split_name, sequences, expected_counts in (
        ("development", development, development_counts),
        ("held-out", held_out, held_out_counts),
    ):
        for transform_class in REQUIRED_TRANSFORM_CLASSES:
            if sum(
                sequence.get("transform_class") == transform_class
                for sequence in sequences
            ) != expected_counts.get(transform_class):
                errors.append(
                    f"{split_name} corpus has the wrong replica count for {transform_class}"
                )
        if any(len(sequence.get("frames", [])) != 3 for sequence in sequences):
            errors.append(f"{split_name} corpus sequence does not contain exactly three frames")
    all_sequences = development + held_out
    all_paths = [
        frame.get("path")
        for sequence in all_sequences
        for frame in sequence.get("frames", [])
    ]
    expected_path_count = 3 * len(all_sequences)
    if len(all_paths) != expected_path_count or len(set(all_paths)) != expected_path_count:
        errors.append("sequence corpus does not contain the declared unique frame paths")
    development_digests = {
        frame.get("sha256")
        for sequence in development
        for frame in sequence.get("frames", [])
    }
    held_out_digests = {
        frame.get("sha256")
        for sequence in held_out
        for frame in sequence.get("frames", [])
    }
    if development_digests & held_out_digests:
        errors.append("development and held-out frame SHA-256 values overlap")
    generator_version = manifest.get("generator_version")
    for sequence in all_sequences:
        recipe = sequence.get("recipe")
        recipe_hash = sequence.get("recipe_sha256")
        if not isinstance(recipe, dict) or recipe.get("generator_version") != generator_version:
            errors.append("sequence recipe generator provenance is invalid")
            continue
        actual_recipe_hash = hashlib.sha256(
            json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if actual_recipe_hash != recipe_hash:
            errors.append("sequence recipe SHA-256 mismatch")
    for field in ("sequence_id", "source_content_id", "generator_seed"):
        development_values = [row.get(field) for row in development]
        held_out_values = [row.get(field) for row in held_out]
        if len(set(development_values)) != len(development_values):
            errors.append(f"development {field} values are not unique")
        if len(set(held_out_values)) != len(held_out_values):
            errors.append(f"held-out {field} values are not unique")
        if set(development_values) & set(held_out_values):
            errors.append(f"development and held-out {field} values overlap")
    retired = manifest.get("retired_holdouts")
    if not isinstance(retired, list):
        errors.append("retired held-out lineage is missing")
        retired = []
    current_hash = hashlib.sha256(raw_manifest).hexdigest()
    held_out_seeds = {
        row.get("generator_seed") for row in held_out
        if isinstance(row.get("generator_seed"), int)
    }
    for entry in retired:
        if not isinstance(entry, dict) or not re.fullmatch(
            r"[0-9a-f]{64}", str(entry.get("manifest_sha256", ""))
        ):
            errors.append("retired held-out lineage has an invalid manifest SHA-256")
            continue
        if entry["manifest_sha256"] == current_hash:
            errors.append("current held-out manifest is already retired")
        retired_seed_start = entry.get("held_out_seed_start")
        if isinstance(retired_seed_start, int) and any(
            retired_seed_start <= seed < retired_seed_start + 1000
            for seed in held_out_seeds
        ):
            errors.append("final held-out seeds reuse a retired split")
    lineage = manifest.get("lineage")
    if not isinstance(lineage, dict) or lineage.get(
        "development_protocol"
    ) != "frozen-before-final-held-out-generation" or lineage.get(
        "held_out_protocol"
    ) != "fresh-after-generator-and-search-protocol-freeze":
        errors.append("final held-out lineage protocol is missing")
    return errors


def calibrate_sequence_manifest(manifest: dict[str, Any], raw_manifest: bytes) -> dict[str, Any]:
    """Calibrate and freeze only when every measured promotion gate passes."""
    errors = validate_sequence_manifest(manifest)
    errors.extend(validate_sequence_lineage(manifest, raw_manifest))
    worker_run: dict[str, Any] | None = None
    full_reproducibility: dict[str, Any] | None = None
    provider_provenance: dict[str, Any] | None = None
    measured_manifest = manifest
    if not errors:
        measured_manifest, worker_run = _with_worker_measurements(manifest)
        if worker_run.get("worker_measurement_error"):
            errors.append(worker_run["worker_measurement_error"])
        provenances = [
            measurement.get("opencv_provenance")
            for measurement in worker_run.get("baseline_measurements", [])
            if isinstance(measurement, dict)
        ]
        unique_provenances = {
            _canonical_hash(provenance): provenance
            for provenance in provenances
            if isinstance(provenance, dict)
        }
        if len(unique_provenances) == 1:
            provider_provenance = next(iter(unique_provenances.values()))
        if (
            provider_provenance is None
            or not provider_provenance.get("distribution_supported")
            or not provider_provenance.get("provider_exact")
        ):
            errors.append("alignment worker did not resolve the exactly pinned OpenCV provider set")
        if not errors:
            full_reproducibility = _full_sequence_reproducibility(manifest)
            if not full_reproducibility["passed"]:
                errors.append("complete calibration payload is not reproducible across 10+2 decoded-frame runs")

    if errors:
        events_by_split = {"development": [], "held_out": []}
        populations = sequence_fit_populations([])
        thresholds = None
        search = {
            "reason": "preflight_or_worker_measurement_failed",
            "search_cap_exceeded": False,
        }
        evaluated_events_by_split = {"development": [], "held_out": []}
    else:
        events_by_split = {
            split: [
                event
                for sequence in measured_manifest.get(f"{split}_sequences", [])
                for event in replay_sequence(sequence, None)
            ]
            for split in ("development", "held_out")
        }
        populations = sequence_fit_populations(events_by_split["development"])
        thresholds, search = find_sequence_thresholds(events_by_split["development"])
        evaluated_events_by_split = {
            split: [
                event
                for sequence in measured_manifest.get(f"{split}_sequences", [])
                for event in replay_sequence(sequence, thresholds)
            ]
            for split in ("development", "held_out")
        }
    baseline_hashes = {
        "threshold_vector": _canonical_hash(thresholds),
        "ordered_decisions": _canonical_hash([
            (split, event["event_id"], event["result"], event["first_failed_gate"])
            for split in ("development", "held_out")
            for event in evaluated_events_by_split[split]
        ]),
        "canonical_payload": _canonical_hash({
            "manifest": _canonical_decoded_manifest(measured_manifest)
            if not errors
            else None,
            "worker": _canonical_worker_measurements(
                worker_run.get("baseline_measurements", []) if worker_run else []
            ),
            "thresholds": thresholds,
            "search": search,
            "replay": evaluated_events_by_split,
        }),
    }

    promotion_errors: list[str] = []
    expected_thresholds = {name for _raw, name, _direction in THRESHOLD_ORDER_14}
    if thresholds is None:
        promotion_errors.append("exact sequence threshold search produced no separating vector")
    elif set(thresholds) != expected_thresholds:
        promotion_errors.append("threshold vector does not contain the complete 14-field contract")
    if search.get("search_cap_exceeded"):
        promotion_errors.append(f"threshold search exceeded {search.get('reason') or 'resource'} cap")
    elif search.get("reason") is not None:
        promotion_errors.append(f"threshold search did not complete: {search['reason']}")
    if full_reproducibility and full_reproducibility.get("passed"):
        for report_field, baseline_field in (
            ("threshold_vector_hashes", "threshold_vector"),
            ("ordered_decision_hashes", "ordered_decisions"),
            ("canonical_payload_hashes", "canonical_payload"),
        ):
            consensus = (
                full_reproducibility[report_field]["same_session"]
                + full_reproducibility[report_field]["fresh_worker"]
            )
            if not consensus or any(
                value != baseline_hashes[baseline_field] for value in consensus
            ):
                promotion_errors.append(
                    f"promoted baseline {baseline_field} does not match 10+2 consensus"
                )
    for name, rows in populations.items():
        if {row["expected_label"] for row in rows} != {"same", "different"}:
            promotion_errors.append(f"{name} lacks both semantic labels")
    for split, events in evaluated_events_by_split.items():
        promotion_errors.extend(validate_complete_sequence_population(events, split))
        if any(event.get("result") not in {"same", "not_same"} for event in events):
            promotion_errors.append(f"{split} contains an unavailable terminal decision")

    development_confusion = _confusion_events(evaluated_events_by_split["development"])
    held_out_confusion = _confusion_events(evaluated_events_by_split["held_out"])
    if any(development_confusion[key] for key in ("false_positive", "false_negative")):
        promotion_errors.append("development sequence replay has classification errors")
    if any(held_out_confusion[key] for key in ("false_positive", "false_negative")):
        promotion_errors.append("held-out sequence replay has classification errors")

    blockers = list(dict.fromkeys(errors + promotion_errors))
    frozen = not blockers
    if not frozen:
        blockers.append("no frozen threshold artifact; production config and visual integration remain disabled")
    reproducibility = full_reproducibility or {
        "same_session_repetitions": 0,
        "fresh_worker_repetitions": 0,
        "canonical_payload_hashes": {"same_session": [], "fresh_worker": []},
        "threshold_vector_hashes": {"same_session": [], "fresh_worker": []},
        "ordered_decision_hashes": {"same_session": [], "fresh_worker": []},
        "worker_pids": {"same_session": [], "fresh_worker": []},
        "passed": False,
        "errors": [],
    }
    return {
        "protocol_version": PROTOCOL_VERSION,
        "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
        "frozen": frozen,
        "provider_provenance": provider_provenance,
        "thresholds": thresholds,
        "thresholds_ieee754_hex": {
            name: (str(value) if isinstance(value, int) else float(value).hex())
            for name, value in (thresholds or {}).items()
        },
        "promoted_baseline_hashes": baseline_hashes,
        "threshold_search": search,
        "events": evaluated_events_by_split,
        "development_confusion": development_confusion,
        "held_out_confusion": held_out_confusion,
        "fitting_populations": {
            name: [row["event_id"] for row in rows]
            for name, rows in populations.items()
        },
        "reproducibility": reproducibility,
        "lineage": manifest.get("lineage"),
        "retired_holdouts": list(manifest.get("retired_holdouts", [])),
        "blockers": blockers,
    }


def calibrate(manifest_path: Path) -> dict[str, Any]:
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest.decode("utf-8"))
    if "development_sequences" in manifest or "held_out_sequences" in manifest:
        return calibrate_sequence_manifest(manifest, raw_manifest)
    rows_by_split = {name: list(manifest.get(name, [])) for name in ("development", "held_out")}
    all_rows = rows_by_split["development"] + rows_by_split["held_out"]
    tasks = [(str(REPO_ROOT / row["reference"]), str(REPO_ROOT / row["candidate"])) for row in all_rows]
    reproducibility_raw = _run_reproducibility(tasks)
    measurements = reproducibility_raw["baseline_measurements"]
    split_measurements = {
        "development": measurements[: len(rows_by_split["development"])],
        "held_out": measurements[len(rows_by_split["development"]) :],
    }
    positive_metric_failures = _positive_metric_failures(
        rows_by_split["development"], split_measurements["development"]
    )
    thresholds = (
        None
        if positive_metric_failures
        else _find_thresholds(rows_by_split["development"], split_measurements["development"])
    )
    classes_by_split = {
        split: {row.get("transform_class") for row in rows}
        for split, rows in rows_by_split.items()
    }
    missing_by_split = {
        split: sorted(REQUIRED_TRANSFORM_CLASSES - classes)
        for split, classes in classes_by_split.items()
    }
    label_counts_by_split = {
        split: {
            label: sum(1 for row in rows if row.get("expected_label") == label)
            for label in ("same", "different")
        }
        for split, rows in rows_by_split.items()
    }
    missing_labels_by_split = {
        split: [label for label, count in counts.items() if count == 0]
        for split, counts in label_counts_by_split.items()
    }
    complete_corpus = all(not missing for missing in missing_by_split.values()) and all(
        not missing for missing in missing_labels_by_split.values()
    )
    holdout_pass = bool(thresholds) and all(
        _passes(measurement, thresholds) == (row["expected_label"] == "same")
        for row, measurement in zip(rows_by_split["held_out"], split_measurements["held_out"])
    )
    # A semantic corpus label is independently authored ``same``/``different``
    # truth.  The first failed implementation gate is threshold-dependent
    # diagnostic data, not another label that can be fitted by editing a
    # manifest after measurement.  Keep its distribution for review, but do
    # not make a semantic row's guessed failure family a freeze predicate.
    first_failure_distribution: dict[str, int] = {}
    for split in ("development", "held_out"):
        for row, measurement in zip(rows_by_split[split], split_measurements[split]):
            actual = _first_failed_inequality(measurement, thresholds)
            key = str(actual or "none")
            first_failure_distribution[key] = first_failure_distribution.get(key, 0) + 1
    opencv_versions = {m.get("opencv_version") for m in measurements if m.get("opencv_version")}
    opencv_version = next(iter(sorted(opencv_versions)), None)
    opencv_distribution = _opencv_distribution_info()
    opencv_supported = (
        bool(opencv_versions)
        and all(_opencv_version_supported(version) for version in opencv_versions)
        and all(
            not opencv_distribution.get("imported_cv2_version")
            or version == opencv_distribution.get("imported_cv2_version")
            for version in opencv_versions
        )
        and bool(opencv_distribution["distribution_supported"])
    )
    reproducibility = _finalize_reproducibility(reproducibility_raw, thresholds)
    # Pair manifests cannot establish pHash persistence, candidate-start
    # identity, or the direct/fallback production branch. They remain useful
    # diagnostics, but are never admissible frozen evidence.
    frozen = False
    blockers = []
    if not thresholds:
        blockers.append("no development threshold vector separates every positive and negative")
    if positive_metric_failures:
        blockers.append("development positive rows have unavailable or non-finite required alignment metrics")
    if not complete_corpus:
        blockers.append("manifest is incomplete in at least one split")
    if not holdout_pass:
        blockers.append("held-out validation failed")
    if not opencv_supported:
        blockers.append("resolved OpenCV build is outside the supported constraint")
        if not opencv_distribution.get("provider_exact", True) or not opencv_distribution.get("version_match", True):
            blockers.append("imported cv2 provider/distribution version is mixed or mismatched")
    if not reproducibility["passed"]:
        blockers.append("alignment measurements are not reproducible across the required worker runs")
    blockers.append("legacy pair manifest is diagnostic-only; sequence replay evidence is required for freeze")
    if not frozen:
        blockers.append("no frozen threshold artifact; production config and visual integration remain disabled")
    calibrated_measurements = []
    for split in ("development", "held_out"):
        for row, measurement in zip(rows_by_split[split], split_measurements[split]):
            report_measurement = dict(measurement)
            # Keep a committed report portable; the manifest row already names
            # the exact pair while the worker needs absolute paths to decode.
            report_measurement["reference_path"] = row["reference"]
            report_measurement["candidate_path"] = row["candidate"]
            calibrated_measurements.append(
                {
                    "split": split,
                    **row,
                    "measurement": report_measurement,
                    "calibrated_result": "same" if thresholds and _passes(measurement, thresholds) else "not_same",
                    "calibrated_first_failed_gate": _first_failed_inequality(measurement, thresholds),
                }
            )
    return {
        "protocol_version": PROTOCOL_VERSION,
        "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
        "opencv_constraint": OPENCV_CONSTRAINT,
        "opencv_version": opencv_version,
        "opencv_build": next((m.get("opencv_build") for m in measurements if m.get("opencv_build")), None),
        "opencv_supported": opencv_supported,
        "opencv_distribution": opencv_distribution,
        "requested_seed": 0,
        "requested_threads": 1,
        "settings": next((m.get("settings") for m in measurements if m.get("settings")), None),
        "thresholds": thresholds,
        "thresholds_ieee754_hex": {
            name: float(value).hex() for name, value in (thresholds or {}).items()
        },
        "development_confusion": _confusion(rows_by_split["development"], split_measurements["development"], thresholds),
        "held_out_confusion": _confusion(rows_by_split["held_out"], split_measurements["held_out"], thresholds),
        "required_transform_classes": sorted(REQUIRED_TRANSFORM_CLASSES),
        "missing_transform_classes_by_split": missing_by_split,
        "label_counts_by_split": label_counts_by_split,
        "missing_labels_by_split": missing_labels_by_split,
        "first_failure_distribution": first_failure_distribution,
        "development_positive_metric_failures": positive_metric_failures,
        "reproducibility": reproducibility,
        "blockers": blockers,
        "measurements": calibrated_measurements,
        "frozen": frozen,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = calibrate(args.manifest)
    output = args.out or (REPO_ROOT / "docs" / "reports" / f"alignment_thresholds_{date.today().isoformat()}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "frozen": report["frozen"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
