# LecturAL pipeline reference

Module map (all heavy deps lazy-imported; deterministic logic is unit-tested offline):

| Module | Responsibility | AC |
|--------|----------------|----|
| `lectural/doctor.py` | component manifest validation for runtime, plugin files, and hooks | distribution |
| `lectural/deps.py` | ffmpeg/yt-dlp/Python dependency preflight with install hints | scaffold |
| `lectural/acquisition.py` | captions-first (VTT/json3 parsers) + audio download | AC-1,2,3 |
| `lectural/speech.py` | faster-whisper medium int8 CPU transcription | AC-3,4 |
| `lectural/vad.py` | silence mask + speech-gap metric (`silencedetect` parser) | AC-9 |
| `lectural/visual.py` | ffmpeg keyframe/scene extraction + histogram/SSIM dedup | AC-5 |
| `lectural/ocr.py` | PaddleOCR primary + Tesseract fallback, incremental re-split | AC-6 |
| `lectural/synthesis.py` | synthesis_input.json + transcript.md + notes.md skeleton | AC-7,8,12 |
| `lectural/coverage.py` | coverage.json (gap/scene/artifact) + raw-samples contract | AC-13 |
| `lectural/runstate.py` | active-run pointer for the Stop hook | AC-2 |
| `lectural/cli.py` | extract, notes, inspect, verify, and doctor subcommands; sequential batch, orchestration | AC-1,2,10,11 |
| `scripts/completeness_hook.py` | Stop hook: block done until coverage passes | AC-13 |

## Doctor component manifest

Run `lectural doctor --fix` before a runtime-only CLI run. The doctor checks Python core import/version, runtime Python imports, and `ffmpeg`/`yt-dlp` on PATH. It does not require plugin files by default.

For a checkout or Claude plugin installation, use `lectural doctor --fix --plugin` to also validate `AGENTS.md`, the agent skill and references, hooks, plugin manifests, marketplace metadata, and hook script path.

Doctor exit codes are `0` ready, `2` user action needed, and `1` internal or unfixable state. `--fix` is bounded and safe: it may attempt `uv tool install yt-dlp`, may use obvious Windows/macOS package managers for ffmpeg, and otherwise reports a one-line hint.

## Key invariants

- **No external LLM tokens.** Raw transcript and OCR are deterministic. The `notes.md` skeleton is deterministic too; host-agent enrichment fills the `NOTES_UNENRICHED_MARKER` prose sections.
- **Capture ALL speech.** `transcript.md` iterates every segment; `notes.md` assigns every in-duration segment to exactly one section (no drops), with an intro section for pre-first-slide speech; host-agent enrichment fills the `NOTES_UNENRICHED_MARKER` prose sections.
- **Honest scene coverage.** `scene_coverage` is fed RAW sampled keyframe times (via `coverage_inputs_from_extraction`); a capped carry-forward passes static slides but FAILs a keyframe-less stall.
- **Speech gap, not silence.** `gap_check` measures untranscribed SPEECH only (VAD/silence mask), gated at `MAX_GAP_SEC`.

## Running offline tests

```bash
uv run --with pytest --with numpy pytest -q
```

Tests for STT/acquisition/visual that need binaries/models are marked `smoke` and excluded by default (see `pyproject.toml [tool.pytest.ini_options]`).
