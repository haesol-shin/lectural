---
description: Turn a YouTube lecture URL into complete study notes.
argument-hint: <youtube-url> [more-urls...] [--force-stt] [--model medium] [--out ./output]
---

Run the LecturAL pipeline explicitly for: $ARGUMENTS

This command performs heavy work (media download, optional long CPU transcription, OCR). Follow the procedure exactly and never summarize around a failure.

Always invoke the CLI as `uv run --project "${CLAUDE_PLUGIN_ROOT}" --extra run lectural ...`. This uses the plugin's project and its `uv.lock`, so the Python run dependencies (including the pinned OpenCV/OCR stack) resolve consistently regardless of the current shell/venv. Do NOT use a bare `lectural`, `python -m lectural.cli`, or `uvx --from "...[run]"` — the session Python may lack the extras, and `uvx` ignores the lockfile and can pull an incompatible OpenCV. `ffmpeg` must still be on PATH.

1. If `$ARGUMENTS` contains no YouTube URL, ask the user for the lecture URL and stop until they provide one. Do not run anything yet.
2. Preflight. Run `uv run --project "${CLAUDE_PLUGIN_ROOT}" --extra run lectural doctor --fix` and interpret the exit code:
   - `0`: ready, continue.
   - `2`: surface the first missing/incompatible item and its one-line hint, tell the user to run `/lectural:setup`, then stop.
   - `1`: report the doctor output, then stop.
3. Run the pipeline: `uv run --project "${CLAUDE_PLUGIN_ROOT}" --extra run lectural $ARGUMENTS`. Treat any non-zero exit code as a hard failure; report the coverage failure and stop. Do not work around it with arbitrary summarization.
4. On success, enrich every generated `notes.md` by following `${CLAUDE_PLUGIN_ROOT}/skills/lectural/references/summary_prompt.md` exactly, reading only local run artifacts (`synthesis_input.json`, `transcript.md`, and `frames/*.png` when OCR text is garbled). Use zero external LLM tokens. Remove every unenriched marker and preserve the line-1 notes marker, the seven section anchors and their order, every `<a id="sec-N">` anchor, the slide `<img>` tags, the coverage footer, and the youtu.be citation deeplinks.
5. Report each output folder and confirm the completeness gate passed.
