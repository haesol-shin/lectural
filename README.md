# LecturAL

[![PyPI](https://img.shields.io/pypi/v/lectural)](https://pypi.org/project/lectural/) [![Python](https://img.shields.io/pypi/pyversions/lectural)](https://pypi.org/project/lectural/) [![CI](https://github.com/haesol-shin/lectural/actions/workflows/ci.yml/badge.svg)](https://github.com/haesol-shin/lectural/actions/workflows/ci.yml) [![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv) [![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/haesol-shin/lectural/blob/main/LICENSE)

LecturAL turns video and audio into complete, deterministic, timestamp-addressable evidence that agents can verify and reuse.

Give it a YouTube URL or a local `.mp4`, `.webm`, `.mkv`, or `.wav` file. It writes an evidence bundle: timestamped transcript segments, selected scene frames with OCR annotations, and a completeness verdict. Agents and scripts cite that evidence by ID and timestamp instead of re-watching the media. Lecture and slide-style video works especially well because its spoken explanations and visible text can both be captured. Study notes are one consumer of the evidence, not the product itself.

## Install

```bash
pip install "lectural[run]"
# or as an isolated tool
uv tool install "lectural[run]"
# or run without installing
uvx --from "lectural[run]" lectural --help
```

The commands below use `lectural` from an active pip environment or a uv tool install. For one-shot `uvx`, replace that prefix with `uvx --from "lectural[run]" lectural`.

Python 3.10–3.12 is required. The `[run]` extra pulls in speech-to-text (faster-whisper), OCR, and YouTube access (yt-dlp). LecturAL also needs `ffmpeg` on `PATH`:

Example package-manager commands for `ffmpeg` (package availability varies by platform; the Windows command installs a third-party build):

| OS | Command |
|---|---|
| Windows | `winget install --id Gyan.FFmpeg -e` |
| macOS | `brew install ffmpeg` |
| Debian/Ubuntu | `sudo apt-get install ffmpeg` |

Run a preflight before your first extraction. `--fix` tries `uv tool install yt-dlp` if that binary is missing and may install `ffmpeg` through `winget` or Homebrew; on Debian/Ubuntu it prints an installation hint rather than requesting administrator privileges. Follow the [doctor exit codes](https://github.com/haesol-shin/lectural/blob/main/docs/contracts/cli.md#doctor) if anything remains missing:

```bash
lectural doctor --fix
```

## Quick start

```bash
lectural extract ./lecture.mp4 --out ./lecture-evidence --json
lectural inspect ./lecture-evidence
lectural verify ./lecture-evidence --source ./lecture.mp4
```

`extract` builds the bundle in a new directory; if `./lecture-evidence` already exists, choose a fresh name such as `./lecture-evidence-2` and use that name for the following commands. Never delete an existing bundle just to rerun extraction. `inspect` shows a readable inventory. `verify` checks structure, artifact containment, frame hashes, identifiers, timestamps, recomputed completeness, and, with `--source`, that the bundle came from that media; exit `0` means valid. It is not fact-checking.

## Commands at a glance

| Command | Purpose |
|---|---|
| `lectural extract <source> --out <new-dir> [--skip-ocr] [--json]` | Build an evidence bundle from one source |
| `lectural inspect <bundle> [--json]` | Summarize a bundle without modifying it |
| `lectural verify <bundle> [--source <file-or-URL>] [--json]` | Check that a bundle is complete and intact |
| `lectural notes <source-or-bundle>... [--out <root>]` | Generate study notes, extracting first when given a source |
| `lectural doctor [--fix] [--plugin] [--json]` | Check the runtime; `--plugin` also checks agent-plugin files |
| `lectural --version [--json]` | Report the tool and supported contract versions |

Every command exits non-zero on failure. With `--json`, normal responses and processable failures print one JSON document to stdout; argument-parser errors may go to stderr.

## Output

```text
lecture-evidence/
├── evidence.json   # contract-versioned evidence manifest
├── transcript.md   # transcript with stable #tHHMMSS anchors
└── frames/         # retained scene frames (video sources)
```

`audio.wav` may also be generated when video audio is acquired for transcription, but it is not a promised evidence artifact.

## Optional study notes

```bash
lectural notes ./lecture-evidence
```

`lectural notes` adds `notes.md` (seven-section study notes with citations back to the source), `synthesis_input.json`, and `coverage.json` (the completeness gate). Notes are currently generated in Korean; the evidence bundle is language-neutral.

## What you get

`lectural extract` writes `evidence.json` (abridged):

```json
{
  "contract_version": 2,
  "source": {"id": "sha256:eb0162565065…", "kind": "local_video", "duration_sec": 20.352},
  "speech": {"source": "stt", "language": "en", "model": "medium", "fallback": {"code": "local_source"}},
  "transcript": {
    "segments": [{"id": "s0001", "start": 0.0, "end": 5.28, "text": "Welcome to lecture 4 on optimization."}]
  },
  "frames": [
    {"id": "f0001", "start": 0.0, "sha256": "2c57d8bd8e89…", "ocr": {"status": "text", "text": "Lecture 4: Optimization …"}}
  ],
  "extraction": {"status": "pass"}
}
```

The full manifest also records speech and visual completeness, timestamp integrity, and resource use. See the versioned [CLI and evidence contract](https://github.com/haesol-shin/lectural/blob/main/docs/contracts/cli.md) and its JSON Schemas for the exact fields, options, and exit codes.

## Use with coding agents

LecturAL ships one shared skill, [`skills/lectural/SKILL.md`](https://github.com/haesol-shin/lectural/blob/main/skills/lectural/SKILL.md), that routes requests such as "extract evidence from this video" or "find where X is explained" to the CLI. Claude Code installs it as a plugin with `/lectural:notes` and a completeness hook; Codex and other agents load the same skill from their skills directory. Setup for each host is in [Using LecturAL with coding agents](https://github.com/haesol-shin/lectural/blob/main/docs/agents.md).

## FAQ

**No captions?** YouTube captions are used when they are usable; otherwise LecturAL transcribes the audio. Local files are always transcribed. `evidence.json` records which path ran in `speech.source` and `speech.fallback.code`.

**Does a local run need yt-dlp?** No; only YouTube sources use it. The preflight still checks all runtime tools, so `doctor --fix` may offer to install it for future YouTube runs.

**What does `--skip-ocr` do?** Keeps the scene frames and skips OCR; the OCR state is recorded as `skipped`.

**Long videos?** CPU transcription time grows with length. `lectural notes ./lecture.mp4 --model small` trades accuracy for speed, and `resources` in `evidence.json` shows where the time went.

**Empty OCR text on some frames?** Expected: frames that show only the speaker have no text. Frames are kept as visual evidence regardless of OCR.

## License

[MIT](https://github.com/haesol-shin/lectural/blob/main/LICENSE)
