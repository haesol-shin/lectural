# Plan: Deliver efficient and trustworthy visual evidence

## Inputs
- Issue: #22 (haesol-shin/lectural)
- Specification: none (issue is the contract)
- Research:
  - Read `lectural/visual.py`, `lectural/ocr.py`, `lectural/evidence.py`, `docs/contracts/evidence.schema.json` end to end.
  - `visual.dedupe_frames` (the only dedupe path actually wired into `ocr_frames`) uses pHash (64-bit DCT, `PHASH_HAMMING_THRESHOLD=12`, 2-frame persistence gate) only. `is_same_slide`/`select_keyframe_indices` (hist_corr + SSIM, `DEDUP_HIST_THRESHOLD=0.90`/`DEDUP_SSIM_THRESHOLD=0.92`) are fully implemented, unit-tested (`tests/test_dedup.py`, `tests/test_ssim.py`), and unused in production — dead code, not a removed feature.
  - `ocr.classify_slide_transition`/`dedupe_incremental_texts` (post-OCR, text-level dedupe) classify duplicate/incremental/new purely from OCR-text length growth (`INCREMENTAL_SLIDE_MIN_GROWTH=0.15`), independent of any image-level signal.
  - `ocr._ocr_paddle` (`lectural/ocr.py:309-324`) calls `paddleocr.PaddleOCR(...)` — a full model load — **inside the per-frame call**, and `ocr.ocr_frames` (`lectural/ocr.py:335-354`) calls it once per frame in a loop. PaddleOCR is therefore re-initialized for every representative frame in a run. This is the literal "repeatedly incurred OCR setup cost" the issue's Goal names.
  - `_ocr_paddle`'s PaddleOCR `.ocr()` call returns `(text, score)` per recognized line (`lectural/ocr.py:318-324`); only `line[1][0]` (text) is kept, `line[1][1]` (confidence) is discarded.
  - `_ocr_tesseract` (`lectural/ocr.py:327-332`) calls `pytesseract.image_to_string`, which returns no per-word confidence. `pytesseract.image_to_data` returns the same text plus per-word confidence at comparable cost.
  - No code currently records representative-frame width/height into `Frame.meta` or the evidence manifest, despite images already being opened (PIL in `ocr.py` preprocessing, cv2 in `visual._image_phash`) on every frame.
  - `docs/contracts/evidence.schema.json` has `"additionalProperties": true` at every relevant object (`extraction.ocr`, `representative_frames[].ocr`, `frame`, root) — a new field is additive and does not require an `EXTRACTION_CONTRACT_VERSION`/`EXTRACTION_SCHEMA_VERSION` bump.
  - `docs/reports/benchmark_stt_baseline_2026-09-19.md` (Issue #21, merged) already measured, on committed fixtures: clean video-slide OCR CER 0.384 (EN) / 0.538 (KO) / 0.483 (mixed); degraded-slide CER 0.027–0.185 (L1 moderate blur) vs 0.676–0.870 (L2 severe defocus); and `near_duplicate_dropped: true` on all three fixtures' `slide_02_near_dup.png` (a shifted/re-encoded duplicate) — i.e. the existing pHash path already resolves that specific near-dup shape. These are real anchors, not this plan's invention.
  - Issue vocabulary was unified before this plan (issue comment 2026-09-19): the reliability field name is `ocr.reliable`, not the issue's original "LLM usability"/"LLM context" wording (dropped as consumer-naming, inconsistent with this repo's positioning — see PR #28).
  - Sponsor/ad-likelihood was descoped from Issue #22 to a future issue (issue comment 2026-09-19); out of scope for this plan.

## Decision drivers
1. Issue #19's public contract (`extraction.ocr.status`, `representative_frames[].ocr.status`, both 4-valued enums) must not change value or meaning — only additive fields are allowed.
2. Real CER anchors exist (#21 baseline) — any reliability threshold must be validated against them, not chosen by feel.
3. The existing synthetic near-dup fixture already passes (`near_duplicate_dropped: true`); the 432.5–444s real-world case is a plausibly different failure mode (compression/OCR-noise-induced near-identity, not a shifted crop) and is not proven to be covered by that fixture. The fix must not regress the passing case while closing this gap.
4. Reuse existing, tested, unused code (`is_same_slide`, `select_keyframe_indices`) and an already-computed but discarded value (PaddleOCR confidence) before adding new dependencies or heuristics — matches the "avoid heuristics, prefer model-native/structural signals" direction from planning discussion.
5. The repeated-PaddleOCR-instantiation defect is a concrete, high-confidence, low-risk perf fix directly named by the issue's own Goal paragraph; it is not speculative.
6. Tesseract fallback currently cannot produce a reliability signal at all (no confidence in its current call shape) — this gap must be handled explicitly, not silently defaulted to `true` or `false`.

## Options considered

### Dedupe — Option A: tune pHash threshold/persistence only
Single global knob (`PHASH_HAMMING_THRESHOLD`/`PHASH_CHANGE_PERSISTENCE`). Cannot distinguish "compression noise changed the fingerprint but the slide is identical" from "the slide actually changed a little" — both are small pHash deltas. Tightening risks losing real incremental slides; loosening risks not fixing 432.5–444s. Rejected: doesn't add a signal, just moves one number blindly.

### Dedupe — Option B: replace pHash with hist/SSIM entirely
More structurally sensitive, but discards the fast first-pass pHash gives on every candidate frame before the expensive comparison, and needlessly touches the pHash-anchored tests in `tests/test_dedup.py`. Rejected: no evidence pHash's first pass is the problem; the STT baseline shows the coarse case pHash already catches.

### Dedupe — Option C (chosen): layer hist/SSIM as a confirming second opinion on pHash, and drive text-transition classification from structural diff instead of OCR-text-length growth
`is_same_slide` requires BOTH hist_corr and SSIM to clear their thresholds before calling two frames identical — a stricter, more structurally aware test than pHash's coarse fingerprint. Using it as an additional gate (a pHash-flagged "new slide" candidate must also structurally differ before being kept distinct) catches compression/noise-driven near-duplicates pHash's fingerprint treats as different, without discarding pHash's cheap first pass. Reuses existing tested code, adds no dependency, and the exact threshold is tuned against real fixtures rather than guessed. For the OCR-side classifier, using SSIM (already computed) instead of raw text-length growth removes OCR-accuracy noise (varies by language, font, engine) from a decision that is fundamentally about visual content, matching the planning discussion's generalization goal.

### Reliability signal — Option A: hand-rolled text heuristic (dictionary match, char-class ratio)
Rejected in planning discussion: language/domain-specific, does not generalize across EN/KO/mixed or non-lecture video-based work, duplicates effort the OCR engine already did internally.

### Reliability signal — Option B (chosen): PaddleOCR's own per-line confidence, aggregated per frame
Already computed on every OCR call, currently thrown away. A model-native uncertainty estimate generalizes across language/domain by construction. Threshold calibrated against #21's CER anchors (see Chosen approach).

## Chosen approach

### 1. Fix the repeated OCR engine setup (Requirements: "avoid repeated OCR setup cost")
Construct the `PaddleOCR(...)` engine once per `ocr_frames` call (or per run, if `ocr_frames` can be called more than once per process) and pass/reuse the instance instead of constructing it inside `_ocr_paddle` per frame. Preserve the existing fallback-to-Tesseract behavior and the `engine_used` return value unchanged.

### 2. Frame-level dedupe: pHash + structural confirmation
- Add a confirming check in `visual.dedupe_frames`: when `select_phash_keyframe_indices` confirms a persistence-gated candidate as a new slide, additionally require `not is_same_slide(hist_corr, ssim)` (computed via the existing `_pair_metrics`) between the candidate and the currently-kept slide before actually keeping it as distinct; otherwise treat it as a duplicate of the kept slide.
- Record the pHash distance, hist_corr, and SSIM values used for each decision in `frame.meta` (extends the existing `phash_hamming_from_previous` pattern) so the decision is auditable, not just a boolean.
- Add one or more new benchmark fixtures reproducing a compression/OCR-noise-induced near-duplicate (not a shifted crop) in `tests/fixtures/benchmark/`, alongside the existing near-dup fixture, so `duplicate_rate`/frame-recall in `scripts/benchmark.py` has a real positive for this failure mode. Exact threshold values (`PHASH_HAMMING_THRESHOLD`, `DEDUP_HIST_THRESHOLD`, `DEDUP_SSIM_THRESHOLD`) are tuned against this fixture set plus the existing `slide_02_near_dup.png` case, verified to keep `near_duplicate_dropped: true` on the latter while dropping the new noise-duplicate fixture and keeping any fixture with genuine incremental content change.

### 3. Text-transition classification: structural diff instead of OCR-text-length growth
`ocr.classify_slide_transition` currently decides duplicate/incremental/new from `INCREMENTAL_SLIDE_MIN_GROWTH` (text length ratio) alone. Replace its primary signal with the SSIM value between the two frames (already available from step 2's pairwise computation when both frames survive to the OCR/text stage); keep text-length growth only as a fallback when frame-pair structural data isn't available (defensive path, not the common case). This removes OCR-accuracy noise (which is language/engine-dependent) from a content-classification decision.

### 4. Reliability signal: PaddleOCR confidence, captured and thresholded
- In `_ocr_paddle`, keep each line's `(text, score)` pair; return (or attach to `Frame.meta["ocr_line_scores"]`) the per-line scores alongside the text.
- Aggregate per frame as the mean of line confidences (documented explicitly as mean, not min/percentile, with the reasoning: a frame with mostly-confident text and one noisy line should not be penalized as harshly as a uniformly noisy frame — open to revision if calibration data disagrees).
- Add `ocr.reliable: bool | null` to `representative_frames[].ocr` in `evidence.build_evidence_manifest` (`lectural/evidence.py`): `null` when `status` is `skipped`, `failed`, or `no-text` (reliability is undefined without text); a threshold-based boolean when `status == "text"`.
- Calibrate the confidence threshold against #21's CER anchors on the existing fixtures: clean video-slide OCR (CER 0.384–0.538) and degraded L1 (CER 0.027–0.185) vs. L2 (CER 0.676–0.870). The chosen threshold must classify L1-equivalent frames as reliable and L2-equivalent frames as not, and the plan records the resulting confidence-vs-CER correlation in `docs/benchmark_definition.md` (or a new report) rather than asserting the threshold without evidence — if PaddleOCR confidence does not correlate usefully with these CER anchors, that is a finding to report back before implementation proceeds, not a threshold to force.
- Tesseract fallback: switch `_ocr_tesseract` from `pytesseract.image_to_string` to `pytesseract.image_to_data`, which returns per-word confidence at comparable cost, so `ocr.reliable` is computable uniformly across both engines rather than silently `null` whenever the degraded fallback is active.

### 5. Mapping onto Issue #19's states (resolves the cold-read-flagged ambiguity)
- `extraction.ocr.status` (run-level: `skipped`/`completed-no-text`/`completed-with-text`/`failed`) — unchanged, execution axis.
- `representative_frames[].ocr.status` (per-frame: `skipped`/`text`/`no-text`/`failed`) — unchanged, detection axis.
- `representative_frames[].ocr.reliable` (new, per-frame, `bool | null`) — quality axis, only meaningful (non-null) when `status == "text"`.
No existing enum value changes; this is purely an additive third field.

### 6. Resolution metadata (Requirements: "record actual source and representative-frame resolution")
Capture width/height once per frame where the image is already opened for pHash computation (`visual._image_phash`) and store as `frame.meta["width"]`/`frame.meta["height"]`, independent of whether OCR runs (applies to `--skip-ocr` runs too). Surface as advisory fields on `representative_frames[]` in the evidence manifest. No gating change — sub-720p stays fully processable, matching the non-goal against a mandatory-720p floor.

## Contract and dependency impact
- `docs/contracts/evidence.schema.json`: add `reliable` (nullable boolean) under `representative_frames[].ocr`, and `width`/`height` (nullable integers) under `representative_frames[]`. Both additive (`additionalProperties: true` already permits this); `EXTRACTION_CONTRACT_VERSION`/`EXTRACTION_SCHEMA_VERSION` stay at `1`.
- `docs/contracts/cli.md`: document the two new fields and the mapping in Chosen-approach §5.
- No new runtime dependency. `pytesseract.image_to_data` ships in the already-depended-on `pytesseract` package.
- `lectural/config.py`: new named constant for the reliability confidence threshold (calibrated per §4, not a magic number), following the existing `DEDUP_HIST_THRESHOLD`-style pattern.
- No change to `synthesis_input.json`'s `SCHEMA_VERSION` unless synthesis is changed to read `ocr.reliable` when selecting trusted text for notes prose — if it is, that's a separate, explicit sub-decision recorded during implementation, not assumed here.

## Execution slices
1. Fix repeated PaddleOCR instantiation in `ocr.ocr_frames`/`_ocr_paddle` (isolated, independently verifiable perf fix; unit + benchmark evidence).
2. Add compression/noise-induced near-duplicate benchmark fixture(s); confirm current pHash-only behavior does or does not already catch it (baseline before touching dedupe logic).
3. Wire `is_same_slide` as a confirming gate in `visual.dedupe_frames`; tune thresholds against existing + new fixtures; verify `near_duplicate_dropped` stays `true` on the existing case.
4. Replace `classify_slide_transition`'s primary signal with structural diff; update `dedupe_incremental_texts` call sites; verify incremental-content fixtures are still kept.
5. Capture PaddleOCR per-line confidence; add `ocr.reliable` to the evidence manifest (nullable per §5); switch Tesseract to `image_to_data`.
6. Calibrate the reliability threshold against #21's CER anchors; document the correlation; add the named constant to `config.py`.
7. Capture and surface frame width/height.
8. Update `docs/contracts/evidence.schema.json` and `docs/contracts/cli.md`; add/extend contract tests.
9. Before/after benchmark run (`scripts/benchmark.py`, warm, `n=3`) covering OCR CPU, peak RAM, temp/final storage, wall time, plus the `--skip-ocr` on/off comparison already scoped by #21's harness.

## Verification
- `uv run --with pytest --with numpy pytest -q` stays green; new/changed unit tests in `tests/test_dedup.py`, `tests/test_ocr.py`, `tests/test_extraction_contract.py` cover: the structural confirming gate, the new fixture's dedupe outcome, `ocr.reliable` null/bool cases, width/height presence.
- `docs/contracts/evidence.schema.json` validates existing fixtures plus a fixture exercising the new fields; schema/contract tests pass.
- `scripts/benchmark.py --reps 3 --warm` (plus one `--skip-ocr` pair) before/after this change, on the existing EN/KO/mixed fixtures plus the new near-duplicate fixture, showing: `near_duplicate_dropped: true` preserved on the existing case, the new near-dup fixture also dropped, no incremental-content fixture regressed, reduced OCR CPU/wall time from the engine-reuse fix, and the reliability threshold's confidence-vs-CER correlation on the L1/L2/clean anchors.
- `lectural doctor` remains `ready`.
- A public CLI smoke result (`lectural extract <local fixture> --out ... --json`) showing the new `reliable`/`width`/`height` fields present and schema-valid.

## Rollout
No runtime-breaking change for existing consumers (additive fields only). `--skip-ocr` behavior unchanged except for the width/height metadata now also being present. Merges behind the normal PR gate.

## Rollback or mitigation
Revert the PR; no consumer contract narrows (fields were additive, never required). If the confidence-threshold calibration in slice 6 does not correlate usefully with CER on the available fixtures, `ocr.reliable` implementation is deferred and reported back to the maintainer rather than shipped with an unvalidated threshold — the rest of the plan (dedupe, engine-reuse, resolution metadata) is independently valuable and not blocked by it.

## Open decisions
- Exact aggregation method for per-frame confidence (mean vs. min vs. a low-percentile) — default to mean per §4, revisit if calibration data disagrees.
- Exact new threshold values for `PHASH_HAMMING_THRESHOLD`/`DEDUP_HIST_THRESHOLD`/`DEDUP_SSIM_THRESHOLD` and the new reliability-confidence constant — determined empirically in execution slices 3 and 6, not fixed here.
- Whether `synthesis.py` should start reading `ocr.reliable` to gate which OCR text enters `notes.md` prose — out of this plan's scope unless the maintainer asks for it; the field's existence doesn't require a synthesis-side consumer yet.
- "Maintainer-approved" recall/timestamp-integrity/accepted-OCR limits (Acceptance criteria) — need an explicit number from the maintainer before slice 9's benchmark run can be judged pass/fail; proposed default is "no regression vs. the #21 baseline report's corresponding metrics," pending confirmation.

## Pre-mortem
Not required (risk:medium, not risk:high per issue label). The main credible failure mode — a reliability threshold that doesn't actually correlate with real OCR error — is addressed structurally in Chosen-approach §4 and the Rollback section (deferred and reported, not shipped unvalidated).
