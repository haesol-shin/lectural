---
description: Turn YouTube or local lecture media into complete study notes.
argument-hint: <source> [more-sources...] [--force-stt] [--model medium] [--out ./output] [--keep-frames] [--skip-ocr]
---

Run the LecturAL pipeline explicitly for: $ARGUMENTS

Accepted sources are YouTube URLs/IDs and existing local `.mp4`, `.webm`, `.mkv`, or `.wav` files. Sources are classified independently and processed sequentially, so a batch may mix YouTube, local video, and local audio. Local files are read in place; they are never copied, renamed, deleted, or modified. Local sources always use STT and never use captions or yt-dlp.

This command performs heavy work (media download or local audio extraction, optional long CPU transcription, and OCR for video). Follow the procedure exactly and never summarize around a failure.

Always invoke the CLI as `uv run --project "${CLAUDE_PLUGIN_ROOT}" --extra run lectural ...`. This uses the plugin's project and its `uv.lock`, so the Python run dependencies (including the pinned OpenCV/OCR stack) resolve consistently regardless of the current shell/venv. Do NOT use a bare `lectural`, `python -m lectural.cli`, or `uvx --from "...[run]"` — the session Python may lack the extras, and `uvx` ignores the lockfile and can pull an incompatible OpenCV. `ffmpeg` must still be on PATH. YouTube inputs additionally require yt-dlp.

1. If `$ARGUMENTS` contains no source, ask the user for a YouTube URL/ID or an existing supported local media file and stop until they provide one. Do not run anything yet.
2. Preflight. Run `uv run --project "${CLAUDE_PLUGIN_ROOT}" --extra run lectural doctor --fix` and interpret the exit code:
   - `0`: ready, continue.
   - `2`: surface the first missing/incompatible item and its one-line hint, tell the user to run `/lectural:setup`, then stop.
   - `1`: report the doctor output, then stop.
3. Run the pipeline: `uv run --project "${CLAUDE_PLUGIN_ROOT}" --extra run lectural $ARGUMENTS`. Treat any non-zero exit code as a hard failure; report the coverage failure and stop. Do not work around it with arbitrary summarization. `--skip-ocr` keeps deduplicated scene frames and their links, skips OCR, and disables only the slide-text OCR predicate; it does not relax speech, visual timeline, artifacts, notes, citations, or exit-code gates. `--keep-frames` still independently archives extra raw samples.
4. On success, enrich every generated `notes.md` by following `${CLAUDE_PLUGIN_ROOT}/skills/lectural/references/summary_prompt.md` exactly, reading only local run artifacts (`synthesis_input.json`, `transcript.md`, and `frames/*.png` when OCR text is garbled). Use zero external LLM tokens. Branch citations only on `synthesis_input.json.video.input_source.citation.kind`: `youtube` preserves `https://youtu.be/<VID>?t=<sec>`, while `transcript` uses exact relative `transcript.md#tHHMMSS[-n]` anchors and never emits `youtu.be`. Remove every unenriched marker and preserve the line-1 notes marker, the seven section anchors and their order, every `<a id="sec-N">` anchor, slide image tags, the coverage footer, and source-appropriate citations.
5. Report each output folder and confirm the completeness gate passed.
