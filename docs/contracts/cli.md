# LecturAL extraction CLI contract

- Contract version: `2`
- JSON Schema version: `2`
- Current application version: see `lectural --version --json`

This is the public boundary for consumers such as `lecture-tools`. Consumers must use only this JSON and the paths it returns; they must not import LecturAL modules or read internal run state. Unknown fields may be ignored, but an unknown schema or contract version must fail closed.

## Commands

```console
lectural --version --json
lectural extract <source> --out <new-directory> [--skip-ocr] --json
```

`<source>` is exactly one supported YouTube URL/ID or existing local `.mp4`, `.webm`, `.mkv`, or `.wav` file. The existing bare-source form remains available for notes generation; it runs extraction first and then builds notes from the emitted evidence bundle:

```console
lectural <source> [--out <root>] [--skip-ocr]
```

The `extract` command rejects the requested output path when it already exists, even when it is empty. It creates the path only after source syntax is valid. Every manifest artifact path is absolute and resolves below the new output directory. `extract` writes `evidence.json`, `transcript.md`, and (for video sources) retained frames; it does not write `notes.md`, `synthesis_input.json`, or `coverage.json`. The bare notes run writes those three notes artifacts after extraction. Local source paths are not copied into the public JSON; `source.argument` contains only a filename, kind, and citation kind.

## Common JSON envelope

Both JSON commands return one object with:

```json
{
  "schema_version": 2,
  "contract_version": 2,
  "tool": "lectural",
  "tool_version": "0.2.0",
  "status": "ok",
  "result": {},
  "errors": [],
  "generated_at": "2026-09-18T08:00:00Z"
}
```

Envelope `status` is `ok`, `partial`, or `error`. Error entries contain only a bounded `code` and safe `message`; they never contain an exception, source path, credential, token, cookie, environment value, or internal state path. The evidence manifest itself has no duplicate top-level status: use `result.extraction.status`.

When no extraction manifest could be produced, `result` is a bounded failure result rather than an evidence manifest. Its `source` is null or a minimal safe descriptor; artifact paths are null when output creation did not occur. The failure-result shape is defined by `extract.schema.json`.

Exit codes for `extract` are:

| Code | Meaning |
| ---: | --- |
| `0` | extraction `pass` |
| `1` | extraction `warn` or `fail` after a JSON response was produced |
| `2` | invalid source or output requires user action; JSON response produced |

Argument-parser failures before a command can be identified use argparse's stderr path. Normal responses and processable failures keep stdout as a single JSON document.

## Version negotiation

`lectural --version --json` returns the application `tool_version` and:

```json
{
  "contract": "extraction",
  "contract_version": 2,
  "supported_contract_versions": [2],
  "schema_version": 2,
  "supported_schema_versions": [2]
}
```

## Extraction response and `evidence.json`

On success, `result` is the same evidence manifest written to `<out>/evidence.json`. Its top-level fields are `schema_version`, `contract_version`, `tool`, `tool_version`, `generated_at`, `source`, `speech`, `transcript`, `frames`, `artifacts`, `extraction`, `resources`, and `failure`.

- `source.id` is `sha256:<hex>` for a local input, computed as a streamed SHA-256 of the source file, or `youtube:<video_id>` for YouTube. `source.kind` is `youtube`, `local_video`, or `local_audio`; `source.title`, `duration_sec`, and nullable `resolution` describe the probed source.
- `speech` records caption/STT provenance, language, model, and a nullable bounded fallback code: `captions_unavailable`, `captions_unusable`, `forced_stt`, or `local_source`. Exception text is never part of the manifest.
- `transcript.segments` is inline. Each entry has a stable time-ordered, 1-based padded ID (`s0001`), `start`, `end`, and `text`. Missing source ends are filled from the next segment start or the probed media duration.
- `frames` is the ordered list of retained visual evidence. IDs are stable and padded (`f0001`); `start` is the frame timestamp, `sha256` is the written PNG digest, and `ocr` contains one of the existing OCR states plus annotation text, slide classification, and nullable reliability. OCR annotates evidence but does not control frame retention.
- `artifacts` contains only `evidence`, `transcript`, `frames_dir`, and `output_dir`; `frames_dir` is null for audio-only sources.
- `extraction.status` is `pass`, `warn`, or `fail`. `reasons` are bounded machine-readable values. Speech-gap coverage, visual timeline coverage, OCR state, timestamp integrity, and required evidence-file presence determine this status. Notes structure is not an extraction gate.
- `extraction.speech_completeness` includes the VAD speech spans used by the notes consumer. `extraction.visual_completeness` includes raw sample timestamps, notes frame IDs, and visual coverage predicates needed to reproduce the existing notes coverage without internal state.
- `extraction.timestamp_integrity` validates every segment interval (`0 <= start <= end <= duration + 0.001`) and frame start, with ordered frame timestamps. Audio duration may be unknown when unavailable.
- `resources` reports wall/stage seconds, process-tree peak RSS in MiB (null if optional `psutil` cannot be used), output bytes, and candidate/retained frame counts. Resource values are observational and never affect extraction status.
- `failure` is null on pass/warn, or one bounded code/message on fail.

The bare notes run reads `evidence.json` and the referenced transcript/frame files only. Its `coverage.json` retains `gap_check`, `scene_coverage`, `artifacts`, `notes_contract`, `overall_pass`, and the other notes completeness fields consumed by `render_notes_md` and the Stop hook.

Contract v2 removes the v1 aliases `representative_frames`, `source_kind`, top-level `status`/`extraction_status`, and `*_md`/`*_json` artifact names. Notes, synthesis-input, and coverage paths are not fields in the extraction manifest. The extraction response envelope's `status` is unchanged. `transcript.md` remains the human-readable citation target; its headings are English and its `<a id="tHHMMSS">` anchors remain stable.

LecturAL reports extraction completeness only. The contract intentionally has no assignment-relevance, code-scene, or project/build eligibility field.

The normative JSON Schemas are [extract.schema.json](extract.schema.json), [evidence.schema.json](evidence.schema.json), and [version.schema.json](version.schema.json).
