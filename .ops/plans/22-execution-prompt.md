# Execution prompt — Issue #22 (paste into a fresh session)

You are the Executor for an already-approved plan. Do not re-plan, re-scope, or second-guess the approved decisions below — implement them. If you find the plan factually wrong against current code, stop and report; do not silently improvise around it.

## Context
- Repo: `haesol-shin/lectural`, local checkout `C:/Users/haesol/dev/LecturAL`.
- Worktree already exists: `C:/Users/haesol/dev/LecturAL-worktrees/22-visual-evidence-efficiency`, branch `feat/22-visual-evidence-efficiency`. Use it — do not create a new worktree.
- Approved plan: `.ops/plans/22-visual-evidence-efficiency.md` at commit `5a2f807` on that branch. Read it in full before touching any code — it contains the exact design, file/line references, and rationale; this prompt only points at it.
- Maintainer approval recorded: https://github.com/haesol-shin/lectural/issues/22#issuecomment-5735692212
- Repository operating standard: `skill://` isn't available outside this session — instead read `https://github.com/haesol-shin/agent-skills/blob/main/docs/repository-operations.md` directly (raw: `https://raw.githubusercontent.com/haesol-shin/agent-skills/main/docs/repository-operations.md`) for commit/PR/review conventions. Also read this repo's `AGENTS.md` and `CONTRIBUTING.md`.

## Important environment caveat
The plan's real-world reproduction case for the 432.5–444s duplicate (Execution slice 3) depends on `.tmp/youtube-noPuRPDiY6k-20260918-android/` in the repo root. This directory is **gitignored and local to this workstation** — it will only be present if this session runs on the same machine as this planning session. If it is missing:
1. Check `.tmp/` for any similarly-named extraction directory first (it may have moved/been cleaned).
2. If genuinely absent, do not fabricate the case — build only the synthetic committed fixture (also required by slice 3) and report the real-case verification as unavailable in this environment, rather than skipping it silently or inventing numbers.

## Execution order
Follow the plan's "Execution slices" section (8 items) in order. Highlights, not a substitute for reading the plan:
1. Fix PaddleOCR re-instantiation (`lectural/ocr.py`).
2. Bounded O(1)-decode dedupe confirmation gate in `visual.dedupe_frames` (peak-RAM bound is a hard requirement, not an optimization nice-to-have — re-read Decision driver 7 and Chosen approach §2 before implementing).
3. Verify against the real case (see caveat above) + add the synthetic committed fixture to `tests/fixtures/benchmark/`.
4. Thread `ocr.reliable` end to end (`_ocr_paddle`/`_ocr_tesseract` → `ocr_image` → `Frame.ocr_confidence` → both `slide_dicts` AND `representative_frame_dicts` — both consumers, this was a repeated review finding, don't do only one).
5. Extend `_safe_source` (`lectural/evidence.py`) to actually preserve the new `resolution` field — do not just add it at the call site, the sanitizer drops unknown keys.
6. Calibrate the reliability threshold against `docs/reports/benchmark_stt_baseline_2026-09-19.md`'s CER anchors. If it does not correlate usefully, STOP and report back (Decision driver 9 / Rollback section) — do not ship an unvalidated threshold.
7. Update `docs/contracts/evidence.schema.json` + `docs/contracts/cli.md`; add a contract test that `_safe_source` preserves `resolution` (this exact gap was missed once already in planning review).
8. Before/after benchmark run, `scripts/benchmark.py --reps 3 --warm` plus `--skip-ocr` pair. Apply the approved tolerance: CPU/wall-time ≤+5%, peak RAM/storage ≤+10%, recall/duplicate-rate/timestamp-integrity/accepted-OCR metrics 0% regression, all vs. the #21 baseline report's corresponding values.

## Constraints (from the plan, do not relax)
- No new runtime dependency (everything needed — `pytesseract.run_and_get_multiple_output`, ffprobe — already ships with existing deps).
- Additive schema changes only; `EXTRACTION_CONTRACT_VERSION`/`EXTRACTION_SCHEMA_VERSION` stay at `1`; `synthesis_input.json`'s `SCHEMA_VERSION` stays at `2`.
- No change to Issue #19's four OCR-state enum values (run-level or per-frame).
- Skip formatters/linters/full project-wide test suite mid-flight is NOT authorized here — this is solo sequential execution, not a parallel batch; run the normal offline suite (`uv run --with pytest --with numpy pytest -q`) as you go.

## When done
- Do not merge, approve your own work, or mark the PR ready without review.
- Open a draft PR (or ask the maintainer how they want it opened) with the standard template (`.github/PULL_REQUEST_TEMPLATE.md`), `Closes #22`, `Plan: .ops/plans/22-visual-evidence-efficiency.md @ 5a2f807`.
- Get a fresh-context reviewer pass (different session/agent, slow model, no access to your implementation conversation) before requesting maintainer merge — risk:medium requires this.
- If you hit a decision the plan leaves open (aggregation method, exact threshold constants — both explicitly deferred to empirical tuning in the plan) — resolve it empirically as the plan directs and document the resulting value/rationale in the PR; that's expected, not a blocker.

## Explicitly out of scope
Do not touch Issue #23 or anything under a `23-*` branch/worktree — unrelated, independent work.
