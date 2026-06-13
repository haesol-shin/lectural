# Architect Review (Pass 2) — LecturAL Plan v4 (Option A-prime)

> run_id: 2026-06-13-0738-79e5 | stage: architect | stage_n: 5
> Inputs: spec deep-interview-lectural.md (li-2026-0613, PASSED); stage-04-revision.md; prior stage-02-architect.md
> Read-only re-review. Planning only. No mutations.

## Summary
The revision adopts Option A-prime and closes all four prior HIGH issues with concrete, testable mechanisms (deterministic baseline summary, VAD-based gap, runstate pointer + Stop no-op, summary_validate structural gate, AC-1..13 matrix, OCR/visual hardening). No BLOCKER and no HIGH remain. Two MEDIUM concerns are newly exposed by the revision (batch gate scope, VAD accuracy as the new single point of trust) and two prior MEDIUMs are still open. Architectural Status: CLEAR. Recommendation: APPROVE.

## Analysis

### Prior HIGH verification
- HIGH-1 (silence vs missed speech conflation) -> RESOLVED. P5 + Phase 4 (vad.py) + §5 check 1 gate on max_non_silence_untranscribed_gap_sec <= 60; the wall-clock 0.98 ratio is gone; long_silence(PASS)/real_gap(FAIL) fixtures regress the exact failure mode. Matches AC-9 definition precisely.
- HIGH-2 (gate not enforcing AC-8) -> RESOLVED. summary_validate.py + hook check 4 validates TOC + coverage header + per-section timestamp/slide link anchors; deterministic baseline guarantees the structure exists before any enrichment. The gate now inspects the artifact whose structure defines completeness.
- HIGH-3 (hook run-context/scoping) -> RESOLVED. runstate.py writes an active-run pointer (env LECTURAL_OUTPUT_DIR + .gjc/state/lectural/active.json); hook resolves output dir from it, no-ops (exit 0) when pointer absent/non-LecturAL/coverage.json missing; Stop event + full matcher specified. The fire-on-every-turn and slug-derivation gaps are answered.
- HIGH-4 (headless summary unverifiable vs AC-11) -> RESOLVED. synthesis.py writes baseline summary.md deterministically (token-zero, extractive), so AC-7/AC-8/AC-13 hold headless; host enrichment is a strict quality layer, not a correctness dependency. The AC-11 standalone path now produces a gate-passable artifact.

Tally: 4 RESOLVED / 0 PARTIAL / 0 UNRESOLVED.

### What strengthened correctly
OCR/visual: PaddleOCR preflight + ocr_engine recorded in coverage.json (LOW-1 closed), ko/en fixtures, named dedup thresholds with over/under tests, post-OCR re-split for incremental slides (MEDIUM-2 closed). The AC matrix gives each AC a command + fixture + expected coverage + expected hook exit, and --force-stt makes AC-3/AC-4 deterministically testable without depending on a no-caption video in the wild.

## Findings

BLOCKER: none. HIGH: none.

MEDIUM-A (new) — Stop-hook validates only the LAST completed run; AC-2 batch can partial-pass. §5/§T10.1 say the runstate pointer is overwritten per run and the Stop hook checks the last completed run. In sequential batch (URL1..URLn) the turn ends once, so the hook validates only URLn. If URL1 is incomplete (real gap / missing summary) the hook exits 0 and completion is falsely declared, contradicting AC-13s intent across the AC-2 path. Folders remain on disk but enforcement does not cover them.
Fix: have runstate accumulate the set of runs created in the current session/turn and have the hook validate every pending run (block if any fails), or explicitly scope the gate to single-URL and document batch as manually re-checked. Cheap, no re-architecture.

MEDIUM-B (new) — VAD becomes the single point of trust for AC-9; CPU silencedetect can misclassify quiet speech as silence (false PASS). The gate now trusts the speech mask completely. silencedetect is amplitude/dB-threshold based; quiet or low-SNR speech the STT also dropped could be labeled silence and excluded from the gap, yielding a false PASS — the inverse of the old false BLOCK. real_gap fixture tests a non-silence gap FAIL but not quiet-speech-misclassified-as-silence.
Fix: pin silencedetect dB/duration thresholds in config.py, add a quiet-speech fixture (low-amplitude real speech that must still count as non-silence), and prefer webrtcvad (frame-energy + spectral) as primary or cross-check when available.

MEDIUM-C (carried, unresolved) — synthesis_input.json still has no schema_version. Prior MEDIUM-1 recommended versioning the sole cross-boundary interface; §4 schema still omits it. An evolving schema will silently break the SKILL enrichment prompt.
Fix: add top-level schema_version: 1, pin it in synthesis_contract.md, assert it in SKILL.md before reading.

MEDIUM-D (carried, partial) — Windows interpreter resolution still hardcodes python. §5 labels the command Windows-portable but uses plain python scripts/completeness_hook.py; py-launcher/venv/python3-not-on-PATH cases are unaddressed.
Fix: resolve sys.executable captured at install or py -3 with documented fallback; preflight in binaries.py.

LOW-A — baseline-vs-enriched divergence is adequately fenced. Host enrichment must preserve anchors; summary_validate runs at Stop time against the current (post-enrichment) summary.md, so a host that strips a required anchor is blocked (exit 2). Residual risk is semantic (host can add unsupported prose) which is inherent to token-zero host synthesis and out of structural-gate scope. Acceptable; consider noting the enrichment-must-preserve-anchors contract in synthesis_contract.md (plan already states this).

LOW-B — summary_validate link-count threshold. Ensure the structural check requires a minimum (>=1 timestamp link, >=1 frame link) rather than mere marker presence; deterministic baseline guarantees it, so this is a test-assertion note.

## Root Cause
N/A — the prior root cause (completeness contract pushed across the non-deterministic host boundary while the gate ran on the deterministic side against files it never produced) is eliminated: the deterministic core now produces and the deterministic gate now validates the same artifact.

## Recommendations (prioritized)
1. Make the Stop hook validate all runs created in the current session/turn (or scope+document single-URL enforcement) — MEDIUM-A.
2. Pin VAD thresholds, add a quiet-speech non-silence fixture, prefer/cross-check webrtcvad — MEDIUM-B.
3. Add schema_version to synthesis_input.json and pin it in contract + SKILL — MEDIUM-C.
4. Resolve the hook interpreter explicitly for Windows — MEDIUM-D.
5. Assert minimum link counts in summary_validate — LOW-B.
All are implementation-time amendments; none block starting Phase 1.

## Architectural Status
CLEAR

## Code Review Recommendation
APPROVE

## Trade-offs
| Concern | Pure Option A (prior) | Option A-prime (adopted) |
|---|---|---|
| Headless summary (AC-11/AC-13) | Fails, no artifact | Always produced, gate-passable |
| Gate enforces AC-8 | No | Yes (summary_validate) |
| AC-9 gap definition | Wall-clock 0.98, false BLOCK | VAD non-silence gap <= 60s |
| New trust dependency | Host agent | VAD accuracy (MEDIUM-B) + batch scope (MEDIUM-A) |
| Token cost | 0 external | 0 external (baseline extractive) |
