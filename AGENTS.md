# AGENTS.md

## Purpose
Turn a YouTube video into complete notes; lecture/slide content is the sweet spot.

## Install & preflight
Run:

```bash
python -c "from lectural.deps import preflight; [print(s) for s in preflight()]"
```

Install the per-OS dependencies named by preflight, then install LecturAL:

```bash
uv pip install -e ".[run]"
```

`ffmpeg` and `yt-dlp` must be on PATH.

## Run

```bash
lectural "<url>" --out ./output
uvx --from ".[run]" lectural "<url>"
```

## Skill-driven host-agent enrichment
After a skill-driven `lectural` run exits successfully, enrich only the prose in
`summary.md` from `synthesis_input.json`. Preserve `ENRICH_MARKER`,
`COVERAGE_ANCHOR`, and `TO-ENRICH`, and leave `outline.md` structural anchors,
TOC links, timestamps, slide links, and transcript bullets intact. Bare CLI runs
remain deterministic low-level artifacts and do not call an external LLM.

## Completeness gate (HARD RULE)
Treat any non-zero `lectural` exit code as a hard failure. Do NOT mark the task done on a non-zero exit. Claude Code additionally has a Stop hook, but Codex must rely on the CLI exit code.

## Pointers
See `README.md` and `skills/lectural/SKILL.md`.
