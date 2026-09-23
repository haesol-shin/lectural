---
description: Turn a YouTube video, local video, local audio file, or evidence bundle into deterministic evidence for video-based work: complete markdown notes.
argument-hint: <source-or-bundle> [more-inputs...] [--force-stt] [--model medium] [--out ./output] [--skip-ocr] [--keep-frames]
---

Run the LecturAL pipeline explicitly for: $ARGUMENTS

This command performs heavy work (media download, optional long CPU transcription, OCR). Follow the procedure exactly and never summarize around a failure.

Always invoke the CLI as `uv run --project "${CLAUDE_PLUGIN_ROOT}" --extra run lectural ...`. This uses the plugin's project and its `uv.lock`, so the Python run dependencies (including the pinned OpenCV/OCR stack) resolve consistently regardless of the current shell/venv. Do NOT invoke an unqualified `lectural` executable, `python -m lectural.cli`, or `uvx --from "...[run]"` — the session Python may lack the extras, and `uvx` ignores the lockfile and can pull an incompatible OpenCV. `ffmpeg` must still be on PATH.

1. If `$ARGUMENTS` contains no YouTube URL/ID, existing local `.mp4`/`.webm`/`.mkv`/`.wav` file, or evidence bundle directory with `evidence.json`, ask the user for an input and stop until they provide one. Do not run anything yet.
2. Preflight. Run `uv run --project "${CLAUDE_PLUGIN_ROOT}" --extra run lectural doctor --fix` and interpret the exit code:
   - `0`: ready, continue.
   - `2`: surface the first missing/incompatible item and its one-line hint, tell the user to run `/lectural:setup`, then stop.
   - `1`: report the doctor output, then stop.
3. Run the pipeline: `uv run --project "${CLAUDE_PLUGIN_ROOT}" --extra run lectural notes $ARGUMENTS`. Treat any non-zero exit code as a hard failure; report the completeness failure and stop. Do not work around it with arbitrary summarization.
4. On success, enrich every generated `notes.md` by following `${CLAUDE_PLUGIN_ROOT}/skills/lectural/references/summary_prompt.md` exactly, reading only local run artifacts (`synthesis_input.json`, `transcript.md`, and `frames/*.png` when OCR text is garbled). Use zero external LLM tokens. Remove every unenriched marker and preserve the line-1 notes marker, the seven section anchors and their order, every `<a id="sec-N">` anchor, the slide `<img>` tags, the coverage footer, and the source-appropriate citations (`youtu.be` for YouTube, `transcript.md#t…` for local).
5. Report each output folder and confirm the completeness gate passed.
