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
- Content: Korean lecture (captions available: 117 cues, language auto)
- Speech source used: **captions** (STT not triggered; faster-whisper not loaded
  in this OCR-enabled run)

## Machine / environment

- Platform: Windows 10.0.26200 (x64)
- CPU: Intel Core Ultra 5 228V (`Intel64 Family 6 Model 189`), 8 logical CPUs
- Python: 3.10.12 (uv ephemeral env)
- Cache state: warm (deps cached by uv; video re-downloaded each run)
- Key dependency versions: paddleocr 2.7.3, paddlepaddle 2.6.2, opencv-python
  4.6.0, numpy 1.26.4, psutil 7.2.2, ffmpeg 8.1.1 (binary)

## Per-stage results

CPU% is summed across the whole process tree (harness + ffmpeg/yt-dlp children),
so values above 100% indicate multi-core usage. Sampling interval: 0.2 s.

| Stage | Wall (s) | CPU avg % | CPU peak % | RSS avg (MB) | RSS peak (MB) | Samples |
|-------|---------:|----------:|-----------:|-------------:|--------------:|--------:|
| acquisition (captions) | 1.085 | 11.4 | 28.7 | 249.1 | 253.4 | 5 |
| video_download (yt-dlp) | 2.245 | 6.4 | 7.7 | 309.8 | 319.3 | 10 |
| visual_extract (ffmpeg 2fps) | 4.107 | 5.5 | 15.8 | 373.8 | 384.8 | 16 |
| visual_dedupe (hist/SSIM) | 165.294 | 101.7 | 149.8 | 316.6 | 360.6 | 752 |
| ocr (PaddleOCR ko) | 71.110 | 242.3 | 698.9 | 547.0 | 832.8 | 152 |
| vad | 0.000 | n/a | n/a | n/a | n/a | 0 |
| synthesis | 0.002 | n/a | n/a | n/a | n/a | 0 |
| coverage | 0.002 | n/a | n/a | n/a | n/a | 0 |
| completeness_hook | 0.085 | n/a | n/a | n/a | n/a | 0 |

Total wall time (stages, excluding dependency install): ~244 s for a ~367 s
video on the captions path.

### Observations

- **`visual_dedupe` is the dominant cost (165 s, ~1 core saturated).** It runs
  histogram + SSIM comparisons over 734 raw 2fps keyframes. This is the primary
  optimization target (e.g. coarser sampling, downscaled SSIM, or vectorization).
- **`ocr` is second (71 s) and is the most multi-core stage** (CPU avg 242%,
  peak 699%, RSS peak ~833 MB) — PaddleOCR over the 20 deduped slide frames,
  including first-run model download for the Korean recognizer.
- **acquisition/download/extract are negligible** when captions exist (no STT).
  If captions were absent, STT (faster-whisper medium, int8, CPU) would dominate
  instead and is expected to scale with audio length.
- `vad`/`synthesis`/`coverage`/hook are effectively free (deterministic).

## Pipeline outputs

- `transcript.md`: real, 117 caption cues (Korean), non-empty.
- 734 raw keyframes extracted -> 20 deduped slide frames, **all 20 OCR'd with
  Korean text** (`slide_frames_with_text: 20/20`, `ocr_engine: paddleocr`).
- `summary.md`: written, ~16.8 KB.

## Completeness gate result

`completeness_hook` returned **exit 2** (gate blocked). `coverage.json`:

- `gap_check.pass`: true
- `scene_coverage.pass`: true (20/20 slide frames carry OCR text)
- `artifacts.transcript_nonempty`: true
- `artifacts.summary_nonempty`: **false** -> `artifacts.pass: false` ->
  `overall_pass: false`

Root cause is the product's stage ordering: `cli._default_processor` (mirrored by
this harness) calls `build_coverage(...)` and then writes `summary.md`
afterwards, so the coverage record's `summary_nonempty` check observes the file
before it is written. `summary.md` itself is produced correctly (~16.8 KB). This
is **existing product behavior**; per this work's scope (no `lectural/` logic
changes) it was measured and reported, not modified. It is a recommended
follow-up fix (write `summary.md` before `build_coverage`, or have coverage take
the rendered summary length directly).

## Reproduction notes

- `psutil` is injected via `uv run --with psutil`; it is intentionally not a
  project dependency.
- `numpy==1.26.4` is pinned because `paddlepaddle==2.6.2` is built against the
  numpy 1.x ABI; numpy 2.x triggers `module compiled against ABI version ...`.
- `paddleocr==2.7.3` caps `opencv-python<=4.6.0.66`; let the resolver pick it.
- If neither captions nor an OCR engine are available, the harness records a
  `status: "blocked"` artifact and exits non-zero instead of fabricating metrics.
