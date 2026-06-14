# AGENTS.md

## Purpose
Turn a YouTube video into complete notes; lecture/slide content is the sweet spot.

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
uvx --from ".[run]" lectural "<url>"
```

## Skill-driven host-agent enrichment
After a skill-driven `lectural` run exits successfully, enrich the prose of
`notes.md` in the `미보강` sections by following
`skills/lectural/references/summary_prompt.md` and reading only
`synthesis_input.json`. Preserve `NOTES_ENRICH_MARKER`, the seven section
anchors, citation deeplinks, transcript anchors, and the `정리 커버리지` footer.
Bare CLI runs remain deterministic low-level artifacts and do not call an
external LLM.

## Completeness gate (HARD RULE)
Treat any non-zero `lectural` exit code as a hard failure. Do NOT mark the task done on a non-zero exit. Claude Code additionally has a Stop hook, but Codex must rely on the CLI exit code.

## Pointers
See `README.md` and `skills/lectural/SKILL.md`.

## Operations

- Branch, commit, and PR conventions: see `CONTRIBUTING.md`.
- Release procedure: see `RELEASE.md`.
- Agent audit policy: commit the durable audit trail `.gjc/ultragoal` and `.gjc/specs`; ignore `.gjc/state` and `.gjc/plans` (the shared ralplan run-id dir is not cleanly isolable, so it stays out of the committed audit until a per-run-id scheme is introduced).
- Gate-run expectation: offline suite green with `uv run --with pytest --with numpy pytest -q` and `lectural doctor` reporting ready.
