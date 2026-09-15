# AGENTS.md

## Purpose
Turn YouTube or local lecture media into complete notes; lecture/slide content is the sweet spot.

## Accepted inputs and runtime
The CLI accepts one or more YouTube URLs/IDs or existing local `.mp4`, `.webm`, `.mkv`, and `.wav` files. Inputs are classified independently and processed sequentially, so batches may mix source kinds. Local files are read in place and are never copied or modified. Local sources always use STT and never use captions or yt-dlp. Video sources retain deduplicated scene frames; `--skip-ocr` keeps and links those frames while disabling only OCR and its slide-text predicate. `--keep-frames` independently archives extra raw samples.

`ffmpeg` is required for STT/VAD and local-video audio extraction. `yt-dlp` is required only for YouTube metadata/media acquisition. Python runtime dependencies are installed by the active uv/uvx environment.

## Install & preflight
Before the first run in a checkout or plugin installation, run:

```bash
lectural doctor --fix
```

Interpret the exit code exactly:

- `0`: proceed with the requested LecturAL run.
- `2`: surface the first missing/incompatible item and its one-line hint to the user, then stop.
- `1`: report the internal/unfixable doctor output, then stop.

## Run

```bash
lectural "https://youtu.be/<VIDEO_ID>" --out ./output
lectural ./recording.mp4 --skip-ocr --out ./output
lectural ./audio.wav --out ./output
```

## Command-driven host-agent enrichment
After a `/lectural:notes` run exits successfully, enrich the prose of `notes.md` in the `미보강` sections by following `skills/lectural/references/summary_prompt.md` and reading only local run artifacts (`synthesis_input.json`, `transcript.md`, and frames when needed). Branch citation generation only on `synthesis_input.json.video.input_source.citation.kind`: YouTube uses `https://youtu.be/<VID>?t=<sec>`, while local media uses exact relative `transcript.md#tHHMMSS[-n]` anchors and never `youtu.be`. Preserve `NOTES_ENRICH_MARKER`, the seven section anchors, citation links, transcript anchors, frame links, and the `정리 커버리지` footer. Bare CLI runs remain deterministic low-level artifacts and do not call an external LLM.

## Completeness gate (HARD RULE)
Treat any non-zero `lectural` exit code as a hard failure. Do NOT mark the task done on a non-zero exit. `--skip-ocr` does not relax speech coverage, video timeline coverage, artifact presence, notes structure, enrichment, citation validity, or CLI exit behavior. Claude Code additionally has a Stop hook, but Codex must rely on the CLI exit code.

## Pointers
See `README.md`, the `commands/` slash commands, and `skills/lectural/references/`.

## Operations

- Branch, commit, and PR conventions: see `CONTRIBUTING.md`.
- Pull requests (HARD RULE): follow `.github/PULL_REQUEST_TEMPLATE.md` exactly (Summary / Changes / Validation / Checklist / Related). When opening a PR non-interactively (`gh` or the API), the web template is NOT auto-injected, so build the PR body from `.github/PULL_REQUEST_TEMPLATE.md` as the starting scaffold and fill every section. Merge only with maintainer approval.
- Release procedure: see `RELEASE.md`.
- Agent audit policy: commit the durable audit trail `.gjc/ultragoal` and `.gjc/specs`; ignore `.gjc/state` and `.gjc/plans` (the shared ralplan run-id dir is not cleanly isolable, so it stays out of the committed audit until a per-run-id scheme is introduced).
- Gate-run expectation: offline suite green with `uv run --with pytest --with numpy pytest -q` and `lectural doctor` reporting ready.
