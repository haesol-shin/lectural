---
description: "[lectural] Set up and verify the LecturAL runtime: install Python run deps, then run lectural doctor --fix for ffmpeg/yt-dlp, and report readiness. Run this once after installing the plugin."
---

Set up the LecturAL runtime for this plugin install. Do NOT run any lecture pipeline here.

1. Install the package and Python runtime dependencies (editable), from the plugin root:
   `uv pip install -e "${CLAUDE_PLUGIN_ROOT}[run]"`
   This installs the `lectural` CLI plus run deps (yt-dlp, faster-whisper, opencv, paddleocr, ...).
2. Run `lectural doctor --fix` and read the exit code. It installs/verifies `yt-dlp`, attempts `ffmpeg` best-effort, and checks plugin/skill/hook wiring and mirror parity.
3. Interpret the doctor exit code:
   - `0`: report that all components are ready; the user can run `/lectural:notes <url>`.
   - `2` (user action needed): for each missing or incompatible item give the exact fix, then re-run `lectural doctor --fix` and report whether it now reaches `0`:
     - `ffmpeg` (system binary, must be on PATH): Windows `winget install --id Gyan.FFmpeg -e`; Debian/Ubuntu `sudo apt-get install ffmpeg`; Fedora `sudo dnf install ffmpeg`; macOS `brew install ffmpeg`.
     - `yt-dlp` on PATH: `uv tool install yt-dlp`.
   - `1` (internal or unfixable): report the full doctor output and stop; do not guess.

Use `lectural doctor --json` when a structured manifest (`schema_version`, `items`, `overall_status`, `exit_code`) is clearer.
