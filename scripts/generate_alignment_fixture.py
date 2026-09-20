#!/usr/bin/env python3
"""Generate the deterministic, metadata-only sequence corpus for Issue #22.

The corpus is deliberately synthetic: labels are decided by the recipe before
any ORB/RANSAC measurement.  It is a calibration-contract fixture, not frozen
evidence and not a substitute for the required independently generated image
corpus/held-out run.  The emitted measurement cache lets pure search and state
machine tests exercise every production branch without importing OpenCV.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.calibrate_alignment import REQUIRED_TRANSFORM_CLASSES


PIXEL_DELTAS = (8, 12, 16, 24, 32, 48, 64)


def _content(changed: float, largest: float) -> dict[str, Any]:
    return {
        "by_pixel_delta": {
            str(delta): {
                "changed_fraction": changed,
                "largest_changed_component_fraction": largest,
            }
            for delta in PIXEL_DELTAS
        }
    }


def _alignment(*, same: bool, failure: str | None = None) -> dict[str, Any]:
    values: dict[str, Any] = {
        "opencv_version": "4.6.0",
        "keypoint_counts": {"reference": 200, "candidate": 200},
        "descriptors_available": True,
        "ratio_match_count": 120,
        "ratio_matches": 100,
        "affine_ok": True,
        "affine": [[1.0, 0.0, 1.0], [0.0, 1.0, 1.0]],
        "determinant": 1.0,
        "scale": 1.0,
        "inlier_count": 90,
        "inlier_ratio": 0.9,
        "residual_median": 0.1,
        "residual_p95": 0.2,
        "hull_support": 0.5,
        "eigenvalue_ratio": 0.5,
        "forward_coverage": 0.95,
        "reverse_coverage": 0.95,
        "forward_ssim": 0.95,
        "reverse_ssim": 0.95,
    }
    if not same:
        failures = {
            "too_few_descriptors": ("descriptors_available", False),
            "ransac_failure": ("affine_ok", False),
            "outlier_heavy": ("inlier_ratio", 0.01),
            "high_residual": ("residual_p95", 9.0),
            "out_of_scale": ("scale", 1.5),
            "collinear_inliers": ("hull_support", 0.001),
            "one_way_coverage": ("reverse_coverage", 0.05),
            "low_masked_ssim": ("reverse_ssim", 0.05),
            "true_transition": ("ratio_matches", 1),
            "same_palette_different_layout": ("eigenvalue_ratio", 0.01),
        }
        field, value = failures.get(failure or "true_transition", ("ratio_matches", 1))
        values[field] = value
    return values


def _sequence(split: str, transform_class: str, seed: int, ordinal: int) -> dict[str, Any]:
    positive_classes = {"static_shift", "static_duplicate", "pan_zoom", "pan_zoom_reverse"}
    same = transform_class in positive_classes
    direct_true = transform_class in {"static_shift", "pan_zoom", "pan_zoom_reverse", "incremental_build", "pan_zoom_incremental", "pan_zoom_shared_template"}
    # The three direct-true different classes are deliberate identity-veto
    # cases.  Their fallback remains alignment-reachable; content rejects them.
    fallback = transform_class in {"pan_zoom", "pan_zoom_reverse", "pan_zoom_incremental", "pan_zoom_shared_template"}
    direction = "zoom_in" if transform_class in {"pan_zoom", "pan_zoom_incremental"} else "zoom_out"
    source = f"{split}-canvas-{seed:03d}"
    visual_id = source if same else f"{source}-changed"
    candidate_hash = (1 << 17) - 1 - ordinal
    event_id = f"{split}-{transform_class}-{seed}:2:1"
    measurement = {
        "direct_same": direct_true,
        "identity_content_change": _content(0.20 if fallback else 0.0, 0.15 if fallback else 0.0),
        "alignment": _alignment(same=same or fallback, failure=transform_class),
        "aligned_content_change": _content(0.20 if not same else 0.0, 0.15 if not same else 0.0),
    }
    recipe = {
        "source_content_id": source,
        "transform_class": transform_class,
        "generator_seed": seed,
        "same_authored_canvas": same,
        "direct_same": direct_true,
        "required_fallback": fallback,
        "fallback_direction": direction if fallback else None,
    }
    return {
        "sequence_id": f"{split}-{transform_class}-{seed}",
        "transform_class": transform_class,
        "source_content_id": source,
        "generator_seed": seed,
        "required_fallback": fallback,
        "fallback_direction": direction if fallback else None,
        "recipe": recipe,
        "recipe_sha256": hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest(),
        "frames": [
            {"timestamp": 0.0, "phash": 0, "expected_visual_id": source},
            {"timestamp": 1.0, "phash": candidate_hash, "expected_visual_id": visual_id},
            {"timestamp": 2.0, "phash": candidate_hash, "expected_visual_id": visual_id},
        ],
        "event_measurements": {event_id: measurement},
    }


def build_synthetic_sequence_manifest() -> dict[str, Any]:
    """Return two development seeds and one disjoint held-out seed per class."""
    classes = sorted(REQUIRED_TRANSFORM_CLASSES)
    development = [
        _sequence("development", transform_class, 1000 + index * 2 + replica, index)
        for index, transform_class in enumerate(classes)
        for replica in range(2)
    ]
    held_out = [
        _sequence("held-out", transform_class, 2000 + index, index)
        for index, transform_class in enumerate(classes)
    ]
    return {
        "manifest_version": 2,
        "generator_version": "issue-22-alignment-synthetic-sequence-v1",
        "development_sequences": development,
        "held_out_sequences": held_out,
        "retired_holdouts": [],
        "synthetic_only": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.write_text(json.dumps(build_synthetic_sequence_manifest(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
