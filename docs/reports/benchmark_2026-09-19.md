# First real benchmark run — 2026-09-19

First end-to-end execution of `scripts/benchmark.py` with real `faster-whisper`,
`PaddleOCR`, and `jiwer`/`whisper-normalizer` installed (the `bench` + `run`
optional-dependency groups), on both supported profiles. Scope: one fixture
(`en_terms_01`), `--reps 1`, `--warm`, to validate the harness end-to-end
before a full matrix run; not a complete quality/resource characterization.

## Exact commands

```bash
uv pip install -e ".[run,bench]"
uv run --with psutil python scripts/benchmark.py \
  --fixtures-dir tests/fixtures/benchmark/en_terms_01 \
  --out output/benchmark-run --platform-label <x86_64-win|arm64-pi-server> \
  --warm --reps 1 --model small
```

Raw reports: [`real_run_x86_64-win_2026-09-19.json`](real_run_x86_64-win_2026-09-19.json), [`real_run_arm64-pi-server_2026-09-19.json`](real_run_arm64-pi-server_2026-09-19.json).

## Environment

| | x86_64 | ARM64 (`pi-server`) |
|---|---|---|
| Platform | Windows-10-10.0.26200-SP0 | Linux-6.18.34+rpt-rpi-2712-aarch64 |
| CPU cores | 8 | 4 |
| Python | 3.11.15 | 3.12.13 |

## Result summary (single run, `en_terms_01`, clean variant, OCR on)

| Metric | x86_64 | ARM64 |
|---|---:|---:|
| Wall time (s) | 9.63 | 49.82 |
| RTF (wall/duration) | 0.499 | 2.581 |
| OCR stage CPU avg % | 285.5 | 56.8 |
| OCR stage RSS peak (MB) | 723.2 | 809.5 |
| `wer_cer` | `{wer: 0.0, cer: 0.0}` | `{wer: 0.0, cer: 0.0}` |
| `terminology_recall` | 1.0 | 1.0 |
| `degraded_slide_ocr` (l1 CER / l2 CER) | 0.704 / 0.857 | 0.704 / 0.857 |

Caption path (usable VTT, mocked `fetch_caption_segments`) produced a
byte-for-byte perfect transcript on both platforms (`wer`/`cer` 0.0),
confirming the caption-injection mechanism reaches the real
`acquire_speech` code path identically cross-platform. `degraded_slide_ocr`
is identical on both platforms (deterministic PaddleOCR output on the same
committed PNG), a useful cross-platform determinism check.

ARM64's ~5x higher RTF matches the 4-vs-8-core gap plus per-core throughput
difference; ARM64's OCR CPU% is lower in relative percent (4 cores, less
headroom to exceed 100%) despite taking longer in wall time — consistent
with `docs/perf_smoke_2026-06-13.md`'s observation that OCR is the dominant,
most multi-core-hungry stage.

## `--media-variant degraded` and `--skip-ocr` (x86_64 only, this pass)

| Variant | Wall time (s) | RTF |
|---|---:|---:|
| clean, OCR on | 9.63–10.05 | 0.50–0.52 |
| degraded (360p video + noisy audio), OCR on | 9.80 | 0.51 |
| clean, `--skip-ocr` | 3.85 | 0.20 |

`--skip-ocr` cuts wall time by ~60% on this fixture, confirming OCR is the
dominant cost even on a 20-second synthetic clip, consistent with the real
555-second YouTube observation below.

## Bugs found and fixed by this real run (not caught by offline mocks)

1. **`wer_cer` empty-reference edge case with real `jiwer` installed**
   (`lectural_bench/metrics.py`): the pure-Python fallback path correctly
   capped empty-reference WER/CER at 1.0, but the `jiwer`-backed path had no
   such guard and returned unbounded values (`wer: 2.0`, `cer: 7.0`) once
   `jiwer` was actually installed and exercised — invisible in the offline
   suite, which never has `jiwer` installed. Fixed by guarding both branches
   identically before delegating to `jiwer`.
2. **`degraded_slide_ocr` never populated** (`scripts/benchmark.py`): the
   glob for `slide_degraded_l*.png` searched the fixture root, but the
   generator writes those files under `slides/`. Fixed with a fallback glob;
   confirmed populated and cross-platform-identical after the fix.

## Observational reference

The pre-existing real 555-second YouTube run
([`observational_555s_perf_smoke_2026-06-14.json`](observational_555s_perf_smoke_2026-06-14.json),
`scripts/perf_smoke.py`) remains an `observational: true` reference only —
not part of this fixture-based controlled comparison, and not re-run here.

## Not yet covered by this pass

- KO/mixed fixtures, `caption-fallback`/`force_stt` speech paths, `cold`
  cache mode, and `n=3` repetitions (this pass used `n=1` on one fixture to
  validate the harness end-to-end; a full matrix run is follow-up work, not
  a blocker for this PR).
