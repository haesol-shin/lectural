# Plan: Per-kind source handlers

## Inputs

- Issue: none (maintainer-directed refactor, recorded in this plan).
- Base: `origin/main` at `17485de`; branch `refactor/source-handlers`.
- Maintainer decisions:
  - Accept a one-time change to existing code now so later source features (public URL input #45 / PR #47, cookies, #44 speech-only and time range) touch few files.
  - `InputSource` stays a frozen dataclass (identity, citation, serialization). Per-kind behavior moves into one `SourceHandler` per kind; no inheritance on `InputSource`. An independent design review preferred this because `InputSource` is the serialization boundary, tests construct it directly (`tests/test_caption_language.py`), and `docs/contracts/evidence.schema.json` fixes `source.kind` to `youtube | local_video | local_audio`.
- Risk: medium (no contract change; wide internal touch).

## Problem

Source-kind branching is spread over four modules (`grep -n "SourceKind\." lectural`):

1. `media.py`: three `SourceKind -> function` dicts (`_PROBE_RESOLVERS`, `_AUDIO_RESOLVERS`, `_VIDEO_RESOLVERS`) and nine one-line resolvers.
2. `acquisition.acquire_speech`: `"local_source" if not YOUTUBE`, `YOUTUBE and not force_stt`, an unknown-kind `ValueError`, `force_stt and YOUTUBE`.
3. `extract.py`: `_source_id` (`youtube:<id>` vs file SHA-256), an unknown-kind `ValueError` in the no-video branch, a YouTube `citation` override that repeats `safe_as_dict`, and a second `"local_source"` default.
4. `source.py`: `has_video`, `caption_capable`, `citation_kind` each test `kind`.

The `"local_source"` rule is defined twice; adding a kind means editing all four modules.

## Goal

One handler per kind answers every per-kind question; pipeline steps (STT, VAD, scenes, OCR, evidence) stay functions and ask the handler. Behavior, CLI output, evidence JSON, error messages, and exit codes stay byte-identical (the warning-location exception is under Compatibility guarantees). No new features.

## Out of scope

- New source kinds, URL input, cookies, speech-only, time range.
- Caption fetching and caption-language policy (stay in `acquisition.py`), STT policy, `verify.py` (works on serialized dicts; its own `_hash_file` stays).
- `classify_source` rules and `InputSource` fields.
- `scripts/` (they build a YouTube `InputSource` and patch `lectural.media.resolve_audio`; both keep working).

## Approach

### Module layout

```
lectural/sources/__init__.py   handler_for(source) and the kind -> handler registry
lectural/sources/base.py       SourceHandler Protocol
lectural/sources/youtube.py    YouTubeHandler
lectural/sources/local.py      LocalVideoHandler, LocalAudioHandler
```

Local video and audio get two small handlers in one module, sharing two module functions (title-hint probe, file SHA-256 id). They differ in `has_video`, audio resolution, and video resolution, so one handler with internal `if` would re-create the branching. No inheritance.

### `SourceHandler` Protocol

| Member | Purpose |
| --- | --- |
| `has_video: bool` | Whether frames, OCR, and visual gates apply. |
| `caption_capable: bool` | Whether `acquire_speech` may try captions before STT. |
| `citation_kind: CitationKind` | Deeplink style used by `InputSource` serialization. |
| `stt_fallback_code: str \| None` | Fallback code when speech is STT without a caption attempt (`"local_source"` for local, `None` for YouTube). |
| `probe(source) -> SourceMetadata` | Title/duration/video id; YouTube runs yt-dlp, local uses `title_hint`. |
| `resolve_audio(source, out_dir) -> str` | Audio path for STT/VAD: yt-dlp download, ffmpeg extraction, or the WAV in place. |
| `resolve_video(source, out_dir) -> str \| None` | Video path for frames, `None` for audio-only. |
| `source_id(source) -> str` | `youtube:<id>` or `sha256:<hex>` of the input file. |

`handler_for(source)` looks up `source.kind`; an unknown kind raises `ValueError(f"Unsupported source kind: {source.kind!r}")`, the message both current guards use.

### What moves where

- `media.py` keeps external-tool wrappers (`fetch_video_metadata`, `download_audio`, `download_video`, `probe_video_resolution`, plus the ffmpeg audio extraction renamed to public `extract_audio(path, out_dir)`) and `SourceMetadata`. The three dicts and nine resolvers go. `probe_source`, `resolve_audio`, `resolve_video` stay as one-line delegates to `handler_for(source)`: they are the asset seam the pipeline calls and tests/scripts patch. The delegate imports `handler_for` inside the function; handlers import `media` as a module and call its wrappers by attribute, so there is no import-time cycle and patches of `media.require_binary` / `media.subprocess.run` still apply.
- Handlers decide which tool a kind uses; `media.py` knows how to run each tool.
- `source.py`: `has_video`, `caption_capable`, `citation_kind` delegate to `handler_for(self)` (lazy import), so each fact is defined once. `as_dict`/`safe_as_dict` unchanged.
- `acquisition.acquire_speech`: `handler = handler_for(source)` once; `fallback_code = handler.stt_fallback_code`; caption branch and `forced_stt` test `handler.caption_capable`; the unknown-kind `elif` is removed (`handler_for` raises it). Audio still goes through `media.resolve_audio`.
- `extract.py`: `_source_id` removed for `handler_for(source).source_id(source)`; the redundant YouTube `citation` override removed (same value, same key position); the unreachable no-video kind guard removed; the STT default uses `handler.stt_fallback_code`. `_sha256_file` moves to `evidence.sha256_file` so frames and the local handler share it.

Call sites changed: `media.py`, `source.py`, `acquisition.py`, `extract.py`, `evidence.py`. `cli.py` already only calls `media.probe_source`.

## Compatibility guarantees

- `kind` values, `InputSource` fields, `as_dict`/`safe_as_dict` output, evidence JSON, `transcript.md`, notes artifacts, stdout, exit codes, error messages, and warning message text: identical.
- Not identical: the `<file>:<line>:` location Python prefixes to the caption-fallback `RuntimeWarning` on stderr. `acquire_speech` warns with `stacklevel=2`, so the location is the `acquire_speech` call in `extract.py`, whose line moves when `_source_id`/`_sha256_file` leave the file (it also differs per install path and moves with any unrelated edit above it). Category and message stay identical. Owner sign-off on this exception is required before implementation; the alternative, pinning the call's line number, is not maintainable.
- Public names in `lectural.media` and `lectural.source` stay; the private `media._*_RESOLVERS` dicts go.
- Also different, internal only: a hand-built `InputSource` with an invalid `kind` now gets the existing `ValueError("Unsupported source kind: …")` from every entry point instead of `KeyError` from `media.probe_source`. `classify_source` cannot produce such a source, so CLI behavior is unchanged.
- No CHANGELOG entry: no user-visible change.

## Test strategy

- Existing suite passes unchanged except `tests/test_media.py::test_all_source_kinds_have_explicit_resolver_entries`, which reads the removed dicts; it moves to `tests/test_sources.py` asserting the same invariant: every `SourceKind` has a handler.
- Byte-identical proof (throwaway, not committed): baseline worktree at `17485de` vs branch head, same machine and model.
  - Run baseline twice first to confirm STT output is deterministic here.
  - `lectural extract <fixture> --out <new dir> --json` for a fixture `video.mp4` (with and without `--skip-ocr`) and `audio.wav` from `tests/fixtures/benchmark/`; `lectural notes` on the same WAV.
  - Error inputs: missing `.mp4`, unsupported suffix, a directory, a non-YouTube string.
  - Diff stdout, stderr, exit code, `evidence.json`, `transcript.md`, notes files after normalizing only `generated_at`, `resources` timings/RSS/bytes, the output-directory and checkout prefixes, and the `<file>:<line>:` location of `RuntimeWarning` lines.
  - YouTube path offline: run `extract.extract_source` on a YouTube `InputSource` with fakes below the handler layer (`media.fetch_video_metadata`, `media.download_audio`, `media.download_video`, `acquisition.fetch_caption_segments`, speech functions) for caption, forced-STT, and caption-failure paths on both trees; diff evidence and captured stderr (same normalization), so the warning category and message are proven identical.
- Static gate: `grep -rn "SourceKind\." lectural --include=*.py` lists only `lectural/sources/` and `lectural/source.py` (`classify_source` and the enum). Run as a command, not a test.
- `uv run --with pytest --with numpy pytest -q` green, `lectural doctor` ready, `git diff --check` clean.

## Risks

- Test seams: tests and `scripts/benchmark.py` patch `media.resolve_audio` / `probe_source` / `resolve_video` and `media.require_binary`. If a pipeline step called a handler directly, those patches would be bypassed and real tools would run. Mitigation: pipeline assets go only through the `media` delegates; handlers call `media` wrappers by module attribute.
- Import cycle `media` ↔ `sources` ↔ `source`: avoided by the two lazy imports above; any import order is covered by the full suite and a bare `python -c "import lectural.sources"` / `import lectural.media`.
- STT nondeterminism could mask or fake a diff: the baseline double run detects it before comparing.

## Commit plan

Each commit leaves the suite green.

1. `refactor(media): move per-kind resolution into source handlers` — add `lectural/sources/`, `media.extract_audio`, delegates; move the completeness test.
2. `refactor(source): derive source capabilities from handlers` — `InputSource` properties delegate.
3. `refactor(acquisition): ask the source handler for caption and fallback` — remove kind branches in `acquire_speech`.
4. `refactor(extract): take source id and fallback from the handler` — `evidence.sha256_file`, drop `_source_id`, citation override, kind guard.

Estimated diff: about 9 files, +190 / −130 (new package ~150 lines; `media.py` net about −50).

## PR #47 on top

PR #47 (`feat/45-public-url`) is rebuilt after this merges, as a pre-step: the CLI detects a public URL before `classify_source`, `remote.materialize` fetches it into scratch, and the pipeline receives a plain `local_video` / `local_audio` `InputSource`. The URL never becomes a kind, so `SourceKind.REMOTE` and its `media.py` `_require_materialized` entries are dropped, and the rebuilt PR touches neither `lectural/sources/` nor `media.py`. Its remaining changes stay where they are: `remote.py`, URL-label helpers in `source.py`, `cli.py`, `evidence.py` (origin-only argument), and the `extract_source(work_dir=...)` parameter, which handlers already accept as `out_dir`.

Later work fits the same seats: cookies belong to the URL fetch pre-step (`remote.py` from PR #47), not to `YouTubeHandler` or the `media.py` wrappers; #44 speech-only is a pipeline flag (`visual_required = source.has_video and not speech_only`) plus a format-selection change in that pre-step, because `lectural/remote.py` `_selected_formats` in PR #47 currently refuses an audio-only pick when the page has video; a time range is a pipeline trim step on the resolved audio/video paths, so the Protocol does not change.
