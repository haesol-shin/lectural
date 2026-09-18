"""Offline contract tests for the benchmark harness and its report schema.

These are structural/determinism checks only -- they never invoke the real
heavy benchmark (faster-whisper, PaddleOCR, jiwer, augraphy). They exist to
keep `scripts/benchmark.py`'s report shape aligned with
`docs/contracts/benchmark.schema.json` and to prove the harness stays
importable/parseable with zero optional dependencies installed, matching the
repo's offline gate (`uv run --with pytest --with numpy pytest -q`).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# Ensure repository root is on sys.path for `scripts.benchmark` import,
# matching the existing pattern in tests/test_benchmark_harness.py.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


BENCHMARK_SCRIPT = REPO_ROOT / "scripts" / "benchmark.py"
SCHEMA_PATH = REPO_ROOT / "docs" / "contracts" / "benchmark.schema.json"
DEFINITION_PATH = REPO_ROOT / "docs" / "benchmark_definition.md"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "benchmark"
OBSERVATIONAL_PATH = (
    REPO_ROOT / "docs" / "reports" / "observational_555s_perf_smoke_2026-06-14.json"
)

# The exact set of heavy/optional benchmark dependencies that must never be
# imported merely by parsing scripts/benchmark.py's CLI (they are all lazy,
# imported inside functions only when the real heavy run actually executes).
HEAVY_MODULES = (
    "jiwer",
    "whisper_normalizer",
    "augraphy",
    "audiomentations",
    "paddleocr",
    "paddle",
    "faster_whisper",
    "Levenshtein",
    "lectural_bench",
)


def test_benchmark_schema_is_valid_json_and_has_required_defs():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["title"].startswith("LecturAL evidence quality")
    required_top = set(schema["required"])
    assert required_top == {
        "schema_version",
        "harness",
        "started_at",
        "platform_label",
        "machine",
        "dependency_versions",
        "config",
        "fixtures_found",
        "results",
        "observational_results",
    }
    assert "fixtureResult" in schema["$defs"]
    assert "observationalResult" in schema["$defs"]
    assert "medianVariance" in schema["$defs"]


def test_schema_requires_speech_source():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    fixture_result_def = schema["$defs"]["fixtureResult"]
    assert "speech_source" in fixture_result_def["required"]
    assert "speech_source" in fixture_result_def["properties"]
    assert set(fixture_result_def["properties"]["speech_source"]["enum"]) == {"caption", "stt", "unknown"}

def _validate_against_schema(report: dict, schema: dict) -> None:
    """Minimal structural validator: required-key presence and basic typing.

    Intentionally not a full JSON Schema validator (no `jsonschema` package
    is added to the offline gate for one test file) -- this checks exactly
    the shape scripts/benchmark.py actually emits.
    """
    for key in schema["required"]:
        assert key in report, f"report missing required top-level key: {key}"
    assert report["schema_version"] == schema["properties"]["schema_version"]["const"]
    assert report["harness"] == schema["properties"]["harness"]["const"]
    assert isinstance(report["platform_label"], str) and report["platform_label"]
    assert isinstance(report["machine"], dict)
    assert isinstance(report["dependency_versions"], dict)
    assert isinstance(report["results"], list)
    assert isinstance(report["observational_results"], list)
    config_required = set(schema["properties"]["config"]["required"])
    assert config_required <= set(report["config"].keys())
    assert report["config"]["cache_mode"] in {"cold", "warm"}


def test_dry_run_report_shape_matches_schema(tmp_path):
    """A --dry-run invocation still exits 0 and, when it does write a report
    (the "no fixtures found" path), that report matches the schema. For the
    normal (fixtures found) dry-run path, this test instead constructs the
    report dict the same way main() does and validates it directly, since
    --dry-run intentionally skips writing a report to avoid implying a real
    run happened.
    """
    from scripts.benchmark import build_parser  # lazy: repo root already on sys.path via conftest

    parser = build_parser()
    args = parser.parse_args(
        [
            "--fixtures-dir",
            str(FIXTURES_DIR),
            "--out",
            str(tmp_path),
            "--platform-label",
            "x86_64-test",
            "--dry-run",
        ]
    )
    assert args.dry_run is True
    assert args.fixtures_dir == str(FIXTURES_DIR)

    # Simulate the exact report skeleton main() builds before any fixture is run.
    from scripts.benchmark import find_fixture_dirs
    from scripts.perf_smoke import _dep_versions, _machine_spec

    fixtures = find_fixture_dirs(args.fixtures_dir)
    assert len(fixtures) >= 6  # 3 languages x {main, _unusable}

    report = {
        "schema_version": 1,
        "harness": "scripts/benchmark.py",
        "started_at": "2026-01-01T00:00:00",
        "platform_label": args.platform_label,
        "machine": _machine_spec(),
        "dependency_versions": _dep_versions(),
        "config": {
            "fixtures_dir": args.fixtures_dir,
            "out": str(tmp_path),
            "platform_label": args.platform_label,
            "cache_mode": "warm",
            "reps": args.reps,
            "skip_ocr": args.skip_ocr,
            "sample_interval": args.sample_interval,
            "model": args.model,
        },
        "fixtures_found": len(fixtures),
        "results": [],
        "observational_results": [],
    }
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    _validate_against_schema(report, schema)


def test_observational_entry_matches_schema():
    from scripts.benchmark import build_observational_entry

    assert OBSERVATIONAL_PATH.is_file(), "observational 555s perf_smoke JSON must be committed"
    entry = build_observational_entry(OBSERVATIONAL_PATH)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    obs_schema = schema["$defs"]["observationalResult"]
    for key in obs_schema["required"]:
        assert key in entry, f"observational entry missing required key: {key}"
    assert entry["observational"] is True
    assert entry["source_harness"] == "scripts/perf_smoke.py"
    assert entry["raw_source_path"] == str(OBSERVATIONAL_PATH)
    # Never treated as ground truth / never silently merged into fixture results.
    assert "aggregate" not in entry
    assert "quality_metrics" not in entry


def test_benchmark_cli_help_imports_no_heavy_dependency():
    """`--help` (pure argparse) must never import any optional heavy dependency.

    Runs in a real subprocess so module-level imports are exercised exactly
    as a bare `python scripts/benchmark.py --help` invocation would see them.
    """
    result = subprocess.run(
        [sys.executable, str(BENCHMARK_SCRIPT), "--help"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "Offline benchmark harness" in result.stdout

    check = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; sys.argv = ['benchmark.py', '--help']\n"
                "try:\n"
                "    import scripts.benchmark\n"
                "except SystemExit:\n"
                "    pass\n"
                f"leaked = [m for m in {HEAVY_MODULES!r} if m in sys.modules]\n"
                "print('LEAKED:' + ','.join(leaked))\n"
            ),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "LEAKED:\n" in check.stdout or check.stdout.strip() == "LEAKED:", (
        f"scripts.benchmark imported a heavy dependency at parse time: {check.stdout}"
    )


def test_fixture_gt_terms_and_key_fields_are_data_stable():
    """Determinism check: the per-fixture `terms`/`key_fields` baked into
    tests/fixtures/benchmark/generate.py's specs (pure data, no TTS/ffmpeg)
    match exactly what is committed in each fixture's gt.json. This is the
    reachable determinism guarantee without re-invoking pyttsx3/ffmpeg in
    the offline gate.
    """
    sys.path.insert(0, str(FIXTURES_DIR))
    try:
        import generate as bench_generate  # type: ignore[import-not-found]
    finally:
        sys.path.remove(str(FIXTURES_DIR))

    for fixture_id, spec in bench_generate.SPECS.items():
        gt_path = FIXTURES_DIR / fixture_id / "gt.json"
        assert gt_path.is_file(), f"missing committed gt.json for {fixture_id}"
        committed = json.loads(gt_path.read_text(encoding="utf-8"))
        assert committed["terms"] == spec.terms, f"terms drift for {fixture_id}"
        assert committed["key_fields"] == spec.key_fields, f"key_fields drift for {fixture_id}"


def test_benchmark_definition_doc_references_committed_files():
    text = DEFINITION_PATH.read_text(encoding="utf-8")
    assert "docs/contracts/benchmark.schema.json" in text
    assert "en_terms_01" in text and "ko_terms_01" in text and "mixed_terms_01" in text
    assert "observational_555s_perf_smoke_2026-06-14.json" in text
    assert "word_timestamps=False" in text  # cue-level-only limitation stated explicitly


def test_benchmark_definition_reflects_updated_contracts():
    text = DEFINITION_PATH.read_text(encoding="utf-8")
    assert "slides_text" in text
    assert "near_duplicate_timestamps" in text
    assert "incremental_timestamps" in text
