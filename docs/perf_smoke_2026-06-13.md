# LecturAL real-video performance smoke — 2026-06-13

Per-stage runtime and CPU/RAM for one real YouTube lecture, produced by the
non-product harness `scripts/perf_smoke.py`. The harness wraps the existing
`lectural` pipeline stage functions; it does not modify product logic.

## Exact command

```bash
uv run --with yt-dlp --with youtube-transcript-api --with "numpy==1.26.4" \
  --with setuptools --with psutil \
  --with "paddleocr==2.7.3" --with "paddlepaddle==2.6.2" \
  python scripts/perf_smoke.py \
  --url https://www.youtube.com/watch?v=19vYXnpDIyg \
  --sample-interval 0.2 --out ./output/perf-smoke
```

`ffmpeg`/`ffprobe` (Gyan build 8.1.1, installed via `winget`) were on PATH;
`yt-dlp` was provided by the `uv run` environment. The canonical install path is
`uv pip install -e ".[run]"` (see README); this run used `uv run --with ...` to
provision the same runtime deps without mutating the system environment.

## Target video

- URL: https://www.youtube.com/watch?v=19vYXnpDIyg
- Duration: 00:06:07 (~367 s), 1280x720, 30 fps
- Content: Korean lecture (captions available: 117 cues)
- Speech source used: **captions** (STT not triggered)

## Machine / environment

- Platform: Windows 10.0.26200 (x64)
- CPU: Intel Core Ultra 5 228V (`Intel64 Family 6 Model 189`), 8 logical CPUs
- Python: 3.10.12 (uv ephemeral env)
- Cache state: warm (deps + paddle models cached; video re-downloaded each run)
- Key dependency versions: paddleocr 2.7.3, paddlepaddle 2.6.2, opencv-python
  4.6.0, numpy 1.26.4, psutil 7.2.2, ffmpeg 8.1.1 (binary)

## Per-stage results

CPU% is summed across the whole process tree (harness + ffmpeg/yt-dlp children),
so values above 100% indicate multi-core usage. Sampling interval: 0.2 s.

| Stage | Wall (s) | CPU avg % | CPU peak % | RSS avg (MB) | RSS peak (MB) | Samples |
|-------|---------:|----------:|-----------:|-------------:|--------------:|--------:|
| acquisition (captions) | 0.903 | 12.5 | 28.5 | 242.0 | 243.9 | 4 |
| video_download (yt-dlp) | 1.667 | 7.1 | 7.7 | 299.0 | 312.2 | 7 |
| visual_extract (ffmpeg 2fps) | 4.119 | 5.4 | 13.3 | 378.8 | 381.7 | 16 |
| visual_dedupe (hist/SSIM) | 153.286 | 102.1 | 153.9 | 313.6 | 355.5 | 696 |
| ocr (PaddleOCR ko) | 71.827 | 291.0 | 626.0 | 622.4 | 848.4 | 119 |
| vad | 0.000 | n/a | n/a | n/a | n/a | 0 |
| synthesis | 0.003 | n/a | n/a | n/a | n/a | 0 |
| coverage | 0.003 | n/a | n/a | n/a | n/a | 0 |
| completeness_hook | 0.099 | n/a | n/a | n/a | n/a | 0 |

Total wall time (stages, excluding dependency install): ~232 s for a ~367 s
video on the captions path.

### Observations

- **`visual_dedupe` is the dominant cost (~153 s, ~1 core saturated).** It runs
  histogram + SSIM comparisons over 734 raw 2fps keyframes. This is the primary
  optimization target (e.g. coarser sampling, downscaled SSIM, vectorization).
- **`ocr` is second (~72 s) and is the most multi-core stage** (CPU avg 291%,
  peak 626%, RSS peak ~848 MB) — PaddleOCR over the 20 deduped slide frames.
- **acquisition/download/extract are negligible** when captions exist (no STT).
  If captions were absent, STT (faster-whisper medium, int8, CPU) would dominate
  instead and is expected to scale with audio length.
- `vad`/`synthesis`/`coverage`/hook are effectively free (deterministic).

## Pipeline outputs

- `transcript.md`: real, 117 caption cues (Korean), non-empty.
- 734 raw keyframes -> 20 deduped slide frames, **all 20 OCR'd with Korean
  text** (`slide_frames_with_text: 20/20`, `ocr_engine: paddleocr`).
- `summary.md`: written, ~8.8 KB, with prose/coverage/enrichment anchors.
- `outline.md`: written with required slide links.

## Completeness gate result

`completeness_hook` returned **exit 0** — gate passed. `coverage.json`:

- `gap_check.pass`: true
- `scene_coverage.pass`: true (20/20 slide frames carry OCR text)
- `artifacts.pass`: true (transcript + summary non-empty; summary anchors and
  outline slide links present)
- `overall_pass`: true

### Fixes applied to reach a clean gate (in scope, product correctness)

The first full run surfaced two real bugs (the hook was working correctly; the
inputs were wrong). Both were fixed; the completeness hook itself was kept:

1. **Coverage/summary write ordering** (`lectural/coverage.py`, `lectural/cli.py`):
   `build_coverage` previously stat'd `summary.md` before it was written, so
   `artifacts.summary_nonempty` was always false on a fresh run. `artifact_check`
   now judges non-emptiness from the rendered transcript/summary text
   (`transcript_text`/`summary_text`), and the orchestrator renders the summary
   before finalizing coverage. File-stat fallback is preserved for the hook.
2. **Windows slide-link separator** (`lectural/cli.py` `_frame_link`): slide image
   links were built with `os.path.relpath`, producing `frames\\...` on Windows,
   which failed the hook's `frames/` slide-link check (and is invalid markdown).
   Links are now normalized to POSIX `/` separators on every OS.

Both are covered by offline regression tests (`tests/test_coverage.py`,
`tests/test_cli.py`); full offline suite: 136 passed.

## Reproduction notes

- `psutil` is injected via `uv run --with psutil`; it is intentionally not a
  project dependency.
- `numpy==1.26.4` is pinned because `paddlepaddle==2.6.2` is built against the
  numpy 1.x ABI; numpy 2.x triggers `module compiled against ABI version ...`.
- `paddleocr==2.7.3` caps `opencv-python<=4.6.0.66`; let the resolver pick it.
- If neither captions nor an OCR engine are available, the harness records a
  `status: "blocked"` artifact and exits non-zero instead of fabricating metrics.
