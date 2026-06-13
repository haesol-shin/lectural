"""Offline unit tests for the non-product perf-smoke harness helpers.

These cover the deterministic logic of `scripts/perf_smoke.py` without any
network, binaries, or models. The real end-to-end run and its metrics live in
`docs/perf_smoke_2026-06-13.md` and `artifacts/g003-perf_metrics.json`.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_HARNESS = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "perf_smoke.py"
_spec = importlib.util.spec_from_file_location("perf_smoke", _HARNESS)
perf_smoke = importlib.util.module_from_spec(_spec)
sys.modules["perf_smoke"] = perf_smoke  # dataclass introspection needs the module registered
_spec.loader.exec_module(perf_smoke)


def _make_sampler():
    return perf_smoke.StageSampler(interval=0.2, _psutil=None, _proc=None)


def test_stage_summary_computes_avg_and_peak() -> None:
    s = _make_sampler()
    s.samples = {
        "ocr": {"cpu": [100.0, 300.0], "rss": [500e6, 900e6]},
    }
    out = s.summary()["ocr"]
    assert out["cpu_pct_avg"] == 200.0
    assert out["cpu_pct_peak"] == 300.0
    assert out["rss_mb_avg"] == 700.0
    assert out["rss_mb_peak"] == 900.0
    assert out["n_samples"] == 2


def test_stage_summary_handles_empty_bucket() -> None:
    s = _make_sampler()
    s.samples = {"idle": {"cpu": [], "rss": []}}
    out = s.summary()["idle"]
    assert out["cpu_pct_peak"] == 0.0
    assert out["rss_mb_peak"] == 0.0
    assert out["n_samples"] == 0


def test_set_stage_changes_active_label() -> None:
    s = _make_sampler()
    assert s._stage == "idle"
    s.set_stage("visual_dedupe")
    assert s._stage == "visual_dedupe"


def test_machine_spec_has_expected_keys() -> None:
    spec = perf_smoke._machine_spec()
    for key in ("platform", "processor", "python", "cpu_count"):
        assert key in spec


def test_dep_versions_is_a_dict_with_probed_modules() -> None:
    versions = perf_smoke._dep_versions()
    assert isinstance(versions, dict)
    # psutil and numpy are probed; values are version strings or MISSING markers.
    assert "psutil" in versions and "numpy" in versions
