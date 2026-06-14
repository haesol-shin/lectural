# Changelog

All notable changes to LecturAL are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.2] - 2026-06-14

### Fixed
- Plugin failed to load with "Duplicate hooks file detected" because
  `plugin.json` referenced `./hooks/hooks.json`, which Claude Code now auto-loads.
  Removed the `hooks` key from `plugin.json`; the standard `hooks/hooks.json`
  (the completeness Stop hook) is loaded automatically. `lectural doctor` now
  flags a manifest `hooks` key that points at the auto-loaded file.

## [0.1.1] - 2026-06-14

### Removed
- The standalone `lectural` plugin skill (`skills/lectural/SKILL.md`). Only the
  `/lectural:notes` and `/lectural:setup` slash commands now surface in the
  Claude Code menu; the enrichment references under `skills/lectural/references/`
  are retained.

### Changed
- Shortened the `/lectural:notes` and `/lectural:setup` command descriptions and
  dropped the `[lectural]` prefix.
- De-skilled host-agent enrichment wording across `AGENTS.md`, the setup command,
  and `docs/synthesis_contract.md` (command-driven, not skill-driven).

### Added
- Advisory, non-blocking `PR Check` workflow plus an `AGENTS.md`/`CONTRIBUTING.md`
  rule to keep PR bodies aligned with `PULL_REQUEST_TEMPLATE.md`.
- Release-notes automation: the Release workflow builds the GitHub Release body
  from the matching `CHANGELOG.md` section via `scripts/changelog_notes.py`.
- A `claude plugin validate .` CI gate (pinned `@anthropic-ai/claude-code`).
- Tests guarding version-surface/CHANGELOG consistency and the release-notes
  extractor.

## [0.1.0] - 2026-06-14

### Added
- YouTube lecture → complete notes pipeline: raw `transcript.md` plus a
  seven-section `notes.md` (3줄 요약 · 목차 · 흐름 · 핵심 개념·이론 · 정리 노트 ·
  복습 질문 · 정리 커버리지).
- youtu.be deeplinks on `핵심 개념·이론` and `복습 질문`; slide images and
  frame-recovered titles in `정리 노트`.
- Claude Code plugin surface: `/lectural:notes`, `/lectural:setup`, and a
  completeness Stop hook.
- `lectural doctor [--fix] [--json]` runtime check and bounded auto-repair.
- Two-layer completeness gate: CLI exit code (structure) plus Stop hook
  (citations, enrichment, per-slide checks).

[Unreleased]: https://github.com/haesol-shin/lectural/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/haesol-shin/lectural/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/haesol-shin/lectural/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/haesol-shin/lectural/releases/tag/v0.1.0
