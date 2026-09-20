"""Determinism and gate-order tests for the transform-aware visual helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from lectural.alignment import (
    AlignmentWorker,
    PROTOCOL_VERSION,
    evaluate_visual_candidate,
    run_alignment_batch,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "benchmark" / "en_terms_01" / "slides"
REFERENCE = FIXTURE_DIR / "slide_01_concept.png"
NEAR_DUPLICATE = FIXTURE_DIR / "slide_02_near_dup.png"
TRANSITION = FIXTURE_DIR / "slide_00_title.png"


def test_alignment_worker_is_one_batch_and_returns_plain_metadata():
    pytest.importorskip("cv2")
    results = run_alignment_batch(
        [(str(REFERENCE), str(NEAR_DUPLICATE)), (str(REFERENCE), str(TRANSITION))],
        {"ssim_min": 0.90},
    )
    assert len(results) == 2
    assert all(result["protocol_version"] == PROTOCOL_VERSION for result in results)
    assert results[0]["result"] == "same"
    assert isinstance(results[0]["ratio_matches"], int)
    assert isinstance(results[0]["inlier_count"], int)
    assert results[0]["opencv_version"]
    assert results[0]["opencv_build"]
    assert results[0]["forward_ssim"] >= 0.90
    assert results[1]["result"] == "not_same"


def test_alignment_worker_session_reuses_one_process_for_serial_candidates():
    pytest.importorskip("cv2")
    worker = AlignmentWorker({"ssim_min": 0.90})
    try:
        worker_pid = worker._process.pid
        first = worker.compare(str(REFERENCE), str(NEAR_DUPLICATE))
        second = worker.compare(str(REFERENCE), str(NEAR_DUPLICATE))
        assert worker._process.pid == worker_pid
        assert first["result"] == second["result"] == "same"
    finally:
        worker.close()


def test_alignment_worker_timeout_terminates_session_and_drops_late_response(monkeypatch):
    pytest.importorskip("cv2")
    worker = AlignmentWorker({"ssim_min": 0.90}, timeout_sec=30.0)
    try:
        monkeypatch.setattr(type(worker._parent), "poll", lambda _self, _timeout: False)
        first = worker.compare(str(REFERENCE), str(NEAR_DUPLICATE))
        assert first["result"] == "unavailable"
        assert first["first_failed_gate"] == "worker"
        assert worker._closed is True
        assert not worker._process.is_alive()

        # A hypothetical late response must not be consumed as the next pair.
        second = worker.compare(str(REFERENCE), str(NEAR_DUPLICATE))
        assert second["result"] == "unavailable"
        assert second["first_failed_gate"] == "worker"
    finally:
        worker.close()


def test_alignment_gate_order_reports_first_failed_gate():
    pytest.importorskip("cv2")
    results = run_alignment_batch(
        [(str(REFERENCE), str(NEAR_DUPLICATE))],
        {"ratio_matches_min": 10_000},
    )
    result = results[0]
    assert result["result"] == "not_same"
    assert result["first_failed_gate"] == "ratio_matches"
    assert result["ratio_matches"] < 10_000
    assert result["inlier_count"] == "not_evaluated"
    assert result["forward_ssim"] == "not_evaluated"


def test_alignment_fails_closed_for_missing_path():
    results = run_alignment_batch([("missing-reference.png", str(NEAR_DUPLICATE))])
    assert results[0]["result"] == "unavailable"
    assert results[0]["first_failed_gate"] == "decode"


def test_alignment_normalizes_unequal_dimensions_for_identity_content(tmp_path):
    cv2 = pytest.importorskip("cv2")
    reference = cv2.imread(str(REFERENCE))
    resized_path = tmp_path / "resized-reference.png"
    resized = cv2.resize(reference, (reference.shape[1] // 2, reference.shape[0] // 2))
    assert cv2.imwrite(str(resized_path), resized)

    result = run_alignment_batch([(str(REFERENCE), str(resized_path))])[0]

    assert result["result"] == "same"
    assert result["decoded_shapes"]["reference"] != result["decoded_shapes"]["candidate"]
    assert "error" not in result


def test_visual_evaluator_requires_identity_content_veto_before_direct_merge():
    decision = evaluate_visual_candidate(
        {
            "direct_same": True,
            "identity_content_change": {
                "changed_fraction": 0.01,
                "largest_changed_component_fraction": 0.01,
            },
        },
        {"changed_fraction_max": 0.02, "largest_changed_component_fraction_max": 0.02},
    )
    assert decision == {
        "result": "same",
        "first_failed_gate": None,
        "path": "identity_content_change",
        "alignment_required": False,
    }


def test_visual_evaluator_falls_back_after_identity_veto_and_fails_closed():
    decision = evaluate_visual_candidate(
        {
            "direct_same": True,
            "identity_content_change": {
                "changed_fraction": 0.5,
                "largest_changed_component_fraction": 0.5,
            },
            "alignment": {"opencv_available": False},
        },
        {"changed_fraction_max": 0.02, "largest_changed_component_fraction_max": 0.02},
    )
    assert decision["result"] == "unavailable"
    assert decision["first_failed_gate"] == "opencv"
    assert decision["alignment_required"] is True
    assert decision["identity_veto_gate"] == "content_change"
