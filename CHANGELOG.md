# Changelog

All notable changes to LecturAL are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **BREAKING:** Extraction contract and schema are now version 2. The manifest removes `representative_frames`, `source_kind`, duplicate top-level `status`/`extraction_status`, notes/synthesis/coverage artifact paths, and `*_md`/`*_json` aliases. Consumers must use `source.kind`, `extraction.status`, `frames`, and the four canonical artifact paths.
- **BREAKING:** The bare `lectural <source>` form is removed in favor of `lectural notes <source>`.
- `lectural notes` accepts existing evidence bundles and regenerates notes in place without re-extraction.
- CLI status and failure messages are now in English; ffmpeg/ffprobe banners and progress are suppressed while errors remain visible.
- Extraction no longer emits notes, synthesis-input, or notes coverage artifacts; `lectural notes` composes evidence extraction with notes generation.
- `transcript.md` headings are English; timestamp anchors remain unchanged.
- `lectural doctor` checks the Python runtime and external binaries by default; `--plugin` enables plugin distribution checks.

### Added
- A thin host-neutral `skills/lectural/SKILL.md` routes agent requests through the public CLI and evidence contract.
- Evidence manifests include source identity, speech provenance with bounded fallback codes, inline interval-bearing transcript segments, frame IDs and SHA-256 digests, extraction completeness details, and observational resource measurements.
- Process-tree peak RSS uses `psutil>=5.9`; RSS is null when sampling is unavailable, while other resource metrics remain available.
- Tagged releases build the sdist and wheel, attach them to the GitHub Release, and publish them to PyPI through Trusted Publishing. The wheel no longer ships the `lectural_bench` benchmark package.
- Read-only `lectural inspect` inventories evidence bundles; `lectural verify` checks schema, containment, artifacts, frame hashes, identifiers, timestamps, completeness, and optional source identity, including after bundles are moved.

## [0.2.0] - 2026-09-23

### Added
- Local lecture inputs: existing `.mp4`, `.webm`, `.mkv`, and `.wav` files alongside YouTube URLs/IDs.
- `--skip-ocr` to keep scene frames while skipping OCR and the slide-text coverage check.
- Source-aware citations: local notes use relative `transcript.md#tHHMMSS[-n]` anchors instead of `youtu.be` links.
- Versioned `lectural --version --json` and `lectural extract ... --json` evidence responses with safe paths, completeness, timestamp integrity, representative frames, and explicit OCR states.
- Transform-aware slide deduplication for shifted, panned, and zoomed frames, with fail-closed OpenCV provenance checks and calibrated thresholds.
- Confidence-aware OCR representative selection plus source/frame dimensions and OCR reliability in JSON evidence.
- Evidence quality and resource benchmark: EN/KO/mixed fixtures, `lectural_bench` metrics (WER/CER, terminology recall, timestamp error, voiced recall/max gap, frame recall/duplicate rate, OCR quality), `scripts/benchmark.py`, and the versioned `docs/contracts/benchmark.schema.json` report schema. Install with the new `[bench]` extra; it is never part of `[run]`.
- Recorded multi-language STT/OCR baseline reports under `docs/reports/`.

### Changed
- `[run]` pins `opencv-python`, `opencv-contrib-python`, and `opencv-python-headless` to exactly `4.6.0.66` (previously `<=4.6.0.66`); transform-aware alignment refuses mismatched OpenCV providers instead of guessing. `pytesseract` now requires `>=0.3.13`.

### Fixed
- Sequential sources no longer overwrite an existing or already-reserved output slug; collisions use `-2`, `-3`, and later suffixes.
- Video visual timeline coverage now fails closed when duration is missing, zero, negative, or non-finite; local audio remains visual not-applicable.
- OCR now reuses one engine per frame batch instead of rebuilding it for every representative frame.

### Compatibility
- New extraction JSON contract version 1 and schema version 1 (`docs/contracts/cli.md`); consumers should pin `v0.2.0` and check `supported_contract_versions`.
- Transform-aware deduplication can keep fewer near-duplicate slide frames than v0.1.2 for the same video; existing output directories are never overwritten.

### Known limitations
- Only the YouTube caption path is validated end to end; local-media ASR, forced faster-whisper, and caption fallback remain unvalidated (#23).
- `[run]` installs three overlapping OpenCV providers for the same `cv2` namespace (#29).

### Rollback
- Reinstall the previous release with `uvx --from "lectural[run] @ git+https://github.com/haesol-shin/lectural@v0.1.2" lectural`. v0.1.2 has no JSON contract, so JSON consumers must pin back as well.

## [0.1.2] - 2026-06-14

### Fixed
- Plugin failed to load with "Duplicate hooks file detected" because `plugin.json` referenced `./hooks/hooks.json`, which Claude Code now auto-loads. Removed the `hooks` key from `plugin.json`; the standard `hooks/hooks.json` (the completeness Stop hook) is loaded automatically. `lectural doctor` now flags a manifest `hooks` key that points at the auto-loaded file.

## [0.1.1] - 2026-06-14

### Removed
- The standalone `lectural` plugin skill (`skills/lectural/SKILL.md`). Only the `/lectural:notes` and `/lectural:setup` slash commands now surface in the Claude Code menu; the enrichment references under `skills/lectural/references/` are retained.

### Changed
- Shortened the `/lectural:notes` and `/lectural:setup` command descriptions and dropped the `[lectural]` prefix.
- De-skilled host-agent enrichment wording across `AGENTS.md`, the setup command, and `docs/synthesis_contract.md` (command-driven, not skill-driven).

### Added
- Advisory, non-blocking `PR Check` workflow plus an `AGENTS.md`/`CONTRIBUTING.md` rule to keep PR bodies aligned with `PULL_REQUEST_TEMPLATE.md`.
- Release-notes automation: the Release workflow builds the GitHub Release body from the matching `CHANGELOG.md` section via `scripts/changelog_notes.py`.
- A `claude plugin validate .` CI gate (pinned `@anthropic-ai/claude-code`).
- Tests guarding version-surface/CHANGELOG consistency and the release-notes extractor.

## [0.1.0] - 2026-06-14

### Added
- YouTube lecture → complete notes pipeline: raw `transcript.md` plus a seven-section `notes.md` (3줄 요약 · 목차 · 흐름 · 핵심 개념·이론 · 정리 노트 · 복습 질문 · 정리 커버리지).
- youtu.be deeplinks on `핵심 개념·이론` and `복습 질문`; slide images and frame-recovered titles in `정리 노트`.
- Claude Code plugin surface: `/lectural:notes`, `/lectural:setup`, and a completeness Stop hook.
- `lectural doctor [--fix] [--json]` runtime check and bounded auto-repair.
- Two-layer completeness gate: CLI exit code (structure) plus Stop hook (citations, enrichment, per-slide checks).

[Unreleased]: https://github.com/haesol-shin/lectural/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/haesol-shin/lectural/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/haesol-shin/lectural/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/haesol-shin/lectural/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/haesol-shin/lectural/releases/tag/v0.1.0
