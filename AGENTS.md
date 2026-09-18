# AGENTS.md

## Purpose
Turn a video (YouTube or local) into deterministic evidence for video-based work: markdown notes (`/lectural:notes`) or a versioned JSON contract (`lectural extract --json`). Best on lecture and slide-style video.

## Install & preflight
Before the first run in a checkout or plugin installation, run:

```bash
lectural doctor --fix
```

Interpret the exit code exactly:

- `0`: proceed with the requested LecturAL run.
- `2`: surface the first missing/incompatible item and its one-line hint to the user, then stop.
- `1`: report the internal/unfixable doctor output, then stop.

`ffmpeg` must be on PATH. Python runtime deps are installed by the active uv/uvx environment; `doctor --fix` only makes safe bounded attempts for `yt-dlp` and obvious ffmpeg package-manager paths.

## Run

```bash
lectural "<url>" --out ./output
lectural ./recording.mp4 --skip-ocr --out ./output
uvx --from ".[run]" lectural "<url>"
```

## Command-driven host-agent enrichment
After a `/lectural:notes` run exits successfully, enrich the prose of `notes.md` in the `미보강` sections by following `skills/lectural/references/summary_prompt.md` and reading only `synthesis_input.json`. Preserve `NOTES_ENRICH_MARKER`, the seven section anchors, citation deeplinks (`youtu.be` or `transcript.md#t…` per `input_source.citation.kind`), transcript anchors, and the `정리 커버리지` footer. Bare CLI runs remain deterministic low-level artifacts and do not call an external LLM.

## Completeness gate (HARD RULE)
Treat any non-zero `lectural` exit code as a hard failure. Do NOT mark the task done on a non-zero exit. `--skip-ocr` does not relax speech, timeline, artifact, or citation gates. Claude Code additionally has a Stop hook, but Codex must rely on the CLI exit code.

## Pointers
See `README.md`, the `commands/` slash commands, and `skills/lectural/references/`.

## Operations

- Branch, commit, and PR conventions: see `CONTRIBUTING.md`.
- Pull requests (HARD RULE): follow `.github/PULL_REQUEST_TEMPLATE.md` exactly (Summary / Changes / Validation / Checklist / Related). When opening a PR non-interactively (`gh` or the API), the web template is NOT auto-injected, so build the PR body from `.github/PULL_REQUEST_TEMPLATE.md` as the starting scaffold and fill every section. Merge only with maintainer approval.
- Release procedure: see `RELEASE.md`.
- Gate-run expectation: offline suite green with `uv run --with pytest --with numpy pytest -q` and `lectural doctor` reporting ready.
