#!/usr/bin/env python3
"""Create the immutable decoded-image sequence corpus used by Issue #22.

The committed manifest is derived only from deterministic, authored image
recipes.  Development and held-out use disjoint seeds and source-content IDs;
the generator never inspects alignment measurements while assigning labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lectural.visual import _image_phash_from_array
from scripts.calibrate_alignment import REQUIRED_TRANSFORM_CLASSES


CORPUS_ROOT = ROOT / "tests" / "fixtures" / "visual_alignment" / "corpus_v1"
MANIFEST_PATH = ROOT / "tests" / "fixtures" / "visual_alignment" / "sequence_manifest_v1.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canvas(seed: int, *, changed: bool = False) -> np.ndarray:
    """Return a text- and geometry-rich, independently authored 640x360 image."""
    rng = np.random.default_rng(seed)
    image = np.full((360, 640, 3), (245, 244, 240), dtype=np.uint8)
    image[:, :, 0] = np.linspace(228, 250, 640, dtype=np.uint8)
    accent = tuple(int(value) for value in rng.integers(35, 180, size=3))
    cv2.rectangle(image, (24, 22), (616, 72), accent, -1)
    cv2.putText(image, f"LECTURAL EVIDENCE {seed}", (42, 56), cv2.FONT_HERSHEY_SIMPLEX, .72, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(image, "Transform-aware visual evidence", (42, 118), cv2.FONT_HERSHEY_SIMPLEX, .72, (20, 24, 36), 2, cv2.LINE_AA)
    lines = ["An authored screen must remain one visual identity.", "Incremental content is a different evidence event.", "Calibration uses immutable decoded image bytes."]
    for index, line in enumerate(lines):
        y = 158 + index * 38
        cv2.circle(image, (52, y - 6), 6, accent, -1)
        cv2.putText(image, line, (72, y), cv2.FONT_HERSHEY_SIMPLEX, .46, (28, 32, 40), 1, cv2.LINE_AA)
    for index in range(9):
        x = 48 + index * 61
        height = int(rng.integers(14, 64))
        cv2.rectangle(image, (x, 334 - height), (x + 35, 334), tuple(int(v) for v in rng.integers(30, 220, size=3)), -1)
    if changed:
        cv2.rectangle(image, (388, 190), (602, 272), (32, 32, 180), -1)
        cv2.putText(image, "CHANGED", (404, 238), cv2.FONT_HERSHEY_SIMPLEX, .72, (255, 255, 255), 2, cv2.LINE_AA)
    return image


def _zoom_pan(image: np.ndarray, scale: float, dx: int, dy: int) -> np.ndarray:
    height, width = image.shape[:2]
    matrix = np.array([[scale, 0.0, dx], [0.0, scale, dy]], dtype=np.float32)
    return cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def _candidate(reference: np.ndarray, transform_class: str, seed: int) -> np.ndarray:
    """Apply an authored transform or semantic change without reading metrics."""
    if transform_class == "pan_zoom":
        return _zoom_pan(reference, 1.16, -44, -23)
    if transform_class == "pan_zoom_reverse":
        return _zoom_pan(reference, .86, 46, 27)
    if transform_class in {"static_duplicate", "static_shift"}:
        return _zoom_pan(reference, 1.05, -16, -8)
    if transform_class == "out_of_scale":
        return _zoom_pan(reference, 1.34, -100, -54)
    if transform_class in {"incremental_build", "pan_zoom_incremental"}:
        result = reference.copy()
        cv2.rectangle(result, (360, 204), (607, 286), (14, 100, 38), -1)
        cv2.putText(result, "NEW FACT", (381, 253), cv2.FONT_HERSHEY_SIMPLEX, .7, (255, 255, 255), 2, cv2.LINE_AA)
        return _zoom_pan(result, 1.11, -32, -18) if transform_class.startswith("pan_") else result
    if transform_class == "pan_zoom_shared_template":
        return _zoom_pan(_canvas(seed + 50000, changed=True), .88, 42, 24)
    if transform_class == "too_few_descriptors":
        return np.full_like(reference, 127)
    if transform_class == "collinear_inliers":
        result = np.full_like(reference, 246)
        cv2.line(result, (20, 180), (620, 180), (0, 0, 0), 3)
        for x in range(40, 620, 40):
            cv2.circle(result, (x, 180), 7, (0, 0, 0), -1)
        return result
    if transform_class == "low_masked_ssim":
        result = _zoom_pan(reference, 1.14, -38, -20)
        return cv2.GaussianBlur(result, (31, 31), 0)
    if transform_class == "one_way_coverage":
        return _zoom_pan(reference, 1.23, -126, -76)
    if transform_class == "same_palette_different_layout":
        return np.rot90(reference, 2).copy()
    if transform_class == "high_residual":
        result = _canvas(seed + 30000, changed=True)
        for y in range(25, 330, 45):
            cv2.circle(result, (80 + (y % 140), y), 16, (0, 0, 0), -1)
        return result
    if transform_class == "outlier_heavy":
        result = _canvas(seed + 40000, changed=True)
        noise = np.random.default_rng(seed + 7).integers(0, 255, result.shape, dtype=np.uint8)
        return cv2.addWeighted(result, .52, noise, .48, 0)
    # true_transition and ransac_failure are independently authored changed screens.
    return _canvas(seed + 10000, changed=True)


def _write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = cv2.imencode(".png", image)[1]
    path.write_bytes(encoded.tobytes())


def _frame(path: Path, timestamp: float, visual_id: str) -> dict[str, Any]:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return {
        "timestamp": timestamp,
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _digest(path),
        "phash": int(_image_phash_from_array(image, cv2, np)),
        "expected_visual_id": visual_id,
    }


def _sequence(split: str, transform_class: str, seed: int) -> dict[str, Any]:
    sequence_id = f"{split}-{transform_class}-{seed}"
    root = CORPUS_ROOT / split / sequence_id
    reference = _canvas(seed)
    candidate = _candidate(reference, transform_class, seed)
    reference_path, candidate_path = root / "frame_000.png", root / "frame_001.png"
    _write_image(reference_path, reference)
    _write_image(candidate_path, candidate)
    same = transform_class in {"static_shift", "static_duplicate", "pan_zoom", "pan_zoom_reverse"}
    source_id = f"{split}-authored-canvas-{seed}"
    candidate_id = source_id if same else f"{source_id}-changed"
    return {
        "sequence_id": sequence_id,
        "transform_class": transform_class,
        "source_content_id": source_id,
        "generator_seed": seed,
        "frames": [
            _frame(reference_path, 0.0, source_id),
            _frame(candidate_path, 0.5, candidate_id),
            _frame(candidate_path, 1.0, candidate_id),
        ],
    }


def build_manifest() -> dict[str, Any]:
    classes = sorted(REQUIRED_TRANSFORM_CLASSES)
    development = [_sequence("development", name, 11000 + index * 10 + replica) for index, name in enumerate(classes) for replica in range(2)]
    held_out = [_sequence("held_out", name, 21000 + index * 10) for index, name in enumerate(classes)]
    return {
        "manifest_version": 3,
        "generator_version": "issue-22-real-image-sequence-v1",
        "development_sequences": development,
        "held_out_sequences": held_out,
        "retired_holdouts": [],
        "labels": "Authored before ORB/RANSAC measurement; held_out seeds and source_content_id values are disjoint from development.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args(argv)
    manifest = build_manifest()
    args.out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
