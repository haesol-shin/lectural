# Plan: Extraction evidence contract v2

## Inputs

- Issue: none (maintainer-directed, recorded in this plan)
- Historical product reference: [PR #32](https://github.com/haesol-shin/lectural/pull/32) supplied the evidence-first boundary and proposed future features; the current public contract is [`docs/contracts/cli.md`](../../docs/contracts/cli.md).
- Maintainer decisions:
  - Segments and frames are inline in `evidence.json`.
  - The bare `lectural <source>` form is removed in v0.3.0 in favor of `lectural notes` (PR C, not this plan).
  - Interval representation is deferred to the `query` contract work.
- Risk: high (public cross-repository contract; `lecture-tools` consumes it).

## Problem

`evidence.json` v1 reports that extraction passed but does not carry the evidence itself.

1. Structured transcript segments exist only in the internal `synthesis_input.json`; the public transcript is markdown. Segments have no end time: `Segment` stores only `t` (`lectural/acquisition.py:20-27`) although VTT cues, json3 events, the transcript API, and faster-whisper (`lectural/speech.py:31-45`) all provide one.
2. `extract` writes notes artifacts because it shares `_default_processor` with the notes run (`lectural/cli.py:265-438`), and extraction completeness depends on the notes contract (`lectural/coverage.py:222-266`, `cli.py:455-468` `NOTES_CONTRACT_INVALID`).
3. Speech provenance (caption vs STT, fallback reason) is absent from JSON; the internal fallback reason is free text including exception messages (`acquisition.py:164-179`).
4. `source` has no identity digest, so a bundle cannot be tied to its media.
5. No resource or cost data leaves the benchmark scripts.
6. `transcript.md` headings are hardcoded Korean (`lectural/synthesis.py:151-163`).

## Approach

### v2 `evidence.json` (= `extract --json` `result`)

```json
{
  "schema_version": 2,
  "contract_version": 2,
  "tool": "lectural",
  "tool_version": "0.3.0",
  "generated_at": "…",
  "source": {
    "id": "sha256:<hex> | youtube:<video_id>",
    "kind": "youtube | local_video | local_audio",
    "argument": "video.mp4",
    "duration_sec": 20.352,
    "has_video": true,
    "resolution": {"width": 1280, "height": 720},
    "citation": {"kind": "youtube | transcript"}
  },
  "speech": {
    "source": "caption | stt",
    "language": "en",
    "model": "medium | null",
    "fallback": {"code": "captions_unavailable | captions_unusable | forced_stt | local_source"} | null
  },
  "transcript": {
    "segments": [{"id": "s0001", "start": 0.0, "end": 4.8, "text": "…"}]
  },
  "frames": [
    {
      "id": "f0001", "start": 0.0, "path": "…/frames/frame_00000.png",
      "sha256": "<hex>", "width": 1280, "height": 720,
      "ocr": {"status": "text | no-text | skipped | failed", "text": "…", "is_slide": true, "reliable": true}
    }
  ],
  "artifacts": {"evidence": "…", "transcript": "…", "frames_dir": "…", "output_dir": "…"},
  "extraction": {"status": "pass | warn | fail", "reasons": [], "speech_completeness": {}, "visual_completeness": {}, "timestamp_integrity": {}, "ocr": {}},
  "resources": {
    "wall_sec": 160.2,
    "stages": {"speech": 0.0, "frames": 0.0, "dedupe": 0.0, "ocr": 0.0},
    "peak_rss_mb": 0.0,
    "artifact_bytes": 0,
    "frames_candidate": 40,
    "frames_retained": 2
  },
  "failure": null
}
```

Rules:

- IDs are 1-based, zero-padded to at least four digits (wider only past 9999 items), and assigned in time order. They are stable for identical inputs and are the only reference format later contracts (`query`, intervals) use.
- `segments[].end` comes from the source when provided. When a source omits it (json3 event without `dDurationMs`), `end = min(next.start, duration)`; the last segment uses `duration`. `_dedupe_rolling` keeps the first segment's `start` and extends its `end` to the last merged duplicate.
- `speech.fallback.code` is one of four bounded values. Exception text never reaches JSON; warnings keep their current text on stderr.
- `source.id` for local files is the streamed SHA-256 of the input file. YouTube uses `youtube:<id>`; the downloaded media is not hashed because the served format can vary.
- `frames[].sha256` is the digest of the written PNG, computed once after OCR selection.
- `resources` is observational: values vary between runs, and `verify` (PR D) never compares them. `peak_rss_mb` covers the process tree (OCR and the alignment worker run as children) and is `null` when it cannot be measured.
- Removed from v1: `representative_frames` (now `frames`, `timestamp_sec` becomes `start`), the notes, synthesis_input, and coverage artifact paths, and the duplicate aliases (`source_kind`, top-level `status`/`extraction_status`, `*_md`/`*_json` artifact names). The canonical locations are `source.kind` and `extraction.status`; the envelope `status` is unchanged. Frame OCR states keep the v1 values.
- `transcript.md` stays as the human-readable rendering and citation target, with English headings.

### Extraction and notes split

- New `lectural/extract.py` owns the evidence pipeline (acquisition, frames, dedupe, OCR, completeness, manifest) and returns the v2 bundle. It never writes `notes.md`, `synthesis_input.json`, or notes coverage.
- New `lectural/notes.py` builds `synthesis_input.json`, `notes.md`, and the notes coverage/contract from a bundle directory by reading only `evidence.json` and the files it references. Until PR C, the existing bare CLI calls `extract` and then `notes`, so users see no behavior change in this PR.
- Extraction completeness drops the notes-contract and notes-artifact checks. They move to the notes path, whose gate still feeds the completeness Stop hook.
- `_default_processor` is deleted after both callers move; no parallel old path remains.

### Rejected alternatives

- Parameterizing `_default_processor` with a `write_notes` flag: keeps the evidence core coupled to the notes consumer that §5 separates.
- `segments.jsonl` sidecar: rejected by the maintainer; inline keeps consumers on one file.
- Stdlib-only peak RSS: `resource` is unavailable on Windows and does not cover per-child peaks consistently. `psutil` is a mature primitive (§15) with wheels on every supported platform; it is already a `[bench]` dependency.

## Execution

1. **Segment end times (internal).** Add `Segment.end`; preserve ends in `parse_vtt`, `parse_json3`, `fetch_caption_segments`, and `transcribe_audio`; apply the missing-end and dedupe rules. Benchmark scoring keeps using `start`.
2. **Split extraction from notes.** Introduce `lectural/extract.py` and `lectural/notes.py`, move the notes gate, and rewire both `extract` and the bare CLI; delete `_default_processor`. Notes output stays byte-compatible for the existing notes tests.
3. **v2 manifest.** Bump `EXTRACTION_CONTRACT_VERSION` and `EXTRACTION_SCHEMA_VERSION` to 2; emit `source.id`, `speech`, inline `transcript.segments`, `frames` with IDs and hashes, and `resources`; map fallback reasons to codes; switch `transcript.md` headings to English; timestamp integrity validates `start <= end <= duration`.
4. **Contract documents.** Rewrite `docs/contracts/{evidence,extract,version}.schema.json` and `docs/contracts/cli.md` for v2; add a `CHANGELOG.md` `[Unreleased]` entry marked as a breaking contract change.
5. **Dependency.** Add `psutil>=5.9` to `[run]`; regenerate `uv.lock`; `doctor` reports it like the other runtime modules.

Steps 1–5 land as one PR; each step is a separate commit that keeps the suite green.

## Verification and recovery

Behavioral checks:

- Parser and STT tests: every path yields `start <= end`; missing-end fallback and duplicate merging follow the rules above.
- Contract tests (`tests/test_extraction_contract.py` migrated): v2 negotiation `[2]`; segment and frame IDs are ordered and unique; frame `sha256` matches the file; `source.id` matches a re-hash of the fixture; fallback codes are bounded and exclude exception text; notes, synthesis_input, and coverage paths are absent; `resources` is present and never affects `status`.
- Decoupling test: build notes from a bundle directory containing only `evidence.json`, `transcript.md`, and `frames/`, and match the current notes output for the same fixture.
- The emitted `evidence.json` for each benchmark fixture validates against `evidence.schema.json` using the existing shape-check approach (no new `jsonschema` dependency in the offline gate).
- Offline suite, `lectural doctor`, CI on Windows, Ubuntu, and macOS.

Smoke evidence (same protocol as v0.2.0):

- `lectural extract` on `tests/fixtures/benchmark/en_terms_01/video.mp4` and `audio.wav` on Debian 13 ARM64 and Windows 11 x86_64 from a clean `uvx` install; record status, segment and frame counts, `resources`.
- Opt-in YouTube caption run to confirm `speech.source: caption` and real caption end times.

Recovery:

- No consumer pins a LecturAL release yet (`agent-skills` `bundle.toml` still names a development commit), so v2 breaks no pinned integration.
- v0.2.0 remains the contract-1 release; rollback is reverting the PR before release or reinstalling `v0.2.0` after it.

## Out of scope

- CLI subcommands, removal of the bare form, `/lectural:notes` and Stop-hook migration (PR C).
- `inspect` and `verify` (PR D).
- Interval representation and `query`.
- Caption usability redesign (#23) beyond exposing the existing decision as bounded codes.
