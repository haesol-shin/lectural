# LecturAL pipeline reference

Module map (all heavy deps lazy-imported; deterministic logic is unit-tested
offline):

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
| `lectural/cli.py` | doctor dispatch, arg parsing, sequential batch, orchestration | AC-1,2,10,11 |
| `scripts/completeness_hook.py` | Stop hook: block done until coverage passes | AC-13 |

## Doctor component manifest

Run `lectural doctor --fix` before the first lecture run in a checkout or Claude
plugin installation. The doctor validates:

- Python core import/version for `lectural` and runtime Python imports.
- External binaries: `ffmpeg` and `yt-dlp` on PATH.
- Agent-side files: `AGENTS.md`, `summary_prompt.md`, and `hooks/hooks.json`.
- Claude plugin manifests: plugin name, marketplace plugin entry, exact
  marketplace `source` value `./`, and hook path existence.

Doctor exit codes are `0` ready, `2` user action needed, and `1` internal or
unfixable state. `--fix` is bounded and safe: it may attempt `uv tool install
yt-dlp`, may use obvious Windows/macOS package managers for ffmpeg, and otherwise
reports a one-line hint.

## Key invariants

- **No external LLM tokens.** Raw transcript and OCR are deterministic. The
  `notes.md` skeleton is deterministic too; host-agent enrichment fills the
  `NOTES_UNENRICHED_MARKER` prose sections.
- **Capture ALL speech.** `transcript.md` iterates every segment; `notes.md`
  assigns every in-duration segment to exactly one section (no drops), with an
  intro section for pre-first-slide speech; host-agent enrichment fills the
  `NOTES_UNENRICHED_MARKER` prose sections.
- **Honest scene coverage.** `scene_coverage` is fed RAW sampled keyframe times
  (via `coverage_inputs_from_extraction`); a capped carry-forward passes static
  slides but FAILs a keyframe-less stall.
- **Speech gap, not silence.** `gap_check` measures untranscribed SPEECH only
  (VAD/silence mask), gated at `MAX_GAP_SEC`.

## Running offline tests

```bash
uv run --with pytest --with numpy pytest -q
```

Tests for STT/acquisition/visual that need binaries/models are marked `smoke`
and excluded by default (see `pyproject.toml [tool.pytest.ini_options]`).
