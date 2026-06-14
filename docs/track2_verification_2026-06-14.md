# Track-2 Pipeline Quality — Final Verification (2026-06-14)

Verification of the Track-2 work units (WU-1..WU-8) for LecturAL pipeline quality.
All commands were run on Windows / CPython 3.10.

## Offline verification

| Check | Command | Result |
|-------|---------|--------|
| Full offline test suite | `uv run --with pytest --with numpy pytest -q` | 178 passed |
| Lock consistency | `uv lock --check` | Resolved 93 packages (consistent) |
| Runtime imports (`[run]`) | `uv run --extra run python -c "import cv2,numpy; preflight(require_ocr=True)"` | numpy 1.26.4, cv2 4.6.0; numpy/paddleocr/paddle/cv2 available |
| Summary/outline/transcript anchors | direct `render_summary_md`/`render_outline_md`/`render_transcript_md` probe | summary owns `ENRICH_MARKER`/`COVERAGE_ANCHOR`/`TO-ENRICH` and no bracketed timestamps; outline owns `TOC_ANCHOR`, `[HH:MM:SS]`, slide links, transcript bullets |
| Skill parity | sha256 of `skills/lectural/SKILL.md` vs `.claude/skills/lectural/SKILL.md` | identical |

## Real-video before/after

Source: `https://www.youtube.com/watch?v=19vYXnpDIyg` (duration 06:07 / 367s).

- Before: `output/perf-smoke/19vYXnpDIyg/` (pre-Track-2 baseline).
- After: `output/track2-after/96강-강박장애-손에-피가날-정도로-씻어도-불안한-이유/`
  - Command: `uv run --extra run lectural "https://www.youtube.com/watch?v=19vYXnpDIyg" --out ./output/track2-after`

| Aspect | Before | After |
|--------|--------|-------|
| Output folder | `19vYXnpDIyg` (video id) | `96강-강박장애-손에-피가날-정도로-씻어도-불안한-이유` (title slug) |
| Duration in coverage/summary | `00:00:00` | `367.0s` / `00:06:07` |
| TOC / section timestamps | all `00:00:00` | real values incl. section `[00:03:16]`, `[00:04:48]` |
| Slides in `synthesis_input.json` | 20 (many duplicates of the same slide) | 4 distinct slides (pHash dedup, threshold 12, ≥2-frame persistence) |
| `frames/` contents | 734 raw frames | 4 final slide images, no `frames/raw/` (default cleanup) |
| OCR engine | paddleocr (garbled text) | paddleocr (ROI crop + upscale + binarize preprocessing; human-readable Korean) |
| Summary | baseline skeleton only | prose `## 핵심 요약` + `## 구간별 요약` + `## TO-ENRICH` cue |
| CLI exit code | n/a (gate false-failed previously) | `0` |
| Stop hook | n/a | `0` (`완전성 게이트 통과: 1개 run 모두 완전`) |

## Two-layer completeness gate

- Layer 1 (primary, agent-neutral): `lectural` CLI exit code = `0` on the real run.
- Layer 2 (additional, Claude-specific): `scripts/completeness_hook.py` exit `0`, independently validating runstate, `coverage.json`, `summary.md` anchors, and `outline.md` TOC/timestamps/transcript bullets/slide links. The hook does not call or wrap the CLI.

## Regression fixed during verification

The first real-video run exited `2` with `ValueError: Unable to read image for pHash` because `cv2.imread` returns `None` for non-ASCII (Korean) title-slug paths on Windows. Fixed in commit `6321dad` by reading image bytes and decoding via `cv2.imdecode` (`_cv2_imread_unicode`), with a regression test writing a PNG under a Korean directory. Re-run: CLI exit `0`, hook exit `0`.
