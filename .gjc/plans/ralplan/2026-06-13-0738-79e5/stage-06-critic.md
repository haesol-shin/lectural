# Critic Pass 2 Evaluation — LecturAL Plan v4

> run_id: 2026-06-13-0738-79e5 | stage: critic | stage_n: 6
> Inputs read: `.gjc/specs/deep-interview-lectural.md`, `.gjc/plans/ralplan/2026-06-13-0738-79e5/stage-04-revision.md`, `.gjc/plans/ralplan/2026-06-13-0738-79e5/stage-03-critic.md`, `.gjc/plans/ralplan/2026-06-13-0738-79e5/stage-05-architect.md`

**[OKAY]**

**Justification**: stage-04 revision is execution-ready for approval. It replaces pure Option A with Option A-prime, gives the deterministic core responsibility for baseline `summary.md`, changes coverage from wall-clock ratio to VAD-masked non-silence gaps, defines runstate-driven Stop hook scoping plus `summary_validate`, adds an AC-1..AC-13 verification matrix, and hardens OCR and visual dedup. Architect pass 2 is CLEAR / APPROVE with only four MEDIUM implementation-time amendments. Those amendments are real but do not require another planning iteration because they can be folded into implementation without changing architecture, sequencing, or acceptance criteria.

## Prior required revisions
1. **ADDRESSED** — Option A-prime is adopted in Principles, Options, Phase 7, and Synthesis contract: deterministic baseline `summary.md` is produced headlessly and host enrichment is optional.
2. **ADDRESSED** — AC-9 coverage is VAD and silence-mask based: `vad.py`, `SpeechMask`, `max_non_silence_untranscribed_gap_sec <= 60`, and `long_silence` / `real_gap` fixtures replace the wall-clock 0.98 ratio.
3. **ADDRESSED** — Hook run context is defined: `runstate.py`, env `LECTURAL_OUTPUT_DIR`, `.gjc/state/lectural/active.json`, Stop trigger, no-op behavior, coverage checks, and `summary_validate` are specified. Architect MEDIUM-A notes batch-wide validation should be strengthened during implementation.
4. **ADDRESSED** — The AC matrix now maps AC-1..AC-13 to command, fixture or URL class, expected artifacts, expected coverage, and hook exit. Some entries use named greenfield fixtures rather than already-existing files, which is acceptable for execution because the fixture tree is explicitly specified.
5. **ADDRESSED** — OCR and visual hardening is specified: PaddleOCR preflight, Tesseract degraded mode with `ocr_engine`, ko/en fixtures, explicit dedup thresholds, over/under tests, and post-OCR re-split for incremental slides.
6. **ADDRESSED** — Principles and alternatives now explain why A-prime preserves token-zero, deterministic raw and baseline, CPU-only operation, and standalone verification while invalidating old Option A, B, and C.

## AC verification concreteness
- **AC-1: CONFIRMED** — `python -m lectural.cli <URL>` against `captions_video` expects `output/<slug>/`, `coverage.json`, hook exit 0.
- **AC-2: CONFIRMED** — `python -m lectural.cli <URL1> <URL2>` against two caption fixtures expects two slug folders and per-folder coverage, hook exit 0. MEDIUM-A asks implementation to validate all batch runs, not only the last pointer.
- **AC-3: CONFIRMED** — caption path versus `--force-stt` / `nocaption_video` expects `transcript_source: caption` versus `stt`.
- **AC-4: CONFIRMED** — `cli --force-stt <URL>` expects timestamped `transcript.md`, `source=stt`, and gap <= 60.
- **AC-5: CONFIRMED** — `pytest tests/test_dedup.py` over `frames_seq` and `incremental_slide` expects reduced frames and reasonable `slide_count`.
- **AC-6: CONFIRMED** — ko/en OCR pytest plus smoke fixtures expect OCR text, `ocr_engine`, and `slides_with_text >= 1`.
- **AC-7: CONFIRMED** — E2E on `captions_video` expects both `transcript.md` and deterministic baseline `summary.md` plus artifact coverage.
- **AC-8: CONFIRMED** — `pytest tests/test_summary_validate.py` expects TOC, coverage header, timestamp links, and frame links; missing anchors produce hook exit 2.
- **AC-9: CONFIRMED** — `pytest tests/test_coverage.py` with `long_silence` and `real_gap` expects gap <= 60 PASS and > 60 FAIL, hook 0 versus 2.
- **AC-10: CONFIRMED** — Skill invocation against `.claude/skills/lectural/SKILL.md` and `scripts/run_lectural.py` expects outputs and hook exit 0.
- **AC-11: CONFIRMED** — `python -m lectural.cli --help` plus headless E2E validates standalone CLI/module execution without host enrichment.
- **AC-12: CONFIRMED** — E2E expects `transcript.md`, `summary.md`, `coverage.json`, and `frames/` under `output/<video-title>/` with required fields.
- **AC-13: CONFIRMED** — `pytest tests/test_hook.py` plus E2E with passing and failing coverage injection expects no-op 0, pass 0, fail 2.

## Representative implementation simulation
1. **Headless single URL**: `cli.py` creates a slug folder, acquisition chooses captions or STT, `synthesis.py` emits both markdown files, `coverage.py` writes gap/scene/artifact data, and Stop hook validates the same deterministic artifacts. AC-7, AC-8, AC-11, and AC-13 no longer depend on host agent behavior.
2. **Silence versus real missed speech**: long silent spans are excluded by `SpeechMask`, so legitimate silence passes; a non-silence transcript gap over 60s fails coverage and hook exit 2. This directly fixes the previous AC-9 false-block problem.
3. **Visual/OCR path**: ffmpeg extraction plus histogram/SSIM dedup reduces frames, PaddleOCR or degraded Tesseract records `ocr_engine`, post-OCR re-split prevents incremental slide collapse, and coverage checks scene buckets plus `slides_with_text` without using OCR failure rate as an invalid proxy.
4. **Batch run**: sequential folder creation is clear. The current plan says the Stop hook validates the last completed run, which is not ideal for batch-wide enforcement but is a bounded implementation-time follow-up, not an architecture blocker.

## Summary
- **Clarity**: Strong. Module responsibilities, phases, hook behavior, and output contracts are explicit.
- **Verifiability**: Strong enough for execution. Every AC has a mapped command or fixture-backed test, expected artifacts or coverage, and hook outcome.
- **Completeness**: Satisfies AC-1..AC-13 at plan level. Remaining items are implementation refinements.
- **Big Picture**: Fits the spec: CPU-first, token-minimal, deterministic core, host enrichment optional, future UI extensibility preserved.
- **Principle/Option Consistency**: Consistent. A-prime resolves old Option A contradictions while keeping B and C invalid for v1.
- **Alternatives Depth**: Adequate. Old Option A, B, and C are fairly rejected; A-prime is the correct adopted variant.
- **Risk/Verification Rigor**: Adequate for approval. OCR, VAD, STT latency, yt-dlp breakage, and dedup tuning have concrete mitigations and tests.

## Non-blocking implementation-time follow-ups
1. **MEDIUM-A** — Stop hook currently validates only the last completed batch run. During implementation, accumulate and validate all runs created in the current session or explicitly add a batch re-check loop.
2. **MEDIUM-B** — VAD is now the main AC-9 trust boundary. Pin silencedetect thresholds, add a quiet-speech fixture, and prefer or cross-check webrtcvad where available.
3. **MEDIUM-C** — Add top-level `schema_version: 1` to `synthesis_input.json`, document it in `synthesis_contract.md`, and assert it before enrichment.
4. **MEDIUM-D** — Replace hardcoded `python scripts/completeness_hook.py` with an explicit interpreter resolution strategy for Windows, such as captured `sys.executable` or documented `py -3` fallback.

## Required fixes before approval
None.

Verdict: **OKAY — execution-ready, pending approval**.
