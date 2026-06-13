# G003 LecturAL — Architect Re-Review (stage 15)

## Summary
Both stage-14 blockers are RESOLVED. The completeness gate is now fail-closed: every URL is pre-registered as pending before processing, mid-batch failures are recorded and the batch continues, and the Stop hook reads run-state self-contained (no lectural import) so an import error can no longer disable the gate. No new bypass gap found. Recommendation: APPROVE.

## Analysis
- lectural/cli.py run() (lines 45-83): runstate.start_session(urls, runstate_file) is the FIRST action — it pre-registers every URL as pending and writes the file immediately. The per-URL loop wraps processor(...) in try/except: success -> update_run(i, status=complete, ...); exception -> update_run(i, status=failed, error=...) and CONTINUES (no abort/return). Every URL therefore has a terminal-or-pending entry on disk regardless of where failure occurs, including a first-URL failure.
- lectural/runstate.py: start_session builds runs[] with one pending entry per URL (index, url, status, output_dir/coverage_json/summary_md=None). update_run merges by index, always persisting status and only overwriting non-None fields (pre-registered url preserved). read_state returns None on missing file and on OSError/JSONDecodeError.
- scripts/completeness_hook.py: _read_runstate is fully self-contained — it computes the path from LECTURAL_RUNSTATE/cwd and parses JSON itself; the lectural.synthesis import is wrapped only to supply anchor literals and explicitly cannot affect run-state reading. Missing file -> None (only exit-0 no-op). Unreadable/malformed file -> sentinel runs:[status=failed] -> exit 2. _validate_run returns a problem for status failed and pending, and for any other status re-validates the actual coverage.json (overall_pass + gap/scene/artifacts) and summary anchors. main returns 2 if any run yields problems, 0 only when all runs validate.

## Root Cause (of prior blockers) — now fixed
- BLOCKER-1 root cause was record-after-success: runs were appended only post-processor, so an early failure left runs=[] and the hook no-oped. Fixed by pre-registration in start_session.
- BLOCKER-2 root cause was a single try/except around a lectural.runstate import that nulled the reader on ImportError. Fixed by inlining the reader and scoping the package import to anchors only.

## Findings
- BLOCKER-1 (partial-batch bypass): RESOLVED. Pre-registration + record-and-continue + hook treating pending/failed as failure. First-URL failure now yields runs=[failed, pending...] -> exit 2. Confirmed by code and by tests test_cli_run_continues_batch_on_processor_error_and_records_failure, test_hook_batch_with_one_failed_run_blocks_whole_gate, and the smoke artifact (failed+pending batch -> exit 2).
- BLOCKER-2 (fail-open on import error): RESOLVED. _read_runstate has no lectural dependency; anchor import failure falls back to literals without touching run-state logic. Missing file is the sole exit-0 no-op; unreadable/malformed -> exit 2. Confirmed by code and smoke artifact (malformed runstate -> exit 2).
- No new bypass gap (verified):
  - Complete run with absent coverage.json: _validate_run -> if not isfile(cov_path) return [coverage.json missing] -> exit 2 (test_hook_missing_coverage_json_blocks).
  - status complete but coverage overall_pass False: hook re-reads coverage content -> blocks (defense-in-depth; complete only means processor finished).
  - Legacy/missing status field: falls through to full artifact validation; passes only if coverage + anchors genuinely pass; missing coverage -> exit 2. The redteam _make_run fixtures omit status and exercise exactly this path.
  - Empty/zero-URL session: runs=[] -> hook no-op exit 0 (acceptable; argparse requires a URL for real runs).
- LOW — stale cross-turn run-state lifecycle: the run-state file is overwritten only on the next lectural invocation; it is never torn down after a passing turn. A subsequent unrelated turn re-validates the stale file. If it passed, harmless exit 0; if artifacts were later deleted, an unrelated turn could be blocked (false-positive, not a bypass). Pre-existing, not introduced by this fix. Suggest documenting or clearing run-state on a clean pass.
- LOW — cosmetic: failed/pending runs render [None] as the output_dir header (output_dir stays None for unproduced runs). No functional impact; message still names error/url.

## Verification note
The restricted bash tool permits only gjc ralplan/gjc state, so I could not re-run the 112-test suite myself. Grounding is by full source reading of runstate.py/cli.py/hook + the redteam/cli/hook test contracts + the real-invocation smoke artifact (no-runstate->0, complete->0, failed+pending->2, malformed->2).

## Recommendations
1. (LOW) Tear down or mark the run-state file after a fully-passing turn to avoid stale cross-turn re-validation.
2. (LOW) Populate output_dir/url in failed/pending hook headers for readability.

## Architectural Status
CLEAR

## Product Status
CLEAR

## Code Status
CLEAR

## Code Review Recommendation
APPROVE

## Trade-offs
- status=complete means processor finished, plus hook re-validates coverage content: slightly redundant but correctly fail-closed; preferred over trusting a status flag.
- Self-contained hook reader duplicates path/read logic with runstate.py: minor duplication accepted in exchange for removing the fail-open import dependency.
