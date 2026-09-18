# Plan: Deliver efficient and trustworthy visual evidence

## Inputs
- Issue: #22 (haesol-shin/lectural)
- Specification: none (issue is the contract)
- Research:
  - Read `lectural/visual.py`, `lectural/ocr.py`, `lectural/evidence.py`, `lectural/cli.py`, `lectural/synthesis.py`, `lectural/media.py`, `lectural/source.py`, `docs/contracts/evidence.schema.json` end to end.
  - `visual.dedupe_frames` (the only dedupe path wired into `ocr_frames`) uses pHash (64-bit DCT, `PHASH_HAMMING_THRESHOLD=12`, 2-frame persistence gate) only. `is_same_slide`/`select_keyframe_indices` (hist_corr + SSIM, `DEDUP_HIST_THRESHOLD=0.90`/`DEDUP_SSIM_THRESHOLD=0.92`) are fully implemented, unit-tested (`tests/test_dedup.py`, `tests/test_ssim.py`), and unused in production.
  - `ocr._ocr_paddle` (`lectural/ocr.py:309-324`) constructs `paddleocr.PaddleOCR(...)` inside the per-frame call, and `ocr.ocr_frames` (`lectural/ocr.py:335-354`) calls it once per frame in a loop — the engine is re-initialized per representative frame. `_ocr_paddle`'s `.ocr()` call returns `(text, score)` per line (`lectural/ocr.py:318-324`); only text is kept, the score is discarded.
  - `ocr.classify_slide_transition` (`lectural/ocr.py:30-60`) is **not** pure text-length growth as first assumed: it already does normalized-equality, then a superset/prefix line-containment check, and applies the `INCREMENTAL_SLIDE_MIN_GROWTH` (0.15) ratio only inside that contained/prefix branch; unrelated content returns `new` regardless of length. A structural (SSIM) signal cannot by itself replace this — it cannot tell "incremental build" from "new slide" (both are visually different from the previous frame). Revised plan below layers SSIM as a *duplicate override*, not a wholesale replacement.
  - `cli.py:347-355` builds `slide_dicts` (`ocr_text`, `frame`, `is_slide`) that feed `synthesis.build_synthesis_input` → `synthesis_input.json`; `synthesis.build_section_hints` (`lectural/synthesis.py:71-102`) uses `ocr_text` for section titles. `synthesis_input.json` is the only input the command-driven host-agent enrichment step (`AGENTS.md` → `skills/lectural/references/summary_prompt.md`) reads to write `notes.md` prose. A `reliable`-only field on `evidence.json`'s `representative_frames[]` does **not** reach this path — `synthesis_input.json` is a separate artifact built from `slide_dicts`, not derived from `evidence.json`.
  - `pytesseract.image_to_string` and `pytesseract.image_to_data` are documented as separate output modes with different reconstruction risk: `image_to_data` returns TSV rows (box + confidence per word/line), and rebuilding a text string from those rows can alter whitespace/line breaks versus `image_to_string`'s direct text output. Preserving raw OCR (an explicit Requirement) means the existing `image_to_string` call must stay as the text source; confidence needs a **second**, additional `image_to_data` call, not a replacement call.
  - `lectural.media.SourceMetadata` (`lectural/media.py:20-24`) has no width/height field. `parse_ytdlp_metadata` (`lectural/media.py:42-58`) does not extract yt-dlp's `width`/`height` JSON fields (present in `yt-dlp --dump-json` output) even though they are available. `_probe_local_video`/`_probe_local_audio` (`lectural/media.py:89-95`) do not call ffprobe at all today — local source resolution is not read anywhere. `InputSource.safe_as_dict()` (`lectural/source.py:90-109`) — the dict that becomes `evidence.json`'s `"source"` field — has a fixed shape with no resolution field.
  - `visual._image_phash` (`lectural/visual.py:362-388`) decodes each candidate frame image once, downsampled to a 32×32 grayscale array (too small to be a meaningful hist/SSIM input). `visual._pair_metrics` (`lectural/visual.py:281-303`) independently re-decodes both compared images from disk at a different (near-original) resolution for hist_corr/SSIM. Naively adding a `_pair_metrics` confirming pass after `select_phash_keyframe_indices` **increases** total decode count (contradicts the Requirement to reduce unnecessary decoding), since each candidate frame would be read from disk again.
  - `docs/contracts/evidence.schema.json` has `"additionalProperties": true` at every relevant object (`extraction.ocr`, `representative_frames[].ocr`, `frame`, root) — new fields there are additive.
  - `docs/reports/benchmark_stt_baseline_2026-09-19.md` (Issue #21, merged) measured on committed fixtures: clean video-slide OCR CER 0.384 (EN) / 0.538 (KO) / 0.483 (mixed); degraded-slide CER 0.027–0.185 (L1 moderate blur) vs. 0.676–0.870 (L2 severe defocus); `near_duplicate_dropped: true` on all three fixtures' `slide_02_near_dup.png` (a shifted/re-encoded duplicate).
  - **Checked for archived frames matching the issue's cited 432.5–444s real-duplicate case**: no output directory in this repository has a 555-second duration (`output/perf-smoke/19vYXnpDIyg` is a different, degraded June-14 run with `duration_sec: 0.0` and only 20 slide frames — FasterWhisper/webrtcvad were missing in that run per its own `perf_metrics.json`; other archived `output/*` runs are 367s). **The actual clip/frames behind the issue's 432.5–444s observation are not in this repository.** This is an open gap requiring a maintainer decision (see Open decisions), not something more code-reading resolves.
  - Issue vocabulary unified before this plan (issue comment 2026-09-19): the reliability field is `ocr.reliable`, not "LLM usability"/"LLM context". Sponsor/ad-likelihood descoped to a future issue (issue comment 2026-09-19); out of scope here.

## Decision drivers
1. Issue #19's public contract (`extraction.ocr.status`, `representative_frames[].ocr.status`, both 4-valued enums) must not change value or meaning — only additive fields are allowed.
2. Real CER anchors exist (#21 baseline) — any reliability threshold must be validated against them.
3. The existing synthetic near-dup fixture already passes (`near_duplicate_dropped: true`); the true 432.5–444s case's frames are not available in-repo, so this plan cannot claim to reproduce *that exact* case — only a documented proxy, pending maintainer input.
4. Reuse existing, tested, unused code (`is_same_slide`) and an already-computed but discarded value (PaddleOCR confidence) before adding heuristics or dependencies.
5. "Trusted synthesis input" is a separate artifact (`synthesis_input.json`) from the evidence manifest (`evidence.json`) — a reliability gate that only touches `evidence.json` does not satisfy the Requirement; both must be addressed.
6. Preserving raw OCR text (explicit Requirement) constrains the Tesseract confidence fix to an *additional* call, not a replacement of the existing text-producing call.
7. Reducing "unnecessary decoding" (explicit Requirement) means any new image comparison must not add a second disk-decode of frames already decoded for pHash.
8. A required Acceptance criterion (independently machine-readable reliability) cannot be quietly dropped if calibration is inconclusive — that must block and return to planning, not ship a partial result silently.

## Options considered

### Dedupe/classification — Option A: tune pHash threshold/persistence only
Single global knob. Cannot distinguish "compression noise changed the fingerprint" from "the slide actually changed a little" — both are small pHash deltas. Rejected: doesn't add a signal, just moves one number blindly.

### Dedupe/classification — Option B: replace pHash and text-containment logic with SSIM end to end
Rejected on two independent grounds found during research: (a) discards pHash's cheap first pass on every candidate frame without evidence it is the problem (the STT baseline shows pHash already resolves the fixture's near-dup case); (b) SSIM alone cannot distinguish "incremental build" from "brand-new slide" — that distinction is inherently about text content (is the new text a superset of the old?), not pixel structure, so a full replacement would silently break the existing, tested incremental-slide-keep behavior.

### Dedupe/classification — Option C (chosen): layer `is_same_slide` as a *duplicate override* on both the image-level dedupe and the text-level classifier, with single-pass decode reuse
At the image level: when pHash's persistence gate confirms a candidate as visually "different," additionally require `not is_same_slide(hist_corr, ssim)` before keeping it as a distinct slide — otherwise it is folded into the previous kept slide as a duplicate. This targets exactly the failure mode pHash's coarse fingerprint misses (near-identical frames whose hash still crossed the distance threshold), while leaving pHash's role as the cheap first pass untouched.
At the text level: keep `classify_slide_transition`'s existing containment/prefix/growth logic (it correctly distinguishes incremental-vs-new by content), but add one override: if the frame pair backing the comparison is image-near-identical (`is_same_slide` true) yet the text differs (OCR noise), force `duplicate` regardless of what the text-only classifier would return. This fixes OCR-noise-induced false "new"/"incremental" calls without discarding the text logic needed to correctly keep genuine incremental builds.
Decode reuse: read each candidate frame's image bytes from disk exactly once per `dedupe_frames` call (cache by path within that call), deriving both the 32×32 pHash input and the near-original-resolution hist/SSIM input from that single decode, instead of separate `_image_phash` and `_pair_metrics` disk reads. This nets fewer decodes than today for any frame compared more than once (adjacent-pair comparisons reuse the previous frame's cached decode), satisfying the "reduce unnecessary decoding" Requirement instead of adding to it.

### Reliability signal — Option A: hand-rolled text heuristic (dictionary match, char-class ratio)
Rejected in planning discussion: language/domain-specific, does not generalize, duplicates work the OCR engine already did internally.

### Reliability signal — Option B (chosen): PaddleOCR's own per-line confidence, aggregated per frame; Tesseract confidence via an additional `image_to_data` call
Model-native uncertainty estimate, already computed once per PaddleOCR call and currently discarded — no new cost there. For Tesseract (rare, already-labeled degraded fallback path), keep the existing `image_to_string` call as the unmodified raw-text source (preserves the Requirement), and add a second `image_to_data` call solely to derive a confidence aggregate; this doubles Tesseract's own cost on that one rare branch, which is an explicit, accepted, and documented tradeoff — it does not touch the dominant PaddleOCR cost path this issue is actually about.

## Chosen approach

### 1. Fix repeated PaddleOCR engine construction (Requirement: avoid repeated OCR setup cost)
Construct the `PaddleOCR(...)` engine once per `ocr_frames` call and reuse it across all frames in that call, instead of inside `_ocr_paddle` per frame. Preserve the existing Tesseract-fallback behavior and `engine_used` return value unchanged.

### 2. Single-pass frame decode + image-level dedupe confirmation
Add a per-`dedupe_frames`-call decode cache keyed by frame path; derive pHash and hist/SSIM inputs from one disk read per unique frame. Wire `is_same_slide` as a confirming duplicate-override gate on `select_phash_keyframe_indices`'s persistence-confirmed candidates, per Option C above. Record pHash distance, hist_corr, and SSIM in `frame.meta` for each decision (extends the existing `phash_hamming_from_previous` pattern) so the outcome is auditable.

### 3. Text-transition classifier: duplicate override, not replacement
Add the image-near-identical duplicate override described in Option C to `classify_slide_transition`/`dedupe_incremental_texts`, reusing the same `is_same_slide` result computed in step 2 for the same frame pair (no extra decode). All existing containment/prefix/growth branches stay as-is.

### 4. Reliability signal (`ocr.reliable`), gated all the way to trusted synthesis input
- In `_ocr_paddle`, retain each line's `(text, score)`; aggregate per frame as the mean of line confidences (documented rationale: a mostly-confident frame with one noisy line should not be penalized as harshly as a uniformly noisy frame; revisit if calibration disagrees).
- Add `ocr.reliable: bool | null` to `representative_frames[].ocr` in `evidence.build_evidence_manifest`: `null` when `status` is `skipped`/`failed`/`no-text` (undefined without text), a threshold-based boolean when `status == "text"`. `evidence.json`'s raw `text` field is never filtered — the Requirement to preserve raw OCR applies there.
- **Also** change `cli.py`'s `slide_dicts` construction: when a slide frame's OCR is not reliable, its `ocr_text` in `synthesis_input.json` is set to `""` (the same convention `ocr.ocr_frames` already uses for non-slide frames), so unreliable text does not reach `build_section_hints` or the host-agent synthesis prompt. This is the change that actually satisfies "excluding low-quality text from trusted synthesis input" — a reliable-flag on `evidence.json` alone does not, since `synthesis_input.json` is a separately built artifact. No `SCHEMA_VERSION` bump: `slides[].ocr_text`'s type and meaning (best-available slide text, possibly empty) are unchanged, only its population rule gains a new condition, consistent with the existing `is_slide` gate already using the same empty-string convention.
- Tesseract: keep the existing `image_to_string` call as the unmodified text source; add a second `pytesseract.image_to_data(..., output_type=Output.DICT)` call to compute a confidence aggregate (mean of non-negative `conf` entries), used only for `ocr.reliable`, never to reconstruct text.
- Calibrate the confidence threshold against #21's CER anchors: L1 blur (CER 0.027–0.185) should classify reliable, L2 defocus (CER 0.676–0.870) should not; the clean video-slide baseline (CER 0.384–0.538) is a mid-range case to inspect closely. The resulting confidence-vs-CER correlation is recorded in `docs/benchmark_definition.md` (or a new report), not asserted without evidence.
- **If PaddleOCR confidence does not correlate usefully with the CER anchors**, this blocks the PR and returns to planning for another validated signal (or a maintainer-approved formal re-scope) — it is not shipped as a silently omitted field, because independently machine-readable reliability is a required Acceptance criterion, not an optional enhancement.

### 5. Mapping onto Issue #19's states
- `extraction.ocr.status` (run-level, unchanged) — execution axis.
- `representative_frames[].ocr.status` (per-frame, unchanged) — detection axis.
- `representative_frames[].ocr.reliable` (new, per-frame, `bool | null`) — quality axis, meaningful only when `status == "text"`.
No existing enum value changes; purely additive.

### 6. Source and representative-frame resolution (Requirement: record actual source and representative-frame resolution)
- Representative-frame resolution: captured once per frame as part of step 2's single decode pass, stored as `frame.meta["width"]`/`["height"]`, surfaced as advisory fields on `representative_frames[]` in the evidence manifest. Applies independent of `--skip-ocr`.
- **Source resolution** (the input video's own dimensions, distinct from retained-frame dimensions — the critic finding this plan's first draft omitted entirely): extend `SourceMetadata` with `width: int | None` / `height: int | None`. For YouTube, extract yt-dlp's existing `width`/`height` JSON fields in `parse_ytdlp_metadata` (no new network call). For local video, add an ffprobe call in `_probe_local_video` (ffprobe already ships with the required `ffmpeg` binary; no new dependency) to read stream resolution. For local audio, both are `None` (no video stream — matches the existing "not applicable" pattern for visual completeness on `local_audio`). Merge into `evidence.json`'s `"source"` field at the `cli.py` call site (`{**source.safe_as_dict(), "resolution": {"width": ..., "height": ...}}`) rather than changing `InputSource.safe_as_dict()`'s own fixed shape, since `InputSource` is built before probing and does not itself know resolution.
- No gating change: sub-720p stays fully processable (non-goal against a mandatory-720p floor unaffected).

## Contract and dependency impact
- `docs/contracts/evidence.schema.json`: add `reliable` (nullable boolean) under `representative_frames[].ocr`, `width`/`height` (nullable integers) under `representative_frames[]`, and `resolution` (object with nullable `width`/`height`) under `source`. All additive; `EXTRACTION_CONTRACT_VERSION`/`EXTRACTION_SCHEMA_VERSION` stay at `1`.
- `docs/contracts/cli.md`: document the new fields and the Issue #19 state mapping (§5).
- No new runtime dependency: `pytesseract.image_to_data` ships with the already-depended-on `pytesseract`; ffprobe ships with the already-required `ffmpeg` binary.
- `lectural/config.py`: new named constant(s) for the reliability confidence threshold and (if changed from current values) the dedupe thresholds, following the existing `DEDUP_HIST_THRESHOLD`-style pattern — no magic numbers.
- `synthesis_input.json`'s `SCHEMA_VERSION` (currently 2) is unaffected per §4's reasoning (population-rule change, not shape change) — flagged explicitly here so a reviewer can check that reasoning rather than assume it.

## Execution slices
1. Fix repeated PaddleOCR instantiation in `ocr.ocr_frames`/`_ocr_paddle` (isolated, independently verifiable perf fix).
2. Single-pass decode cache in `visual.dedupe_frames`; wire `is_same_slide` as the confirming duplicate-override gate; record decision metadata in `frame.meta`.
3. Add the same duplicate-override to `classify_slide_transition`/`dedupe_incremental_texts`, reusing step 2's `is_same_slide` result for the same frame pair.
4. Add a compression/OCR-noise-induced near-duplicate benchmark fixture (documented as a proxy, not the verified real case — see Open decisions); verify current pHash-only behavior against it before and after steps 2–3; verify `near_duplicate_dropped` stays `true` on the existing shifted-crop fixture and incremental-content fixtures are not regressed.
5. Capture PaddleOCR per-line confidence; add `ocr.reliable` to the evidence manifest per §5's nullability rule; switch `_ocr_tesseract` to also call `image_to_data` for confidence (text source unchanged).
6. Gate `synthesis_input.json`'s `slide_dicts[].ocr_text` on `ocr.reliable` in `cli.py`, matching the existing `is_slide` empty-string convention.
7. Calibrate the reliability threshold against #21's CER anchors; document the correlation; add the named constant to `config.py`; if calibration is inconclusive, stop and report back per Decision driver 8 rather than proceeding.
8. Extend `SourceMetadata` with width/height; extract yt-dlp's existing fields; add ffprobe-based local-video probing; merge into `evidence.json`'s `source.resolution`.
9. Update `docs/contracts/evidence.schema.json` and `docs/contracts/cli.md`; extend contract tests.
10. Before/after benchmark run (`scripts/benchmark.py`, warm, `n=3`) covering OCR CPU, peak RAM, temp/final storage, decode count, wall time, plus the `--skip-ocr` on/off comparison already scoped by #21's harness.

## Verification
- `uv run --with pytest --with numpy pytest -q` stays green; new/changed unit tests in `tests/test_dedup.py`, `tests/test_ocr.py`, `tests/test_extraction_contract.py` cover: the duplicate-override gate (image-level and text-level), the new fixture's dedupe outcome, `ocr.reliable` null/bool cases, the `synthesis_input.json` gating (a known-noisy fixture's text is empty in `slides[]` but present, unfiltered, in `evidence.json`), width/height presence for both source and representative frames.
- `docs/contracts/evidence.schema.json` validates existing fixtures plus a fixture exercising every new field; schema/contract tests pass.
- `scripts/benchmark.py --reps 3 --warm` (plus one `--skip-ocr` pair) before/after this change, on the existing EN/KO/mixed fixtures plus the new near-duplicate fixture, showing: `near_duplicate_dropped: true` preserved on the existing case, the new near-dup fixture also dropped, no incremental-content fixture regressed, reduced OCR CPU/wall time from the engine-reuse fix, reduced (not increased) visual-stage decode count, and the reliability threshold's confidence-vs-CER correlation on the L1/L2/clean anchors.
- Explicit pass/fail rule for slice 10 (replacing the first draft's unconfirmed "no regression" placeholder): for each of the three repeated runs, the **median** of OCR CPU-seconds and wall-time must not exceed the corresponding #21 baseline-report value; recall/duplicate-rate/timestamp-integrity metrics must not fall below their #21 baseline-report value on the equivalent fixture. The tolerance band around "must not exceed/fall below" (e.g. exact percentage) is a pending maintainer decision (see Open decisions) — the *statistic and comparison rule* are fixed here so slice 10 has a determinate structure to execute against once that number is supplied.
- `lectural doctor` remains `ready`.
- A public CLI smoke result (`lectural extract <local fixture> --out ... --json`) showing the new `reliable`, `width`/`height`, and `source.resolution` fields present and schema-valid.

## Rollout
No runtime-breaking change for existing consumers (additive fields only). `--skip-ocr` behavior unchanged except width/height metadata now also present. Merges behind the normal PR gate.

## Rollback or mitigation
Revert the PR; no consumer contract narrows (fields were additive, never required). **Unlike this plan's first draft, an inconclusive reliability-threshold calibration is not a silent-ship condition**: per Decision driver 8, it sets the work to blocked and returns to planning for a different validated signal or a maintainer-approved formal re-scope of Issue #22's acceptance criteria. The dedupe/decode/engine-reuse/resolution-metadata slices are independently valuable and not gated on the reliability signal succeeding, but the PR as a whole does not close Issue #22 without it.

## Open decisions
- **Requires maintainer input before this plan can be marked Ready:**
  - The tolerance/statistic for "maintainer-approved" recall/timestamp-integrity/accepted-OCR limits (Acceptance criteria) — this plan fixes the *comparison rule* (median of 3 runs vs. #21 baseline, per Verification) but the numeric tolerance is still open.
  - **The real 432.5–444s duplicate case's source frames are not present in this repository** (confirmed by checking every archived `output/*` run's duration). Options: (a) the maintainer supplies the original clip/frames from that run so the fixture is a verified reproduction, not a proxy; (b) the plan proceeds with a documented synthetic proxy and this is recorded as a known evidence gap in the eventual PR, not silently presented as a verified fix.
- Exact aggregation method for per-frame confidence (mean vs. min vs. a low-percentile) — default mean per §4, revisit if calibration data disagrees.
- Exact new threshold values for `PHASH_HAMMING_THRESHOLD`/`DEDUP_HIST_THRESHOLD`/`DEDUP_SSIM_THRESHOLD` and the new reliability-confidence constant — determined empirically in execution slices 4 and 7.
- Whether other `notes.md`-facing code beyond `build_section_hints` (e.g. any direct frame/OCR-text rendering) also needs the reliability gate — slice 6 covers the confirmed path; if review finds another path, it is added to the same slice rather than a follow-up.

## Pre-mortem
Not required (risk:medium, not risk:high per issue label). The main credible failure mode — a reliability threshold that doesn't actually correlate with real OCR error — is addressed structurally in Chosen-approach §4 and the Rollback section (blocks and returns to planning, not shipped unvalidated).
