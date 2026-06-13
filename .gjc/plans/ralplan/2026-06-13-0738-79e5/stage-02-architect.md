# Architect Review — LecturAL Implementation Plan (Option A)

> run_id: 2026-06-13-0738-79e5 | stage: architect | stage_n: 2
> Inputs: .gjc/specs/deep-interview-lectural.md (li-2026-0613, Ambiguity 4.8%, PASSED); .gjc/plans/ralplan/2026-06-13-0738-79e5/stage-01-planner.md
> Read-only planning review. No code, no mutations.

## Summary
Option A (deterministic Python core -> synthesis_input.json -> host-agent summary.md -> Python completeness hook) is the right backbone and is well aligned with the token-zero and CPU-first constraints. However the plan ships with a completeness gate whose semantics are internally inconsistent (the 0.98 covered-ratio conflates silence with missed speech), whose existence-only artifact check does not enforce the AC-8 structure it is supposed to guarantee, and whose hook wiring does not pin down how it locates the right output run or scopes itself to LecturAL stops. These are planning-stage defects that must be amended before execution. Architectural Status: WATCH. Recommendation: REQUEST CHANGES.

## Analysis

### What is sound
- P1/P2/P3 are correct and concretely mapped. Determinism for raw/OCR/dedup/coverage with LLM only at the host-summary step is the only decomposition consistent with the token-minimization constraint and the deferred-Ollama non-goal. Option C (multimodal LLM ingest) and Option B (local LLM) are correctly invalidated.
- Module decomposition (acquisition/speech/visual/ocr/synthesis/coverage) cleanly mirrors the topology and ACs, and the Segment/Frame/CoverageReport dataclass boundary gives testable seams (test_dedup/test_coverage/test_synthesis_input).
- The decision to enforce via settings.json and treat SKILL.md frontmatter as documentation-only is architecturally correct (single enforcement source).
- Caption-first short-circuit and frame-dedup-before-context are the right token levers.

### Where the architecture is under-specified or self-conflicting
The whole product value is one word from the spec: confidence (확신) that the lecture was fully captured, and that confidence is delegated entirely to coverage.json + hook. So the gate is load-bearing. Three properties of the gate as planned do not hold up.

1. The completeness metric mixes two incompatible definitions. AC-9 defines a gap as a non-silence untranscribed span > 60s. The plan §5 check 1 ANDs that with transcript_covered_ratio >= 0.98 over total duration. A real lecture has silent intros/outros, music, applause, board-writing pauses, and Q&A dead air. transcript_covered_ratio computed over wall-clock duration treats all of that silence as uncovered, so a perfectly transcribed 50-minute lecture with 3 minutes of distributed silence lands at ~0.94 and is falsely BLOCKED. The 0.98 ratio is a different, stricter, and frequently unachievable metric than the AC it claims to implement.

2. The gate does not enforce AC-8. Check 3 is existence + min-bytes on summary.md. AC-8 demands a TOC, a coverage header, and per-section timestamp/slide links. Because the host agent is the (non-deterministic, untested) producer of summary.md and the gate only checks that the file is non-empty, a one-line summary passes the gate while violating AC-8. The single guarantee of completeness does not actually inspect the artifact whose structure defines completeness.

3. Hook context resolution and scoping are unspecified. A Claude Code Stop/PostToolUse hook receives session JSON (cwd, transcript_path, session_id) on stdin; it does NOT receive the LecturAL output slug. In sequential batch mode there are multiple output/<slug>/coverage.json files. The plan says the hook identifies the working dir and loads output/<slug>/coverage.json but never says how <slug> is derived, nor how the hook no-ops when the stop is unrelated to a LecturAL run (a Stop hook fires on every turn end). As written, the hook either cannot find the run or blocks unrelated stops.

## Root Cause
The architecture pushes the only human-meaningful artifact (the structured summary) and therefore part of the completeness contract across a non-deterministic, non-reproducible boundary (the host agent), while the enforcement mechanism (the hook) lives on the deterministic side and runs against files the deterministic side never produced. coverage.json is generated before summary.md exists, so any summary property must be checked live at hook time, and structural quality cannot be checked at all without re-deriving it deterministically. The token-zero win is real, but it was bought by making the completeness guarantee partially unverifiable in exactly the standalone/automation mode that AC-11 promises.

## Steelman Antithesis (best case against pure Option A)
The strongest alternative is not Option B/C; it is Option A-prime: keep determinism and token-zero, but move a deterministic, extractive, template-based summary generator INTO the pipeline (synthesis.py emits a baseline summary.md from outline + merged segments + slides + coverage, with TOC, coverage header, and transcript/frame links auto-generated). The host agent then OPTIONALLY enriches/rewrites that baseline.

Why this is genuinely better on its own terms:
- Reproducibility/automation: AC-11 promises the core runs standalone and AC-13 promises completeness is machine-enforced. With pure Option A, a standalone CLI run (no host agent, and the explicitly designed-for non-developer wrap) produces NO summary.md, so the completeness hook can never pass headless and the confidence guarantee evaporates exactly where it is most needed. A-prime always produces a structurally valid, gate-passable artifact with zero tokens.
- Testability: a template summary is unit-testable (TOC present, every section linked, coverage header correct). Host-only summary has no test in Phase 10 beyond opaque E2E.
- Gate honesty: the gate can validate the real AC-8 structure because a deterministic producer guarantees it; the host can only improve prose, never break structure.
- No constraint violation: extractive templating uses zero LLM tokens, so the token-minimization principle is preserved; the host agent contribution becomes a quality enhancer rather than a correctness dependency.

The pure-Option-A counter-argument (host summaries read better, and the host LLM is already running so its prose is free) is valid for quality but does not address correctness/automation. Hence the synthesis below: do both.

## Tradeoff Tensions

T1. Token-zero host synthesis vs reproducibility/automation of the summary. Host-only summary = best prose, zero tokens, but non-deterministic, untested, and unproducible headless (breaks AC-11 standalone + AC-13 headless enforcement). Deterministic summary = reproducible, testable, gate-enforceable, but blander prose.
Synthesis: deterministic template baseline (always produced, gate-validated for AC-8 structure) + optional host enrichment layered on top. summary.md is valid even with no agent; the agent only upgrades prose. Resolves T1 without spending tokens.

T2. CPU STT latency vs completeness-gate strictness. The latency mitigation is downgrading the model (--model base/small) on long videos, which lowers accuracy. If the gate keys on covered-ratio it conflates lower accuracy / more silence with incompleteness, so the latency escape hatch fights the gate.
Synthesis: define coverage as did we ATTEMPT transcription over all detected speech regions (VAD-based), not transcription quality or wall-clock ratio. Model downgrade then changes accuracy but not coverage, decoupling latency tuning from gate pass/fail.

T3. PaddleOCR install weight vs accuracy on Windows. Tesseract fallback keeps the pipeline running, but Tesseract Korean accuracy is materially worse than PP-OCRv5; the weak slides_with_text>=1 bar still passes, so the product silently degrades on its core value (모든 화면 텍스트) with no signal.
Synthesis: for a single-developer Windows v1, treat PaddleOCR as a hard install-once dependency (README + binaries.py preflight) rather than optional; keep Tesseract strictly as a logged degraded fallback, and record the OCR engine used in coverage.json so degradation is visible rather than silent.

## Open-Question Verdicts

Q1. synthesis_input.json versioning — VERSION IT. Add a top-level "schema_version": "1" (monotonic integer, bump on any breaking field change). references/synthesis_contract.md must pin the version it documents, and SKILL.md must assert the version it expects before reading. Rationale: this JSON is the sole cross-boundary interface between the deterministic core and the host instructions; an unversioned interface breaks the SKILL prompt silently when the schema evolves.

Q2. Hook location single vs dual — SINGLE SOURCE (settings.json) for enforcement; SKILL.md frontmatter documentation-only, NOT an executable hook. Endorse the plan. Dual executable hooks risk double-firing and divergent exit semantics. Make this explicit so executor does not add a second live hook.

Q3. scene-coverage N + dedup thresholds —
- N: derive from duration, do NOT fix a constant. N = clamp(ceil(duration_sec/300), 1, 24) (one bucket per ~5 min, capped). Document in config.py.
- Recognize the keyframe-presence-per-bucket check is a weak signal: 2fps downsample + I-frame extraction nearly guarantees a frame per bucket, so passing it proves little. The real failure mode is the opposite (over-dedup hides slides). Keep dedup thresholds (histogram + SSIM) in config.py with regression fixtures (plan already does), and add an over/under-dedup sanity bound (e.g., flag if dedup ratio is implausibly high).
- slides_with_text>=1 is too weak as a global check; make it conditional: require text on slide-classified frames only, and document that text-free frames are normal (consistent with the spec excluding OCR-failure-rate from the gate).

Q4. visual/ocr coupling — KEEP DECOUPLED via the Frame dataclass (clean, testable boundary; ocr.py populates Frame.ocrText). The acceptable-coupling caveat: visual dedup runs BEFORE OCR, so incremental-build slides / progressive reveals that are visually near-identical but textually different get merged and content is lost — a direct threat to 모든 화면 텍스트. Mitigate without coupling the modules: add a cheap post-OCR reconciliation in synthesis (or a thin visual.refine pass) that re-splits frames merged visually when their OCR text differs beyond a threshold. Modules stay separate; correctness is protected.

## Findings (severity, location, impact, fix)

BLOCKER: none.

HIGH-1 — coverage metric conflates silence with missed speech (plan §5 check 1; coverage.py / Phase 7 T7.1).
Impact: transcript_covered_ratio >= 0.98 over total duration falsely BLOCKS normal lectures that contain legitimate silence; directly contradicts AC-9 (gap = NON-silence span > 60s).
Fix: compute coverage over VAD-detected speech regions only. Gate on max non-silence speech gap <= 60s; drop or redefine the 0.98 ratio as a speech-region coverage ratio. Add a unit fixture with silent intro/outro that must PASS.

HIGH-2 — gate does not enforce AC-8 structure (plan §5 check 3; completeness_hook.py / Phase 9, AC-8).
Impact: existence + min-bytes lets a trivial host summary pass while violating the TOC/coverage-header/per-section-link requirements that define completeness.
Fix: validate summary.md content (TOC marker present, coverage header present, >= K timestamp links, >= 1 frame link). Best paired with the deterministic baseline (steelman) so the structure is guaranteed before the host edits it.

HIGH-3 — hook run-context resolution and stop-scoping unspecified (plan §5 wiring; Phase 9 T9.2).
Impact: Stop/PostToolUse JSON does not carry the output slug; in sequential batch there are multiple coverage.json files; a Stop hook fires on every turn so it may block unrelated stops or fail to find the run.
Fix: define slug resolution deterministically (e.g., a run pointer file output/.last_run or LECTURAL_OUTPUT_DIR env written by the CLI), and make the hook NO-OP (exit 0) when no active LecturAL run marker is present so it never blocks unrelated sessions. Specify which event (Stop vs PostToolUse) and the matcher.

HIGH-4 — summary production and completeness are unverifiable in standalone/headless mode (AC-11 vs AC-13; architecture-level).
Impact: the reusable CLI and the planned non-developer wrap have no host agent, so no summary.md is produced and the completeness hook can never pass headless; the core confidence guarantee is absent in exactly the mode AC-11 sells.
Fix: adopt the deterministic baseline summary (steelman / T1 synthesis). The host agent becomes an optional enhancer, not a correctness dependency.

MEDIUM-1 — synthesis_input.json has no schema_version (plan §4 schema). Fix per Q1.
MEDIUM-2 — pre-OCR visual dedup can drop incremental-build slides (visual.py before ocr.py). Fix per Q4 (post-OCR re-split).
MEDIUM-3 — settings.json hardcoding the python command is fragile on Windows (py launcher / venv / python3 not on PATH). Fix: resolve interpreter explicitly (sys.executable captured at install, or py -3 with documented fallback) and preflight in binaries.py.
MEDIUM-4 — scene-coverage check is a weak completeness signal and N is implied-fixed (plan §5 check 2). Fix per Q3.

LOW-1 — OCR engine actually used is not recorded, hiding Tesseract Korean degradation. Fix: write ocr_engine into coverage.json and warn on fallback (supports T3).
LOW-2 — yt-dlp breakage is operational; plan mitigation (pin + troubleshooting + transcript-api fallback) is adequate. No change required.

## Recommendations (prioritized)
1. Redefine the coverage gate on VAD-detected speech regions; remove the wall-clock 0.98 ratio or recast it as speech-region coverage (HIGH-1). Add silence-bearing PASS fixtures to test_coverage.py.
2. Add a deterministic extractive baseline summary.md generator in synthesis.py (TOC + coverage header + links), zero tokens; host agent enrichment becomes optional (HIGH-2, HIGH-4, T1). Unit-test its structure.
3. Make the hook validate AC-8 structure and resolve its run via a CLI-written run pointer + no-op when no active run (HIGH-2, HIGH-3).
4. Add schema_version to synthesis_input.json and pin it in synthesis_contract.md and SKILL.md (MEDIUM-1).
5. Add post-OCR frame re-split to protect incremental slides; derive N from duration; condition slides_with_text on slide-classified frames (MEDIUM-2, MEDIUM-4).
6. Pin interpreter resolution for the Windows hook; record ocr_engine in coverage.json (MEDIUM-3, LOW-1).

## Architectural Status
WATCH

## Code Review Recommendation
REQUEST CHANGES

## Trade-offs (options compared)
| Concern | Pure Option A (host-only summary) | Option A-prime (deterministic baseline + optional host enrichment) |
|---|---|---|
| Token cost | 0 external; host prose free | 0 external; host prose free (enrichment only) |
| Summary prose quality | Highest | High (baseline plainer, host can upgrade) |
| Reproducibility / standalone (AC-11) | Fails headless (no summary) | Always produces valid summary |
| Gate can enforce AC-8 | No (existence-only) | Yes (structure guaranteed) |
| Testability of summary | None (E2E only) | Unit-testable structure |
| Implementation cost | Lower now | One added deterministic module |
Recommendation: adopt A-prime; it preserves every constraint that justified Option A while closing the correctness/automation gaps.
