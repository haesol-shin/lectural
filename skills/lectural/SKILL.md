---
name: "lectural"
description: "Use this skill when the user wants trustworthy, timestamped evidence from a video, audio, or YouTube source (transcript segments, frames, or OCR), wants to check a bundle, or wants lecture notes."
---

# LecturAL

Map the user's request to the public LecturAL CLI and contracts. Do not interpret media yourself. Read the [CLI and evidence contract](../../docs/contracts/cli.md); never read internal or undocumented files.

## Extract evidence

1. Preflight with `lectural doctor`. A non-zero exit is a failure: report it and stop.
2. Run `lectural extract <source> --out <new-dir> --json`. The output directory must not already exist.
3. Read `<new-dir>/evidence.json`. Cite transcript evidence by `transcript.segments[].id` and its `start`/`end`; cite frame evidence by `frames[].id` and its `start` timestamp. Use the recorded values exactly; never fabricate timestamps.

## Check a bundle

- Use `lectural inspect <bundle>` for a readable inventory.
- Use `lectural verify <bundle> [--source <src>] --json` to check structural and completeness trust. This is not fact-checking.

## Find where something is explained

Until a `query` command exists, search `transcript.segments[].text` and `frames[].ocr.text` in `evidence.json`. Return matching segment/frame IDs and recorded timestamps, plus the neighboring transcript segments in time order. Do not answer beyond the evidence.

## Generate lecture notes

Run `lectural notes <source-or-bundle> --out <root>`. After it succeeds, enrich notes only by following [`references/summary_prompt.md`](references/summary_prompt.md); do not copy or replace that contract.

## Hard rules

- Treat every non-zero command exit as failure: report it and stop.
- `extract --out` must name a new directory.
- Never invent IDs, timestamps, OCR, transcript content, or conclusions not supported by the evidence.
