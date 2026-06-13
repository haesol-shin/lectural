## Summary
G003 packages the deterministic core as a skill + CLI and adds a Stop-hook completeness gate. The pure orchestration (injected processor), raw-frame-time wiring into coverage, and centralized anchors are clean and well-tested for the happy/recorded-run paths. But the system-level completeness PROMISE is defeatable on the exact batch path v1 supports: a mid-batch processor failure is never recorded and remaining URLs are skipped, so failed/unproduced videos are invisible to the hook (and a first-URL failure makes the hook a no-op). Recommendation: REQUEST CHANGES.

## Analysis
- CLI orchestration (lectural/cli.py:47-68): pure, injectable processor; sequential batch records each run via runstate. Unit tests (tests/test_cli.py) confirm single/batch recording, fresh-session-per-invocation, order preservation.
- Real pipeline _default_processor (cli.py:73-141) correctly wires RAW pre-dedup frame times into coverage: raw_sample_times comes from raw_frames timestamps, slides are the deduped slide_dicts. coverage_inputs_from_extraction (coverage.py) is keyword-only and documents the raw-vs-slides contract; carry-cap logic in scene_coverage depends on dense raw samples. Question (4): CORRECT.
- runstate (lectural/runstate.py): start_session replaces the file (fresh session id), record_run appends. Sequential single-process writes mean no race. Tests confirm fresh session and cleared prior runs. Question (2): fresh-session semantics correct; stale-state risk exists (file never cleared/consumed, see Findings).
- Hook (scripts/completeness_hook.py): no-op when no runstate/empty runs (99-101); iterates ALL recorded runs (104-110); exit 2 on coverage overall_pass false OR missing summary anchors; Korean reasons. Tests cover good/coverage-fail/anchor-fail/one-of-batch-fail. Anchors (ENRICH_MARKER, COVERAGE_ANCHOR, TOC_ANCHOR, HH:MM:SS timestamp regex, conditional frames link) are consistent with synthesis.render_summary_md output and docs/synthesis_contract.md; SECTION_PREFIX only checked indirectly via the timestamp regex. Question (1): correct for recorded runs; gaps below.
- SKILL.md: sharp trigger (YouTube lecture URL + COMPLETE notes, KR/EN trigger phrases, refuses done until hook confirms); preserves token-zero and capture-ALL promises; documents py -3 Windows fallback. Question (6): CLEAR.

## Root Cause
The completeness guarantee is anchored on runstate, but runstate records only SUCCESSFULLY produced runs. The hook can only validate what was recorded, so any URL that fails before record_run, or any URL skipped after an earlier failure aborts the batch loop, is structurally invisible to the gate. The backstop has a hole on the precise failure mode it exists to catch.

## Findings
- CRITICAL/HIGH (BLOCKER) Partial-batch failure bypasses the gate. cli.py:62-68 records a run only after processor returns; a raise propagates to main (160-162 then return 1), skipping the failed URL and all remaining URLs. First-URL failure leaves runs empty, so the hook no-ops exit 0 (completeness_hook.py:99-101). A batch with failed videos can pass the gate. Fix: record an attempted/expected/pending entry per URL up front (or wrap each processor call to record a failure) so the hook exits 2 on any unproduced/incomplete run.
- HIGH (BLOCKER) Hook fails open on import error. completeness_hook.py:27-34 wraps runstate AND synthesis imports in one except that sets read_state to None (31); main (98) then no-ops. An anchor-import failure disables run validation, and any ImportError silently disables the completeness backstop instead of failing closed. Fix: split try blocks; if read_state cannot import, diagnose and exit non-zero.
- MEDIUM runstate never cleared (runstate.py:27-37). Hook re-validates the last session on every later Stop; deleting/moving the output dir later makes unrelated turns exit 2 until the file is hand-deleted. Fix: scope/consume runstate per session.
- MEDIUM settings.json:9 hardcodes python; SKILL.md py -3 fallback is prose-only and cannot auto-apply to the actual hook command (Windows Store-stub/missing-python risk). Fix: launcher trying py -3 then python, or per-OS command.
- LOW SECTION_PREFIX from the contract is checked only indirectly via the timestamp regex (completeness_hook.py:39-61). Not currently exploitable (renderer always emits at least one section) but looser than docs/synthesis_contract.md.

## Recommendations
1. Record every attempted URL up front with a pending/failed status and have the hook exit 2 on any non-complete run; do not abort the batch on a single failure (P1 blocker).
2. Split the hook import try/except so a runstate import failure fails closed (P1 blocker).
3. Clear/consume the runstate after a passing gate to stop stale re-validation (P2).
4. Make the hook command launcher cross-platform (py -3 then python) rather than prose-only guidance (P2).
5. Assert SECTION_PREFIX directly to match the synthesis contract (P3).

## Architectural Status
WATCH

## Code Review Recommendation
REQUEST CHANGES

## Trade-offs
- Record-on-success (current) vs record-attempt-up-front: current is simpler and keeps runstate to real artifacts, but cannot detect failed/skipped videos; record-attempt closes the completeness hole at the cost of a pending/failed state machine. The product promise favors record-attempt.
- Fail-open vs fail-closed hook: fail-open avoids blocking unrelated turns on a broken install but silently voids the gate; for a completeness gate, fail-closed-with-diagnostic is correct.
- Lanes: Architecture WATCH (sound design, fixable completeness/coupling gaps); Product BLOCK (headline nothing-missed guarantee defeatable on batch failure); Code WATCH (fail-open coupling + portability).
