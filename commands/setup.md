---
description: Set up and verify the LecturAL runtime before first use.
---

Set up and verify the LecturAL runtime for this plugin install. Do NOT run any lecture pipeline here.

LecturAL runs through `uv run --project "${CLAUDE_PLUGIN_ROOT}" --extra run`, which uses the plugin's `uv.lock` so the Python run dependencies (including the pinned OpenCV/OCR stack) resolve consistently. You do not need a separate global install. `ffmpeg` is a system binary and must be on PATH. Do not use `uvx --from "...[run]"` (it ignores the lockfile and can pull an incompatible OpenCV).

1. Run the doctor with the lockfile-consistent invocation:
   `uv run --project "${CLAUDE_PLUGIN_ROOT}" --extra run lectural doctor --fix`
   It provisions/verifies the Python run deps (yt-dlp, faster-whisper, opencv, paddleocr, ...), installs/verifies the `yt-dlp` binary, attempts `ffmpeg` best-effort, and checks plugin/hook wiring.
2. Interpret the doctor exit code:
   - `0`: report that all components are ready; the user can run `/lectural:notes <url>`.
   - `2` (user action needed): for each missing or incompatible item give the exact fix, then re-run the doctor and report whether it now reaches `0`:
     - `ffmpeg` (system binary, must be on PATH): Windows `winget install --id Gyan.FFmpeg -e`; Debian/Ubuntu `sudo apt-get install ffmpeg`; Fedora `sudo dnf install ffmpeg`; macOS `brew install ffmpeg`.
     - `yt-dlp` binary on PATH: `uv tool install yt-dlp`.
   - `1` (internal or unfixable): report the full doctor output and stop; do not guess.

Use `uv run --project "${CLAUDE_PLUGIN_ROOT}" --extra run lectural doctor --json` when a structured manifest (`schema_version`, `items`, `overall_status`, `exit_code`) is clearer.
