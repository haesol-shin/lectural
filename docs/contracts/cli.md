# LecturAL CLI contract

- Contract version: `2`
- JSON Schema version: `2`
- Current application version: see `lectural --version --json`

This is the public boundary for consumers such as `lecture-tools`. Consumers must use only this JSON and the paths it returns; they must not import LecturAL modules or read internal run state. Unknown fields may be ignored, but an unknown schema or contract version must fail closed.

## Commands

```console
lectural --version [--json]
lectural extract <source> --out <new-directory> [--skip-ocr] --json
lectural notes <input>... [--out <root>] [--force-stt] [--model <model>] [--skip-ocr] [--keep-frames]
lectural inspect <bundle-directory-or-evidence.json> [--json]
lectural verify <bundle-directory-or-evidence.json> [--source <file-or-URL>] [--json]
lectural doctor [--fix] [--plugin] [--json]
```

`<source>` is one supported YouTube URL/ID or existing local `.mp4`, `.webm`, `.mkv`, or `.wav` file. Each `<input>` to `notes` is either such a source or an existing evidence-bundle directory containing `evidence.json`. Source inputs are extracted and then passed to the notes consumer; bundle inputs regenerate notes in place without re-extraction. `--out` chooses the output root for source inputs. `--force-stt`, `--model`, `--skip-ocr`, and `--keep-frames` are extraction-only options and are rejected for bundle inputs.

Multiple `notes` inputs are processed sequentially. Each source reserves a unique slug directory under `--out`, adding a numeric suffix when a directory already exists; evidence-bundle inputs keep their existing directory.

The `extract` command rejects the requested output path when it already exists, even when it is empty. It creates the path only after source syntax is valid. Every manifest artifact path is absolute and resolves below the new output directory. `extract` writes `evidence.json`, `transcript.md`, and (for video sources) retained frames; it does not write `notes.md`, `synthesis_input.json`, or `coverage.json`. The `notes` command creates those notes artifacts after extraction, or rebuilds them from a supplied evidence bundle. Local source paths are not copied into the public JSON; `source.argument` contains only a filename, kind, and citation kind.

## Doctor

`lectural doctor [--fix] [--plugin] [--json]` checks the Python runtime and external binaries (`ffmpeg`, `yt-dlp`). Plugin files are not required by default; `--plugin` adds checks for the agent instructions, skill and references, hooks, plugin manifest, and marketplace manifest. Run it from the plugin root when requesting plugin checks.

The JSON report retains `schema_version`, `items`, `overall_status`, and `exit_code`, with optional `actions` when `--fix` performs an action. Exit codes are `0` ready, `2` missing or incompatible components, and `1` internal or unfixable failure. `--fix` makes only the existing bounded attempts for `yt-dlp` and `ffmpeg`.

## Common JSON envelope

`extract`, `inspect`, `verify`, and `--version --json` emit one object with the common envelope:

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

Extraction envelope `status` is `ok`, `partial`, or `error`; inspect and verify use `ok` or `error`. Error entries contain only a bounded `code` and safe `message`; they never contain an exception, source path, credential, token, cookie, environment value, or internal state path. The evidence manifest itself has no duplicate top-level status: use `result.extraction.status`.

When no extraction manifest could be produced, `result` is a bounded failure result rather than an evidence manifest. Its `source` is null or a minimal safe descriptor; artifact paths are null when output creation did not occur. The failure-result shape is defined by `extract.schema.json`.

Exit codes for `extract` are:

| Code | Meaning |
| ---: | --- |
| `0` | extraction `pass` |
| `1` | extraction `warn` or `fail` after a JSON response was produced |
| `2` | invalid source or output requires user action; JSON response produced |

Argument-parser failures before a command can be identified use argparse's stderr path. Normal responses and processable failures keep stdout as a single JSON document.

## Inspect

```console
lectural inspect <bundle-directory-or-evidence.json> [--json]
```

`inspect` is read-only. Human output is a concise inventory of source identity and duration, speech provenance, transcript/frame counts and timestamps, OCR and completeness states, extraction reasons, versions, artifact sizes, and resource measurements. With `--json`, `result` contains those same inventory fields. Its response schema is [inspect.schema.json](inspect.schema.json).

Exit codes:

| Code | Meaning |
| ---: | --- |
| `0` | The bundle was loaded and inventoried |
| `2` | The bundle is unreadable, invalid JSON, or uses an unsupported contract/schema version |

## Verify

```console
lectural verify <bundle-directory-or-evidence.json> [--source <file-or-URL>] [--json]
```

`verify` reports `schema`, `containment`, `artifacts`, `frame_hashes`, `identifiers`, `timestamps`, `completeness`, and `source` checks. Each check has a `name` and `status` (`pass`, `fail`, or `skipped`), with an optional bounded code and path-free detail. The source check is `skipped` unless `--source` is supplied; for a local file it compares a streamed SHA-256, and for YouTube it compares the video ID. `result` is `{ "valid": boolean, "checks": [...] }`; the common envelope status is `ok` for valid bundles and `error` otherwise. The response schema is [verify.schema.json](verify.schema.json).

Exit codes:

| Code | Meaning |
| ---: | --- |
| `0` | Every applicable check passed |
| `1` | The bundle loaded, but one or more checks failed |
| `2` | The bundle is unreadable, invalid JSON, uses an unsupported contract/schema version, or command usage is invalid |

Manifest paths are stored as absolute paths. For copied or moved bundles, `inspect` and `verify` preserve each artifact's path relative to the recorded `artifacts.output_dir`, then resolve it under the bundle's actual directory. A recorded path outside that original output directory fails `containment`; verification never follows it outside the bundle.

`verify` checks structure, safe containment, required artifacts, frame hashes, stable identifiers, timestamp bounds/order, declared speech and visual completeness, and optional source identity. It does not re-extract media, assess transcript/OCR factual accuracy, determine assignment relevance, compare resource measurements, or certify that evidence is suitable for a particular task. It is a deterministic structural and completeness check, not a fact-check.

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
- `extraction.speech_completeness.speech_spans` lists the detected voiced-speech spans as `[start, end]` seconds. `extraction.visual_completeness.raw_sample_times` lists the candidate frame timestamps sampled before deduplication, and `slide_frame_ids` lists the `frames[].id` values kept as distinct slides (all retained frames when OCR is skipped). Consumers such as the notes run rebuild their own coverage from these fields without internal state.
- `extraction.timestamp_integrity` validates every segment interval (`0 <= start <= end <= duration + 0.001`) and frame start, with ordered frame timestamps. Audio duration may be unknown when unavailable.
- `resources` reports wall/stage seconds, process-tree peak RSS in MiB (null if optional `psutil` cannot be used), output bytes, and candidate/retained frame counts. Resource values are observational and never affect extraction status.
- `failure` is null on pass/warn, or one bounded code/message on fail.

The `notes` command reads `evidence.json` and the referenced transcript/frame files to build notes artifacts. Its `coverage.json` retains `gap_check`, `scene_coverage`, `artifacts`, `notes_contract`, `overall_pass`, and the other notes completeness fields consumed by `render_notes_md` and the Stop hook.

Contract v2 removes the v1 aliases `representative_frames`, `source_kind`, top-level `status`/`extraction_status`, and `*_md`/`*_json` artifact names. Notes, synthesis-input, and coverage paths are not fields in the extraction manifest. The extraction response envelope's `status` is unchanged. `transcript.md` remains the human-readable citation target; its headings are English and its `<a id="tHHMMSS">` anchors remain stable.

LecturAL reports extraction completeness only. The contract intentionally has no assignment-relevance, code-scene, or project/build eligibility field.

The normative JSON Schemas are [extract.schema.json](extract.schema.json), [evidence.schema.json](evidence.schema.json), [inspect.schema.json](inspect.schema.json), [verify.schema.json](verify.schema.json), and [version.schema.json](version.schema.json).
