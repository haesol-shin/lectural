---
name: lectural
description: >-
  Use when the user provides a YouTube lecture URL (or several) and wants COMPLETE
  study notes: every spoken word, every on-screen text, and every slide or scene
  turned into markdown. Triggers on requests like "summarize this lecture",
  "transcribe and summarize this lecture", or any YouTube link framed as study
  material. Produces a raw transcript plus structured notes and refuses to claim
  done until completeness checks confirm nothing was missed.
argument-hint: <youtube-url> [more-urls...] [--force-stt] [--model medium]
---

# LecturAL - Complete YouTube Lecture Notes

Core contract: capture every utterance, every on-screen text, and every scene
without arbitrary summarization or skipping. Completeness is enforced first by
the CLI exit code and additionally by the Stop hook, not by author assertion.

## How it works (Option A-prime, zero external tokens)

A deterministic Python core builds the raw artifacts WITHOUT any external LLM.
After the CLI succeeds, the already-running host agent enriches `notes.md` prose
from text artifacts only. External API token cost remains zero.

1. **Acquire**: captions first (yt-dlp / youtube-transcript-api). If captions are
   missing or `--force-stt` is set, download audio only and transcribe with
   faster-whisper (medium, int8, CPU).
2. **Visual**: ffmpeg keyframe and scene extraction (2fps) -> histogram/SSIM
   dedup -> PaddleOCR (Korean and English, Tesseract fallback) for slide text.
3. **Synthesize**: `transcript.md` (raw, timestamped) + `notes.md` (seven-section
   deterministic skeleton with prose enrichment cues) + `synthesis_input.json` +
   `coverage.json`.
4. **Completeness**: check speech gaps, scene coverage, and artifact presence via
   `coverage.json`.

## Preflight before first run

Before the first lecture run in a checkout or plugin installation, run:

```bash
lectural doctor --fix
```

Interpret the doctor exit code exactly:

- `0`: all components are ready; proceed with the lecture run.
- `2`: user action is needed; surface the first missing or incompatible item and
  its hint, then stop.
- `1`: internal or unfixable state; report the doctor output and stop.

Use `lectural doctor --json` when a structured manifest is easier for automation.
The manifest covers the Python package, runtime Python imports, `ffmpeg`,
`yt-dlp`, agent files, Claude plugin manifests, hook wiring, and root/.claude
skill/reference mirror parity.

## Run

Single video or sequential batch:

```bash
lectural "https://youtu.be/<id>"
lectural "<url1>" "<url2>" --out ./output
lectural "<url>" --force-stt --model medium
```

Artifacts are written under `./output/<video-title>/`: `transcript.md`,
`notes.md`, `frames/`, `coverage.json`, and `synthesis_input.json`.

## Required: host-agent notes enrichment (still zero external tokens)

After `lectural` exits successfully, the host agent MUST enrich `notes.md` prose
by following `references/summary_prompt.md` and reading only local run artifacts
(`synthesis_input.json`, `transcript.md`, and frame images when OCR text is
garbled; no external LLM). It MUST enrich the five sections marked by
`NOTES_UNENRICHED_MARKER`: `NOTES_TAKEAWAY_ANCHOR`, `NOTES_FLOW_ANCHOR`,
`NOTES_CONCEPTS_ANCHOR`, `NOTES_DETAIL_ANCHOR`, and `NOTES_QUESTIONS_ANCHOR`.
It MUST preserve `NOTES_ENRICH_MARKER` on line 1, the seven section anchors
(`NOTES_TAKEAWAY_ANCHOR`, `NOTES_TOC_ANCHOR`, `NOTES_FLOW_ANCHOR`,
`NOTES_CONCEPTS_ANCHOR`, `NOTES_DETAIL_ANCHOR`, `NOTES_QUESTIONS_ANCHOR`, and
`NOTES_COVERAGE_ANCHOR`), citation deeplinks, transcript anchors, and slide image
links. Remove the `NOTES_UNENRICHED_MARKER` markers once enrichment is complete.
A bare CLI run remains an honest deterministic skeleton and does not call an
external LLM.

## Completeness gate (must pass)

Completeness is enforced in two layers. Layer 1 (primary, agent-agnostic): the
`lectural` CLI exit code. `cli.main` ANDs every processed run's `overall_pass`
and returns a non-zero exit (`2`) when any run fails its coverage checks (speech
gap, scene coverage, non-empty artifacts). Any agent wrapping the CLI MUST treat
a non-zero exit as a hard failure and must not work around it with arbitrary
summarization. Layer 2 (additional, Claude Code only): the Stop hook
(`scripts/completeness_hook.py`) is a session-final verifier that independently
validates `notes.md` (`NOTES_ENRICH_MARKER` on line 1 + the seven section anchors
+ slide image link when frames exist), runstate, and `coverage.json`; it does not
call or wrap the CLI.

On Windows without `python`, use `py -3` for the hook script.

## Scope

v1: single + sequential batch. Deferred: parallel batch, non-developer UI, GPU
path, speaker diarization, and translation.

See `references/pipeline.md` and `docs/synthesis_contract.md` for details.
