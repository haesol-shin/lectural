---
name: "lectural"
description: "Use this skill when the user wants trustworthy, timestamped evidence from a video, audio, or YouTube source (transcript segments, frames, or OCR), wants to check a bundle, or wants lecture notes."
---

# LecturAL

Map the user's request to the public LecturAL CLI and contracts. Do not interpret media yourself. Read the [CLI and evidence contract](https://github.com/haesol-shin/lectural/blob/main/docs/contracts/cli.md); never read internal or undocumented files.

On hosts other than the Claude Code plugin, install the CLI with the `[run]` extra as in the [README](https://github.com/haesol-shin/lectural/blob/main/README.md#install), then run the `lectural` commands below from `PATH`. The Claude Code plugin supplies its own locked runtime through `/lectural:setup`: replace the leading `lectural` in **every** command below, including `doctor`, with `uv run --project "${CLAUDE_PLUGIN_ROOT}" --directory "${CLAUDE_PLUGIN_ROOT}" --extra run lectural`.

## Extract evidence

1. Preflight with `lectural doctor`. A non-zero exit is a failure: report it and stop.
2. Run `lectural extract <source> --out <new-dir> --json`. Choose a fresh output path if a previous bundle exists; do not overwrite it.
3. Read `<new-dir>/evidence.json` and report the bundle path and extraction status. For content claims, cite transcript evidence by `transcript.segments[].id` and its `start`/`end`, or frame evidence by `frames[].id` and its `start` timestamp. Use the recorded values exactly; never fabricate timestamps.

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
