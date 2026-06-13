---
name: lectural
description: >-
  Use when the user provides a YouTube lecture URL (or several) and wants COMPLETE
  study notes — every spoken word, every on-screen text, and every slide/scene —
  turned into markdown. Triggers on requests like "summarize this lecture",
  "transcribe and summarize this lecture", or any YouTube link framed as study
  material. Produces a raw transcript plus a structured summary and refuses to
  claim "done" until a completeness hook confirms nothing was missed.
argument-hint: <youtube-url> [more-urls...] [--force-stt] [--model medium]
---

# LecturAL — Complete YouTube Lecture Notes

Core contract: capture every utterance, every on-screen text, and every scene
without arbitrary summarization or skipping. Completeness is enforced by a Stop
hook (below), not by author assertion.

## How it works (Option A-prime · zero external tokens)

A deterministic Python core builds the raw artifacts WITHOUT any external LLM;
you (the host agent) only optionally *enrich* the summary. External API token
cost is zero.

1. **Acquire**: captions first (yt-dlp / youtube-transcript-api). If captions are
   missing or `--force-stt` is set, download audio only and transcribe with
   faster-whisper (medium, int8, CPU).
2. **Visual**: ffmpeg keyframe/scene extraction (2fps) -> histogram/SSIM dedup ->
   PaddleOCR (Korean and English, Tesseract fallback) for slide text. Incremental
   slides are kept separate.
3. **Synthesize**: `transcript.md` (raw, timestamped) + `summary.md` (table of
   contents + coverage summary + per-section timestamps and slide links) +
   `synthesis_input.json` + `coverage.json`.
4. **Completeness**: check speech gaps, scene coverage, and artifact presence via
   `coverage.json`.

## Run

First confirm external dependencies (clear install hints print if anything is
missing):

```bash
python -c "from lectural.deps import preflight; [print(s) for s in preflight()]"
```

Single video or sequential batch:

```bash
# Install: uv pip install -e ".[run]"   (ffmpeg and yt-dlp must be on PATH)
lectural "https://youtu.be/<id>"
lectural "<url1>" "<url2>" --out ./output         # process several, sequentially
lectural "<url>" --force-stt --model medium       # ignore captions, force STT
```

Artifacts: under `./output/<video-title>/` -> `transcript.md`, `summary.md`,
`frames/`, `coverage.json`, `synthesis_input.json`.

## Optional: summary enrichment (still zero tokens)

`summary.md` is already a deterministic baseline. If richer prose is wanted, read
only `synthesis_input.json` (text only, no images) and enrich the prose. You MUST
preserve the required anchors defined in `lectural.synthesis`: `ENRICH_MARKER`,
`COVERAGE_ANCHOR`, `TOC_ANCHOR`, the `SECTION_PREFIX` section headings, the
per-section timestamps, and the `frames/` links. Do not put raw images into
context.

## Completeness gate (must pass)

The plugin ships a Stop hook (`hooks/hooks.json`) that runs
`python "${CLAUDE_PLUGIN_ROOT}/scripts/completeness_hook.py"`. The hook inspects
every run registered in this session — its `coverage.json` and `summary.md`
anchors — and blocks "done" with exit 2 if any run fails. When the gate blocks,
do not work around it with arbitrary summarization; resolve the root cause
(caption gaps, uncovered scenes, empty artifacts). On Windows without `python`,
use `py -3` for the same script.

## Scope

v1: single + sequential batch. **Deferred** (excluded): parallel batch,
non-developer UI, GPU path, speaker diarization/translation.

See `references/pipeline.md` and `docs/synthesis_contract.md` for details.
