# Changelog

All notable changes to LecturAL are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/haesol-shin/lectural/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/haesol-shin/lectural/releases/tag/v0.1.0
