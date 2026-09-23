# LecturAL extraction CLI contract

- Contract version: `1`
- JSON Schema version: `1`
- Current application version: see `lectural --version --json`

This is the public boundary for consumers such as `lecture-tools`. Consumers must use only this JSON and the paths it returns; they must not import LecturAL modules or read internal run state. Unknown fields may be ignored, but an unknown schema or contract version must fail closed.

## Commands

```console
lectural --version --json
lectural extract <source> --out <new-directory> [--skip-ocr] --json
```

`<source>` is exactly one supported YouTube URL/ID or existing local `.mp4`, `.webm`, `.mkv`, or `.wav` file. The existing bare-source form remains available for notes generation:

```console
lectural <source> [--out <root>] [--skip-ocr]
```

The extraction command rejects the requested output path when it already exists, even when it is empty. It creates the path only after source syntax is valid. Every returned artifact path is an absolute native path resolving below that new output directory. Local source paths are not copied into the public JSON; the source descriptor contains only a filename, kind, and citation kind.

## Common JSON envelope

Both JSON commands return one object with:

```json
{
  "schema_version": 1,
  "contract_version": 1,
  "tool": "lectural",
  "tool_version": "0.2.0",
  "status": "ok",
  "result": {},
  "errors": [],
  "generated_at": "2026-09-18T08:00:00Z"
}
```

`status` is `ok`, `partial`, or `error`. Error entries contain only a bounded `code` and safe `message`; they never contain an exception, source path, credential, token, cookie, environment value, or internal state path.

Exit codes for `extract` are:

| Code | Meaning |
| ---: | --- |
| `0` | extraction `pass` |
| `1` | extraction `warn` or `fail` after a JSON response was produced |
| `2` | invalid source or output requires user action; JSON response produced |

Argument-parser failures before a command can be identified use argparse's stderr path. Normal responses and processable failures always keep stdout as a single JSON document.

## Version negotiation

`lectural --version --json` returns the application `tool_version` and:

```json
{
  "contract": "extraction",
  "contract_version": 1,
  "supported_contract_versions": [1],
  "schema_version": 1,
  "supported_schema_versions": [1]
}
```

## Extraction response and `evidence.json`

`result` is the same evidence manifest written to `<out>/evidence.json`. Its top-level fields are:

- `source` / `source_kind`: normalized `youtube`, `local_video`, or `local_audio` input kind. `source.resolution.width` and `.height` describe the actual processed video; they are null for audio-only input.
- `status` / `extraction_status`: `pass`, `warn`, or `fail`.
- `artifacts`: output-contained paths for `evidence`, `transcript`, `notes`, `synthesis_input`, `coverage`, `output_dir`, and `frames_dir` when visual evidence applies. The `*_md` and `*_json` names are stable aliases.
- `extraction.reasons`: bounded machine-readable reason objects.
- `extraction.speech_completeness` and `extraction.visual_completeness`: deterministic completeness results. Visual completeness is `not-applicable` for local audio.
- `extraction.timestamp_integrity`: validity and counts for transcript and representative-frame timestamps.
- `extraction.ocr.status`: exactly `skipped`, `completed-no-text`, `completed-with-text`, or `failed`. OCR is an annotation/index and never controls representative-frame retention.
- `representative_frames`: timestamped retained frame paths with nullable pixel `width`/`height`. Each frame has an `ocr` annotation with `status`, nullable `text`, `is_slide`, and nullable `reliable`. `reliable` is a quality axis only for `status: text`; it never changes the existing four OCR-state values. Unreliable text remains in evidence but is omitted from trusted `synthesis_input.json` slide text.
- `failure`: `null` on pass/warn, or one bounded code/message on fail.

LecturAL reports extraction completeness only. The contract intentionally has no assignment-relevance, code-scene, or project/build eligibility field.

The normative JSON Schemas are [extract.schema.json](extract.schema.json), [evidence.schema.json](evidence.schema.json), and [version.schema.json](version.schema.json).
