"""Deterministic, transform-aware visual confirmation.

The public pipeline does not enable this module until a calibration report has
been frozen.  Its worker boundary is intentional: OpenCV's RNG and thread
settings are process-global, so the host process must never mutate them.
"""

from __future__ import annotations

import math
import multiprocessing
import os
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Iterable


PROTOCOL_VERSION = 1
OPENCV_CONSTRAINT = ">=4.5,<=4.6.0.66"
OPENCV_LOCKED_PROVIDER_VERSIONS = {
    "opencv-contrib-python": "4.6.0.66",
    "opencv-python": "4.6.0.66",
    "opencv-python-headless": "4.6.0.66",
}
WORKER_SEED = 0
WORKER_THREADS = 1
MAX_WORKING_EDGE = 640
RATIO_TEST = 0.75
RANSAC_REPROJ_THRESHOLD = 3.0
RANSAC_MAX_ITERS = 2000
RANSAC_CONFIDENCE = 0.99
RANSAC_REFINE_ITERS = 10
MASK_EROSION_SIZE = 7


_METRIC_KEYS = (
    "ratio_match_count",
    "ratio_matches",
    "inlier_count",
    "inlier_ratio",
    "residual_median",
    "residual_p95",
    "determinant",
    "scale",
    "hull_support",
    "eigenvalue_ratio",
    "forward_coverage",
    "reverse_coverage",
    "forward_ssim",
    "reverse_ssim",
)


def _unavailable_metrics() -> dict[str, Any]:
    return {key: "not_evaluated" for key in _METRIC_KEYS}


def _result(
    *,
    result: str,
    first_failed_gate: str | None,
    **fields: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "result": result,
        "first_failed_gate": first_failed_gate,
        **_unavailable_metrics(),
    }
    out.update(fields)
    return out


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _opencv_build_signature(cv2) -> str | None:
    try:
        lines = str(cv2.getBuildInformation()).splitlines()
    except Exception:
        return None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Version control"):
            return stripped
    return next((line.strip() for line in lines if line.strip()), None)


def opencv_provenance(cv2) -> dict[str, Any]:
    """Describe the imported cv2 module and its exactly pinned provider set."""
    providers = sorted(set(importlib_metadata.packages_distributions().get("cv2", [])))
    versions: dict[str, str | None] = {}
    for provider in OPENCV_LOCKED_PROVIDER_VERSIONS:
        try:
            versions[provider] = importlib_metadata.version(provider)
        except importlib_metadata.PackageNotFoundError:
            versions[provider] = None
    expected = sorted(OPENCV_LOCKED_PROVIDER_VERSIONS)
    cv_version = str(getattr(cv2, "__version__", ""))
    module_path = getattr(cv2, "__file__", None)
    provider_exact = providers == expected
    versions_match = all(
        versions[name] == locked
        for name, locked in OPENCV_LOCKED_PROVIDER_VERSIONS.items()
    )
    return {
        "expected_providers": expected,
        "provider_candidates": providers,
        "locked_distribution_versions": OPENCV_LOCKED_PROVIDER_VERSIONS,
        "distribution_versions": versions,
        "provider_exact": provider_exact,
        "provider_present": all(name in providers for name in expected),
        "imported_cv2_version": cv_version or None,
        "imported_cv2_path": str(Path(module_path).resolve()) if module_path else None,
        "version_match": _opencv_version_compatible(
            cv_version,
            OPENCV_LOCKED_PROVIDER_VERSIONS["opencv-python"],
        ),
        "distribution_supported": (
            provider_exact
            and versions_match
            and _opencv_version_compatible(
                cv_version,
                OPENCV_LOCKED_PROVIDER_VERSIONS["opencv-python"],
            )
        ),
    }


def _opencv_version_supported(version: Any) -> bool:
    """Validate the plan's supported OpenCV version interval."""
    parts = str(version or "").split(".")
    if len(parts) < 3:
        return False
    try:
        major, minor, patch = (int(parts[index]) for index in range(3))
        build = int(parts[3]) if len(parts) > 3 else 0
    except (TypeError, ValueError):
        return False
    return major == 4 and (minor == 5 or (minor == 6 and patch == 0 and build <= 66))


def _opencv_version_compatible(cv_version: Any, distribution_version: Any) -> bool:
    def base(value: Any) -> tuple[int, int, int] | None:
        parts = str(value or "").split(".")
        if len(parts) < 3:
            return None
        try:
            return tuple(int(parts[index]) for index in range(3))
        except (TypeError, ValueError):
            return None

    imported = base(cv_version)
    distribution = base(distribution_version)
    return imported is not None and imported == distribution


def _threshold(thresholds: dict[str, Any], name: str, default: float | None = None) -> float | None:
    value = thresholds.get(name, default)
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _resize_for_alignment(image, cv2, np):
    height, width = image.shape[:2]
    longest = max(height, width)
    scale = 1.0 if longest <= MAX_WORKING_EDGE else MAX_WORKING_EDGE / longest
    if scale == 1.0:
        return image, scale
    resized = cv2.resize(
        image,
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA,
    )
    return resized, scale


def _imread_unicode(path: str, cv2, np):
    try:
        encoded = Path(path).read_bytes()
    except OSError:
        return None
    if not encoded:
        return None
    return cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)


def _box_mean(values, np, win: int = MASK_EROSION_SIZE):
    pad = win // 2
    padded = np.pad(values, pad, mode="edge")
    cumulative = np.cumsum(np.cumsum(padded, axis=0), axis=1)
    cumulative = np.pad(cumulative, ((1, 0), (1, 0)), mode="constant")
    height, width = values.shape
    total = (
        cumulative[win:win + height, win:win + width]
        - cumulative[:height, win:win + width]
        - cumulative[win:win + height, :width]
        + cumulative[:height, :width]
    )
    return total / (win * win)


def _ssim_map(a, b, np):
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mean_a = _box_mean(a, np)
    mean_b = _box_mean(b, np)
    mean_a2 = mean_a * mean_a
    mean_b2 = mean_b * mean_b
    mean_ab = mean_a * mean_b
    var_a = _box_mean(a * a, np) - mean_a2
    var_b = _box_mean(b * b, np) - mean_b2
    covariance = _box_mean(a * b, np) - mean_ab
    numerator = (2 * mean_ab + c1) * (2 * covariance + c2)
    denominator = (mean_a2 + mean_b2 + c1) * (var_a + var_b + c2)
    return np.clip(numerator / denominator, -1.0, 1.0)


def _masked_ssim(a, b, mask, np) -> float | str:
    valid = mask != 0
    if not bool(np.any(valid)):
        return "not_evaluated"
    values = _ssim_map(a.astype(np.float64), b.astype(np.float64), np)[valid]
    if values.size == 0:
        return "not_evaluated"
    return float(np.mean(values))


def _content_change_metrics(reference, candidate, support, cv2, np, pixel_delta: int) -> dict[str, float] | None:
    """Measure changed support without morphology or threshold-side effects."""
    valid = support != 0
    valid_count = int(np.count_nonzero(valid))
    if valid_count == 0 or not np.isfinite(reference).all() or not np.isfinite(candidate).all():
        return None
    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    candidate_gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY)
    difference = np.abs(reference_gray.astype(np.int16) - candidate_gray.astype(np.int16))
    changed = (difference >= int(pixel_delta)) & valid
    changed_u8 = changed.astype(np.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(changed_u8, connectivity=8)
    largest = max((int(stats[label, cv2.CC_STAT_AREA]) for label in range(1, count)), default=0)
    return {
        "changed_fraction": float(np.count_nonzero(changed)) / valid_count,
        "largest_changed_component_fraction": float(largest) / valid_count,
    }


def _p95(values, np) -> float | str:
    if len(values) == 0:
        return "not_evaluated"
    ordered = np.sort(np.asarray(values, dtype=np.float64))
    index = int(math.ceil(0.95 * len(ordered)) - 1)
    return float(ordered[max(0, min(index, len(ordered) - 1))])


def _inlier_geometry(src, np, cv2, reference_shape: tuple[int, int]) -> dict[str, Any]:
    """Calculate the plan's final-inlier geometry fields."""
    out: dict[str, Any] = {}
    if len(src) == 0:
        return out
    points = np.asarray(src, dtype=np.float64).reshape(-1, 2)
    if not np.isfinite(points).all():
        return out
    hull = cv2.convexHull(points.astype(np.float32).reshape(-1, 1, 2))
    area = float(cv2.contourArea(hull))
    height, width = reference_shape
    out["hull_support"] = area / float(width * height) if width and height else 0.0
    if len(points) < 2:
        out["eigenvalue_ratio"] = 0.0
        return out
    centered = points - np.mean(points, axis=0)
    covariance = (centered.T @ centered) / len(points)
    eigenvalues = np.linalg.eigvalsh(covariance)
    largest = float(eigenvalues[-1])
    smallest = float(eigenvalues[0])
    out["eigenvalue_ratio"] = (
        max(0.0, smallest) / largest if largest > 0.0 and math.isfinite(largest) else 0.0
    )
    return out


def _support_and_ssim(source, destination, transform, cv2, np, *, pixel_delta: int | None = None) -> tuple[float, float | str, dict[str, float] | None]:
    """Warp one direction and return pre-erosion coverage and masked SSIM."""
    dest_height, dest_width = destination.shape[:2]
    source_height, source_width = source.shape[:2]
    warped = cv2.warpAffine(
        source,
        transform,
        (dest_width, dest_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    support = cv2.warpAffine(
        np.full((source_height, source_width), 255, dtype=np.uint8),
        transform,
        (dest_width, dest_height),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    coverage = float(np.count_nonzero(support)) / float(dest_width * dest_height)
    kernel = np.ones((MASK_EROSION_SIZE, MASK_EROSION_SIZE), dtype=np.uint8)
    eroded = cv2.erode(support, kernel, iterations=1)
    source_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY).astype(np.float64)
    destination_gray = cv2.cvtColor(destination, cv2.COLOR_BGR2GRAY).astype(np.float64)
    content = None if pixel_delta is None else _content_change_metrics(warped, destination, eroded, cv2, np, pixel_delta)
    return coverage, _masked_ssim(source_gray, destination_gray, eroded, np), content


def _gate_min(value: Any, threshold: float | None) -> bool:
    return _finite(value) and (threshold is None or float(value) >= threshold)


def _gate_max(value: Any, threshold: float | None) -> bool:
    return _finite(value) and (threshold is None or float(value) <= threshold)


CANONICAL_GATE_ORDER = (
    "opencv",
    "decode",
    "descriptor",
    "ratio_matches",
    "affine",
    "matrix",
    "inliers",
    "residual",
    "geometry",
    "coverage",
    "ssim",
    "content_change",
)


def _missing(value: Any) -> bool:
    return value is None or value == "not_evaluated"


def _pending_or_failure(
    gate: str,
    *,
    complete: bool,
    unavailable: bool = False,
) -> dict[str, Any] | None:
    if not complete:
        return {"result": "pending", "first_failed_gate": gate}
    return {
        "result": "unavailable" if unavailable else "not_same",
        "first_failed_gate": gate,
    }


def _affine_is_finite(matrix: Any) -> bool:
    if not isinstance(matrix, list) or len(matrix) != 2:
        return False
    return all(
        isinstance(row, list)
        and len(row) == 3
        and all(_finite(value) for value in row)
        for row in matrix
    )


def evaluate_alignment_metadata(
    metadata: dict[str, Any],
    thresholds: dict[str, Any] | None = None,
    *,
    complete: bool = True,
) -> dict[str, Any]:
    """Evaluate the canonical alignment gates from plain worker metadata.

    ``complete=False`` is used by production while a worker is still building
    the measurement. Missing downstream values are then ``pending`` rather
    than failures; any available failed prerequisite is still terminal. The
    calibration path uses ``complete=True`` and therefore treats every
    unavailable prerequisite as a failed/no-vector measurement.
    """
    thresholds = dict(thresholds or {})

    if metadata.get("opencv_available") is False:
        return {"result": "unavailable", "first_failed_gate": "opencv"}
    if metadata.get("decode_ok") is False:
        return {"result": "unavailable", "first_failed_gate": "decode"}
    if complete and _missing(metadata.get("opencv_version")):
        return {"result": "unavailable", "first_failed_gate": "opencv"}

    descriptor_available = metadata.get("descriptors_available")
    if descriptor_available is False:
        return {"result": "not_same", "first_failed_gate": "descriptor"}
    if descriptor_available is None:
        if _missing(metadata.get("keypoint_counts")):
            failure = _pending_or_failure("descriptor", complete=complete)
            if failure is not None:
                return failure
        elif complete and _missing(metadata.get("ratio_match_count")):
            return {"result": "not_same", "first_failed_gate": "descriptor"}

    ratio_count = metadata.get("ratio_match_count")
    ratio_matches = metadata.get("ratio_matches")
    if _missing(ratio_count) or _missing(ratio_matches):
        failure = _pending_or_failure("ratio_matches", complete=complete)
        if failure is not None:
            return failure
    elif not _finite(ratio_count) or float(ratio_count) < 2 or not _finite(ratio_matches) or float(ratio_matches) < _threshold(thresholds, "ratio_matches_min", 2.0):
        return {"result": "not_same", "first_failed_gate": "ratio_matches"}

    affine = metadata.get("affine")
    if metadata.get("affine_ok") is False:
        return {"result": "not_same", "first_failed_gate": "affine"}
    if _missing(affine):
        failure = _pending_or_failure("affine", complete=complete)
        if failure is not None:
            return failure
    elif not _affine_is_finite(affine):
        return {"result": "not_same", "first_failed_gate": "affine"}

    determinant = metadata.get("determinant")
    scale = metadata.get("scale")
    if _missing(determinant) or _missing(scale):
        failure = _pending_or_failure("matrix", complete=complete)
        if failure is not None:
            return failure
    elif (
        not _finite(determinant)
        or not _finite(scale)
        or float(determinant) <= 0.0
        or float(scale) <= 0.0
        or (
            _threshold(thresholds, "scale_min") is not None
            and float(scale) < _threshold(thresholds, "scale_min")
        )
        or (
            _threshold(thresholds, "scale_max") is not None
            and float(scale) > _threshold(thresholds, "scale_max")
        )
    ):
        return {"result": "not_same", "first_failed_gate": "matrix"}

    inlier_count = metadata.get("inlier_count")
    inlier_ratio = metadata.get("inlier_ratio")
    if _missing(inlier_count) or _missing(inlier_ratio):
        failure = _pending_or_failure("inliers", complete=complete)
        if failure is not None:
            return failure
    elif (
        not _gate_min(inlier_count, _threshold(thresholds, "inlier_count_min", 1.0))
        or not _gate_min(inlier_ratio, _threshold(thresholds, "inlier_ratio_min", 0.0))
    ):
        return {"result": "not_same", "first_failed_gate": "inliers"}

    residual_median = metadata.get("residual_median")
    residual_p95 = metadata.get("residual_p95")
    if _missing(residual_median) or _missing(residual_p95):
        failure = _pending_or_failure("residual", complete=complete)
        if failure is not None:
            return failure
    elif (
        not _gate_max(residual_median, _threshold(thresholds, "residual_median_max"))
        or not _gate_max(residual_p95, _threshold(thresholds, "residual_p95_max"))
    ):
        return {"result": "not_same", "first_failed_gate": "residual"}

    hull_support = metadata.get("hull_support")
    eigenvalue_ratio = metadata.get("eigenvalue_ratio")
    if metadata.get("geometry_available") is False:
        return {"result": "not_same", "first_failed_gate": "geometry"}
    if _missing(hull_support) or _missing(eigenvalue_ratio):
        failure = _pending_or_failure("geometry", complete=complete)
        if failure is not None:
            return failure
    elif (
        not _gate_min(hull_support, _threshold(thresholds, "hull_support_min", 0.0))
        or not _gate_min(eigenvalue_ratio, _threshold(thresholds, "eigenvalue_ratio_min", 0.0))
    ):
        return {"result": "not_same", "first_failed_gate": "geometry"}

    coverages = (metadata.get("forward_coverage"), metadata.get("reverse_coverage"))
    if metadata.get("coverage_available") is False:
        return {"result": "not_same", "first_failed_gate": "coverage"}
    if any(_missing(value) for value in coverages):
        failure = _pending_or_failure("coverage", complete=complete)
        if failure is not None:
            return failure
    elif not all(_gate_min(value, _threshold(thresholds, "coverage_min", 0.0)) for value in coverages):
        return {"result": "not_same", "first_failed_gate": "coverage"}

    ssims = (metadata.get("forward_ssim"), metadata.get("reverse_ssim"))
    if metadata.get("ssim_available") is False:
        return {"result": "not_same", "first_failed_gate": "ssim"}
    if any(_missing(value) for value in ssims):
        failure = _pending_or_failure("ssim", complete=complete)
        if failure is not None:
            return failure
    elif not all(_gate_min(value, _threshold(thresholds, "ssim_min", 0.0)) for value in ssims):
        return {"result": "not_same", "first_failed_gate": "ssim"}

    return {"result": "same", "first_failed_gate": None}


def _content_change_passes(
    metadata: dict[str, Any] | None,
    thresholds: dict[str, Any],
    *,
    complete: bool,
) -> dict[str, Any]:
    """Apply the shared, fail-closed content-change predicate.

    Metric extraction stays below this pure function so calibration, sequence
    replay, and production cannot silently acquire different terminal logic.
    """
    metadata = metadata or {}
    changed = metadata.get("changed_fraction")
    largest = metadata.get("largest_changed_component_fraction")
    if _missing(changed) or _missing(largest):
        return _pending_or_failure("content_change", complete=complete) or {
            "result": "not_same", "first_failed_gate": "content_change"
        }
    if not _finite(changed) or not _finite(largest):
        return {"result": "not_same", "first_failed_gate": "content_change"}
    changed_max = _threshold(thresholds, "changed_fraction_max")
    largest_max = _threshold(thresholds, "largest_changed_component_fraction_max")
    if (changed_max is not None and float(changed) > changed_max) or (
        largest_max is not None and float(largest) > largest_max
    ):
        return {"result": "not_same", "first_failed_gate": "content_change"}
    return {"result": "same", "first_failed_gate": None}


def evaluate_visual_candidate(
    metadata: dict[str, Any],
    thresholds: dict[str, Any] | None = None,
    *,
    complete: bool = True,
) -> dict[str, Any]:
    """Evaluate the complete production branch formula from plain metadata.

    ``direct_same`` selects the identity attempt, but does not by itself merge
    a persistent pHash candidate.  A failed identity content veto enters the
    same alignment evaluator as a direct-metric miss.  Missing required data,
    worker failure, and every failed gate retain the frame (``not_same``).
    """
    thresholds = dict(thresholds or {})
    direct_same = metadata.get("direct_same")
    if direct_same is True:
        identity = _content_change_passes(
            metadata.get("identity_content_change"), thresholds, complete=complete
        )
        if identity["result"] == "pending":
            return {**identity, "path": "identity_content_change", "alignment_required": False}
        if identity["result"] == "same":
            return {"result": "same", "first_failed_gate": None, "path": "identity_content_change", "alignment_required": False}
        # Content change is a veto, not a terminal direct duplicate decision:
        # a coordinate change can still be recovered by alignment.
        identity_failure = identity["first_failed_gate"]
    elif direct_same is False:
        identity_failure = None
    else:
        return {"result": "unavailable", "first_failed_gate": "direct", "path": "unavailable", "alignment_required": False}

    alignment = evaluate_alignment_metadata(
        dict(metadata.get("alignment") or {}), thresholds, complete=complete
    )
    if alignment["result"] != "same":
        return {
            "result": alignment["result"],
            "first_failed_gate": alignment["first_failed_gate"],
            "path": "alignment_content_change",
            "alignment_required": True,
            "identity_veto_gate": identity_failure,
        }
    content = _content_change_passes(
        metadata.get("aligned_content_change"), thresholds, complete=complete
    )
    return {
        "result": content["result"],
        "first_failed_gate": content["first_failed_gate"],
        "path": "alignment_content_change",
        "alignment_required": True,
        "identity_veto_gate": identity_failure,
    }


def visual_metadata_from_worker_result(
    result: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    """Shape one plain worker result for the shared production evaluator."""
    pixel_delta = _threshold(thresholds, "pixel_delta")
    selected: dict[str, Any] = {}
    for key in ("identity_content_change", "aligned_content_change"):
        value = result.get(key)
        if isinstance(value, dict) and isinstance(value.get("by_pixel_delta"), dict):
            value = value["by_pixel_delta"].get(str(int(pixel_delta))) if pixel_delta is not None else None
        selected[key] = value
    excluded = {
        "direct_same",
        "direct_metrics",
        "source_phash",
        "identity_content_change",
        "aligned_content_change",
        "worker_pid",
        "reference_path",
        "candidate_path",
    }
    return {
        "direct_same": result.get("direct_same"),
        "direct_metrics": result.get("direct_metrics"),
        "source_phash": result.get("source_phash"),
        **selected,
        "alignment": {
            key: value
            for key, value in result.items()
            if key not in excluded
        },
    }


def _terminal_result(
    metadata: dict[str, Any],
    thresholds: dict[str, Any],
    *,
    complete: bool = False,
) -> dict[str, Any] | None:
    decision = evaluate_alignment_metadata(metadata, thresholds, complete=complete)
    if decision["result"] == "pending":
        return None
    return _result(
        result=decision["result"],
        first_failed_gate=decision["first_failed_gate"],
        **metadata,
    )


def _measure_pair(reference_path: str, candidate_path: str, thresholds: dict[str, Any]) -> dict[str, Any]:
    """Measure and gate one pair. This function runs only in the worker."""
    try:
        import cv2
        import numpy as np
    except Exception as exc:
        return _result(
            result="unavailable",
            first_failed_gate="opencv",
            error=f"{type(exc).__name__}: {exc}",
            opencv_version=None,
            requested_seed=WORKER_SEED,
            requested_threads=WORKER_THREADS,
        )

    provenance = opencv_provenance(cv2)
    base = {
        "opencv_available": True,
        "opencv_version": str(getattr(cv2, "__version__", "unknown")),
        "opencv_provenance": provenance,
        "opencv_build": _opencv_build_signature(cv2),
        "opencv_constraint": OPENCV_CONSTRAINT,
        "requested_seed": WORKER_SEED,
        "requested_threads": WORKER_THREADS,
        "reference_path": str(reference_path),
        "candidate_path": str(candidate_path),
        "settings": {
            "orb": {
                "nfeatures": 1000,
                "scaleFactor": 1.2,
                "nlevels": 8,
                "edgeThreshold": 31,
                "firstLevel": 0,
                "WTA_K": 2,
                "scoreType": "ORB_HARRIS_SCORE",
                "patchSize": 31,
                "fastThreshold": 20,
            },
            "ratio_test": RATIO_TEST,
            "ransac": {
                "reproj_threshold": RANSAC_REPROJ_THRESHOLD,
                "max_iters": RANSAC_MAX_ITERS,
                "confidence": RANSAC_CONFIDENCE,
                "refine_iters": RANSAC_REFINE_ITERS,
            },
        },
    }
    if not provenance["distribution_supported"]:
        base["opencv_available"] = False
        base["error"] = "OpenCV provider set or version does not match the calibrated runtime"
        return _terminal_result(base, thresholds, complete=True)
    reference = _imread_unicode(reference_path, cv2, np)
    candidate = _imread_unicode(candidate_path, cv2, np)
    if reference is None or candidate is None:
        base["decode_ok"] = False
        return _terminal_result(base, thresholds, complete=True)
    base["decode_ok"] = True
    base["decoded_shapes"] = {
        "reference": [int(reference.shape[1]), int(reference.shape[0])],
        "candidate": [int(candidate.shape[1]), int(candidate.shape[0])],
    }
    # These are deliberately measured here, from the decoded source pixels.
    # Calibration must never turn the manifest's diagnostic cache into an
    # alternate source of pHash/direct/content evidence.
    from .visual import _array_pair_metrics, _image_phash_from_array, is_same_slide

    reference_phash = _image_phash_from_array(reference, cv2, np)
    candidate_phash = _image_phash_from_array(candidate, cv2, np)
    identity_candidate = candidate
    if reference.shape != candidate.shape:
        identity_candidate = cv2.resize(candidate, (reference.shape[1], reference.shape[0]))
    hist_corr, direct_ssim = _array_pair_metrics(reference, identity_candidate, cv2, np)
    full_support = np.full(reference.shape[:2], 255, dtype=np.uint8)
    identity_by_delta = {
        str(delta): _content_change_metrics(
            reference,
            identity_candidate,
            full_support,
            cv2,
            np,
            delta,
        )
        for delta in (8, 12, 16, 24, 32, 48, 64)
    }
    base.update({
        "source_phash": {"reference": int(reference_phash), "candidate": int(candidate_phash)},
        "direct_metrics": {"hist_corr": hist_corr, "ssim": direct_ssim},
        "direct_same": is_same_slide(hist_corr, direct_ssim),
        "identity_content_change": {"by_pixel_delta": identity_by_delta},
    })
    pixel_delta = _threshold(thresholds, "pixel_delta")
    if base["direct_same"] is True and pixel_delta is not None:
        identity = _content_change_passes(
            identity_by_delta.get(str(int(pixel_delta))),
            thresholds,
            complete=True,
        )
        if identity["result"] == "same":
            base["alignment_skipped"] = "identity_content_change"
            return _result(result="same", first_failed_gate=None, **base)

    reference, reference_scale = _resize_for_alignment(reference, cv2, np)
    candidate, candidate_scale = _resize_for_alignment(candidate, cv2, np)
    base["working_shapes"] = {
        "reference": [int(reference.shape[1]), int(reference.shape[0])],
        "candidate": [int(candidate.shape[1]), int(candidate.shape[0])],
    }
    base["working_scales"] = {
        "reference": float(reference_scale),
        "candidate": float(candidate_scale),
    }

    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    candidate_gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(
        nfeatures=1000,
        scaleFactor=1.2,
        nlevels=8,
        edgeThreshold=31,
        firstLevel=0,
        WTA_K=2,
        scoreType=cv2.ORB_HARRIS_SCORE,
        patchSize=31,
        fastThreshold=20,
    )
    cv2.setRNGSeed(WORKER_SEED)
    keypoints_reference, descriptors_reference = orb.detectAndCompute(reference_gray, None)
    cv2.setRNGSeed(WORKER_SEED)
    keypoints_candidate, descriptors_candidate = orb.detectAndCompute(candidate_gray, None)
    keypoint_counts = {
        "reference": len(keypoints_reference or []),
        "candidate": len(keypoints_candidate or []),
    }
    base["keypoint_counts"] = keypoint_counts
    if descriptors_reference is None or descriptors_candidate is None:
        base["descriptors_available"] = False
        return _terminal_result(base, thresholds, complete=True)
    if len(descriptors_reference) < 2 or len(descriptors_candidate) < 2:
        base["descriptors_available"] = False
        return _terminal_result(base, thresholds, complete=True)
    base["descriptors_available"] = True

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    try:
        knn_rows = matcher.knnMatch(descriptors_reference, descriptors_candidate, k=2)
    except Exception as exc:
        base["error"] = f"{type(exc).__name__}: {exc}"
        return _terminal_result(base, thresholds, complete=True)
    ratio_match_count = sum(1 for row in knn_rows if len(row) == 2)
    matches = [
        (row[0], row[1])
        for row in knn_rows
        if len(row) == 2 and row[0].distance < RATIO_TEST * row[1].distance
    ]
    matches.sort(key=lambda pair: (pair[0].queryIdx, pair[0].trainIdx, pair[0].distance))
    base["ratio_match_count"] = ratio_match_count
    base["ratio_matches"] = len(matches)
    if ratio_match_count < 2 or not _finite(len(matches)):
        return _terminal_result(base, thresholds, complete=True)
    if not _gate_min(len(matches), _threshold(thresholds, "ratio_matches_min", 2.0)):
        return _terminal_result(base, thresholds, complete=True)

    src = np.float32([keypoints_reference[m.queryIdx].pt for m, _ in matches])
    dst = np.float32([keypoints_candidate[m.trainIdx].pt for m, _ in matches])
    cv2.setRNGSeed(WORKER_SEED)
    try:
        matrix, mask = cv2.estimateAffinePartial2D(
            src,
            dst,
            method=cv2.RANSAC,
            ransacReprojThreshold=RANSAC_REPROJ_THRESHOLD,
            maxIters=RANSAC_MAX_ITERS,
            confidence=RANSAC_CONFIDENCE,
            refineIters=RANSAC_REFINE_ITERS,
        )
    except Exception as exc:
        base["affine_ok"] = False
        base["error"] = f"{type(exc).__name__}: {exc}"
        return _terminal_result(base, thresholds, complete=True)
    if matrix is None or mask is None:
        base["affine_ok"] = False
        return _terminal_result(base, thresholds, complete=True)

    matrix = np.asarray(matrix, dtype=np.float64)
    base["affine"] = matrix.tolist()
    if matrix.shape != (2, 3) or not np.isfinite(matrix).all():
        return _terminal_result(base, thresholds, complete=True)
    a, b, tx = matrix[0]
    c, d, ty = matrix[1]
    determinant = float(a * d - b * c)
    scale = float(math.sqrt(a * a + c * c))
    base["determinant"] = determinant
    base["scale"] = scale
    if not _finite(determinant) or not _finite(scale) or determinant <= 0.0 or scale <= 0.0:
        return _terminal_result(base, thresholds, complete=True)
    scale_min = _threshold(thresholds, "scale_min")
    scale_max = _threshold(thresholds, "scale_max")
    if (scale_min is not None and scale < scale_min) or (scale_max is not None and scale > scale_max):
        return _terminal_result(base, thresholds, complete=True)

    inlier_mask = np.asarray(mask).reshape(-1) != 0
    inlier_indices = np.flatnonzero(inlier_mask)
    inlier_count = int(len(inlier_indices))
    inlier_ratio = float(inlier_count) / float(len(matches)) if matches else "not_evaluated"
    base["inlier_count"] = inlier_count
    base["inlier_ratio"] = inlier_ratio
    inlier_min = _threshold(thresholds, "inlier_count_min", 1.0)
    inlier_ratio_min = _threshold(thresholds, "inlier_ratio_min", 0.0)
    if inlier_count < (inlier_min or 0.0) or not _gate_min(inlier_ratio, inlier_ratio_min):
        return _terminal_result(base, thresholds, complete=True)

    transformed = (matrix[:, :2] @ src[inlier_indices].T).T + matrix[:, 2]
    residuals = np.linalg.norm(transformed - dst[inlier_indices], axis=1)
    base["residual_median"] = float(np.median(residuals))
    base["residual_p95"] = _p95(residuals, np)
    if not _gate_max(base["residual_median"], _threshold(thresholds, "residual_median_max")):
        return _terminal_result(base, thresholds, complete=True)
    if not _gate_max(base["residual_p95"], _threshold(thresholds, "residual_p95_max")):
        return _terminal_result(base, thresholds, complete=True)

    geometry = _inlier_geometry(src[inlier_indices], np, cv2, reference.shape[:2])
    base.update(geometry)
    if not _gate_min(
        base.get("eigenvalue_ratio"), _threshold(thresholds, "eigenvalue_ratio_min", 0.0)
    ) or not _gate_min(
        base.get("hull_support"), _threshold(thresholds, "hull_support_min", 0.0)
    ):
        return _terminal_result(base, thresholds, complete=True)

    try:
        pixel_delta = _threshold(thresholds, "pixel_delta")
        forward_coverage, forward_ssim, forward_content = _support_and_ssim(
            reference, candidate, matrix, cv2, np,
            pixel_delta=int(pixel_delta) if pixel_delta is not None else None,
        )
        inverse = cv2.invertAffineTransform(matrix)
        reverse_coverage, reverse_ssim, reverse_content = _support_and_ssim(
            candidate, reference, inverse, cv2, np,
            pixel_delta=int(pixel_delta) if pixel_delta is not None else None,
        )
    except Exception as exc:
        base["coverage_available"] = False
        base["error"] = f"{type(exc).__name__}: {exc}"
        return _terminal_result(base, thresholds, complete=True)
    base.update(
        {
            "forward_coverage": forward_coverage,
            "reverse_coverage": reverse_coverage,
            "forward_ssim": forward_ssim,
            "reverse_ssim": reverse_ssim,
            "forward_content_change": forward_content,
            "reverse_content_change": reverse_content,
        }
    )
    aligned_by_delta = {}
    if pixel_delta is not None:
        aligned_by_delta[str(int(pixel_delta))] = (
            None
            if forward_content is None or reverse_content is None
            else {
                "changed_fraction": max(
                    forward_content["changed_fraction"],
                    reverse_content["changed_fraction"],
                ),
                "largest_changed_component_fraction": max(
                    forward_content["largest_changed_component_fraction"],
                    reverse_content["largest_changed_component_fraction"],
                ),
            }
        )
        calls_per_direction = 1
    else:
        for delta in (8, 12, 16, 24, 32, 48, 64):
            _fc, _fs, forward = _support_and_ssim(
                reference, candidate, matrix, cv2, np, pixel_delta=delta
            )
            _rc, _rs, reverse = _support_and_ssim(
                candidate, reference, inverse, cv2, np, pixel_delta=delta
            )
            aligned_by_delta[str(delta)] = (
                None
                if forward is None or reverse is None
                else {
                    "changed_fraction": max(
                        forward["changed_fraction"], reverse["changed_fraction"]
                    ),
                    "largest_changed_component_fraction": max(
                        forward["largest_changed_component_fraction"],
                        reverse["largest_changed_component_fraction"],
                    ),
                }
            )
        calls_per_direction = 8
    base["aligned_content_change"] = {"by_pixel_delta": aligned_by_delta}
    base["alignment_warp_count"] = 4 * calls_per_direction
    base["alignment_warp_pixels"] = (
        2
        * calls_per_direction
        * (
            int(reference.shape[0] * reference.shape[1])
            + int(candidate.shape[0] * candidate.shape[1])
        )
    )
    coverage_min = _threshold(thresholds, "coverage_min", 0.0)
    if not _gate_min(forward_coverage, coverage_min) or not _gate_min(reverse_coverage, coverage_min):
        return _terminal_result(base, thresholds, complete=True)
    ssim_min = _threshold(thresholds, "ssim_min", 0.0)
    if not _gate_min(forward_ssim, ssim_min) or not _gate_min(reverse_ssim, ssim_min):
        return _terminal_result(base, thresholds, complete=True)
    return _terminal_result(base, thresholds, complete=True)


def _worker_entry(connection, thresholds: dict[str, Any]) -> None:
    """Process target; all OpenCV global state is contained here."""
    try:
        try:
            import cv2
        except Exception as exc:
            connection.send({
                "ok": True,
                "protocol_version": PROTOCOL_VERSION,
                "opencv_available": False,
                "error": f"{type(exc).__name__}: {exc}",
            })
            while True:
                command = connection.recv()
                if command is None:
                    break
                if isinstance(command, dict) and command.get("op") == "inspect":
                    connection.send({
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "path": str(command.get("path", "")),
                        "worker_pid": os.getpid(),
                    })
                    continue
                reference, candidate = command
                connection.send(_result(
                    result="unavailable",
                    first_failed_gate="opencv",
                    reference_path=str(reference),
                    candidate_path=str(candidate),
                    error=f"{type(exc).__name__}: {exc}",
                ))
            return

        cv2.setNumThreads(WORKER_THREADS)
        connection.send(
            {
                "ok": True,
                "protocol_version": PROTOCOL_VERSION,
                "opencv_version": str(getattr(cv2, "__version__", "unknown")),
                "opencv_build": _opencv_build_signature(cv2),
                "opencv_provenance": opencv_provenance(cv2),
                "requested_seed": WORKER_SEED,
                "requested_threads": WORKER_THREADS,
            }
        )
        while True:
            command = connection.recv()
            if command is None:
                break
            if isinstance(command, dict) and command.get("op") == "inspect":
                path = str(command.get("path", ""))
                image = _imread_unicode(path, cv2, __import__("numpy"))
                if image is None:
                    connection.send({"ok": False, "error": "decode failed", "path": path, "worker_pid": os.getpid()})
                else:
                    np = __import__("numpy")
                    from .visual import _image_phash_from_array
                    connection.send({"ok": True, "path": path, "phash": int(_image_phash_from_array(image, cv2, np)), "worker_pid": os.getpid()})
                continue
            reference, candidate = command
            result = _measure_pair(reference, candidate, thresholds)
            result["worker_pid"] = os.getpid()
            connection.send(result)
    except BaseException as exc:
        try:
            connection.send({
                "ok": False,
                "protocol_version": PROTOCOL_VERSION,
                "error": f"{type(exc).__name__}: {exc}",
            })
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


def _worker_failure(task: tuple[str, str], error: str) -> dict[str, Any]:
    return _result(
        result="unavailable",
        first_failed_gate="worker",
        reference_path=task[0],
        candidate_path=task[1],
        error=error,
    )


def run_alignment_batch(
    tasks: Iterable[tuple[str, str]],
    thresholds: dict[str, Any] | None = None,
    *,
    timeout_sec: float = 30.0,
) -> list[dict[str, Any]]:
    """Run an ordered task batch in one short-lived worker process.

    The parent only sends paths and receives JSON-like dictionaries.  A batch
    is the unit of process creation, so a caller can process all persistent
    candidates from one ``dedupe_frames`` invocation without one process per
    candidate.
    """
    task_list = [(str(reference), str(candidate)) for reference, candidate in tasks]
    if not task_list:
        return []
    try:
        worker = AlignmentWorker(dict(thresholds or {}), timeout_sec=timeout_sec)
    except (OSError, RuntimeError) as exc:
        return [_worker_failure(task, f"{type(exc).__name__}: {exc}") for task in task_list]
    try:
        return [worker.compare(*task) for task in task_list]
    finally:
        worker.close()


class AlignmentWorker:
    """One serial worker session for all alignment candidates in one call."""

    def __init__(self, thresholds: dict[str, Any] | None = None, *, timeout_sec: float = 30.0):
        context = multiprocessing.get_context("spawn")
        self._parent, child = context.Pipe(duplex=True)
        self._timeout_sec = timeout_sec
        self._process = context.Process(target=_worker_entry, args=(child, dict(thresholds or {})))
        self._process.daemon = True
        self._closed = False
        self._process.start()
        child.close()
        if not self._parent.poll(timeout_sec):
            self.close()
            raise RuntimeError("alignment worker failed to initialize")
        hello = self._parent.recv()
        if not hello.get("ok"):
            self.close()
            raise RuntimeError(str(hello.get("error", "alignment worker failed to initialize")))

    def compare(self, reference_path: str, candidate_path: str) -> dict[str, Any]:
        task = (str(reference_path), str(candidate_path))
        if self._closed:
            return _worker_failure(task, "alignment worker session is unusable")
        try:
            if not self._process.is_alive():
                self._mark_unusable("alignment worker exited")
                return _worker_failure(task, "alignment worker exited")
            self._parent.send(task)
            if not self._parent.poll(self._timeout_sec):
                self._mark_unusable("alignment worker timed out")
                return _worker_failure(task, "alignment worker timed out")
            result = self._parent.recv()
            if isinstance(result, dict) and result.get("ok") is False:
                self._mark_unusable(str(result.get("error", "alignment worker failed")))
                return _worker_failure(task, str(result.get("error", "alignment worker failed")))
            return result if isinstance(result, dict) else _worker_failure(task, "invalid alignment result")
        except (BrokenPipeError, EOFError, OSError, RuntimeError) as exc:
            self._mark_unusable(f"{type(exc).__name__}: {exc}")
            return _worker_failure(task, f"{type(exc).__name__}: {exc}")

    def inspect(self, image_path: str) -> dict[str, Any]:
        """Decode one source frame in this session and return its pHash."""
        if self._closed:
            return {"ok": False, "error": "alignment worker session is unusable"}
        try:
            self._parent.send({"op": "inspect", "path": str(image_path)})
            if not self._parent.poll(self._timeout_sec):
                self._mark_unusable("alignment worker timed out")
                return {"ok": False, "error": "alignment worker timed out"}
            result = self._parent.recv()
            return result if isinstance(result, dict) else {"ok": False, "error": "invalid inspection result"}
        except (BrokenPipeError, EOFError, OSError, RuntimeError) as exc:
            self._mark_unusable(f"{type(exc).__name__}: {exc}")
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _mark_unusable(self, reason: str) -> None:
        """Terminate immediately so a late result cannot poison a later task."""
        if self._closed:
            return
        self._closed = True
        if self._process.is_alive():
            self._process.terminate()
        self._process.join(timeout=5.0)
        self._parent.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._process.is_alive():
                self._parent.send(None)
                self._process.join(timeout=5.0)
        except (BrokenPipeError, EOFError, OSError):
            pass
        finally:
            if self._process.is_alive():
                self._process.terminate()
            self._process.join(timeout=5.0)
            self._parent.close()


__all__ = [
    "MAX_WORKING_EDGE",
    "OPENCV_CONSTRAINT",
    "PROTOCOL_VERSION",
    "OPENCV_LOCKED_PROVIDER_VERSIONS",
    "AlignmentWorker",
    "CANONICAL_GATE_ORDER",
    "evaluate_alignment_metadata",
    "visual_metadata_from_worker_result",
    "evaluate_visual_candidate",
    "opencv_provenance",
    "run_alignment_batch",
]
