# Plan: Deliver efficient and trustworthy visual evidence

## Inputs
- Issue: #22 (haesol-shin/lectural)
- Specification: none (issue is the contract)
- Research:
  - Read `lectural/visual.py`, `lectural/ocr.py`, `lectural/evidence.py`, `lectural/cli.py`, `lectural/synthesis.py`, `lectural/media.py`, `lectural/source.py`, `docs/contracts/evidence.schema.json` end to end.
  - `visual.dedupe_frames` (the only dedupe path wired into `ocr_frames`) uses pHash (64-bit DCT, `PHASH_HAMMING_THRESHOLD=12`, 2-frame persistence gate) only, and runs **before** OCR in the pipeline. `is_same_slide`/`select_keyframe_indices` (hist_corr + SSIM) are implemented, unit-tested, and unused in production.
  - `ocr._ocr_paddle` (`lectural/ocr.py:309-324`) constructs `paddleocr.PaddleOCR(...)` inside the per-frame call; `ocr.ocr_frames` (`lectural/ocr.py:335-354`) calls it once per frame in a loop. `.ocr()` returns `(text, score)` per line; only text is kept today.
  - **Data-flow boundaries that constrain the reliability signal's design** (round-2 finding): `_ocr_paddle`/`_ocr_tesseract` currently return text only; `ocr_image` returns `(text, engine)`; `Frame` (`lectural/visual.py:28-34`) has no confidence field; `cli.py` builds two independent dict lists from `Frame` objects — `slide_dicts` (`cli.py:347-355`, feeds `synthesis_input.json`) and `representative_frame_dicts` (`cli.py:396-404`, feeds `evidence.build_evidence_manifest`). A reliability value computed inside `_ocr_paddle` reaches neither consumer unless it is threaded through every one of these boundaries explicitly.
  - `evidence.build_evidence_manifest` passes the `source` dict through `_safe_source` (`lectural/evidence.py:175-191`) before it reaches the public manifest. `_safe_source` returns a **fixed**, hand-enumerated shape (`kind`, `argument`, `has_video`, `citation`) — it does not pass through unknown keys. Any new `source.resolution` field added only at the `cli.py` call site is silently dropped here unless `_safe_source` itself is extended to copy it.
  - `ocr.classify_slide_transition` (`lectural/ocr.py:30-60`) already does normalized-equality, then superset/prefix line-containment, applying the length-growth ratio only inside that branch; unrelated content returns `new` regardless of length. Because image-level dedupe (`dedupe_frames`) already runs before any frame reaches OCR, a frame pair that is "OCR-noise-near-identical" would already have been merged at the image level if it is also visually near-identical — a *second*, OCR-side structural override would either be redundant with the image-level gate or (per round-2 finding) structurally unreachable, since `dedupe_incremental_texts` compares OCR-qualified/kept slides, not necessarily the same adjacent pairs `dedupe_frames` compared, and no decode cache survives across that module boundary. **This plan therefore does not add a text-level structural override** — the image-level gate (Chosen approach §2) is the single dedupe decision point; `classify_slide_transition` is unchanged.
  - `pytesseract` (pinned per `pyproject.toml`) exposes `run_and_get_multiple_output(image, extensions=[...], lang=...)`, which runs Tesseract **once** and returns multiple output formats (e.g. `txt` and `tsv`) from that single invocation — confirmed against the installed version's documented API. This avoids a second Tesseract process per frame.
  - `media._download_video` (`lectural/media.py:171-183`) selects YouTube video with `-f "bestvideo[height<=720]+bestaudio/best"`. A separate, unconstrained `yt-dlp --dump-json` metadata call (`fetch_video_metadata`) can report a different resolution than the format actually selected and downloaded for frame extraction — reporting the metadata call's `width`/`height` as "source resolution" would not describe the video actually processed. Source resolution must be probed from the **downloaded** file (ffprobe, same mechanism as local video), not a separate metadata field.
  - A path-keyed, call-wide decode cache retaining every candidate frame's near-original-resolution array at once is a real peak-RAM risk: at the issue's own cited scale (1,110 candidate frames), even modest frame dimensions accumulate to multiple gigabytes of resident arrays before any OpenCV/SSIM temporaries — directly conflicting with the Requirement to avoid an unacceptable peak-RAM increase. `select_phash_keyframe_indices`'s actual algorithm (`lectural/visual.py:77-120`) only ever needs the *currently kept* slide's decoded data and the *current candidate's* decoded data at any one time (it is a strictly sequential, single-pass scan) — so the cache only needs to be bounded to O(1) frames, not O(N).
  - `docs/contracts/evidence.schema.json` has `"additionalProperties": true` at every relevant object — new fields there are additive.
  - `docs/reports/benchmark_stt_baseline_2026-09-19.md` (Issue #21, merged): clean video-slide OCR CER 0.384 (EN) / 0.538 (KO) / 0.483 (mixed); degraded-slide CER 0.027–0.185 (L1 moderate blur) vs. 0.676–0.870 (L2 severe defocus); `near_duplicate_dropped: true` on all three fixtures' shifted/re-encoded duplicate.
  - **No archived output in this repository has a ~555-second duration** (checked every `output/*` run; closest are a 367s run and a degraded, speech-incomplete June-14 run). The actual clip/frames behind the issue's cited 432.5–444s observation are not available in-repo — an open gap for the maintainer, not something further code-reading resolves.
  - Issue vocabulary unified before this plan (issue comment 2026-09-19): reliability field is `ocr.reliable`. Sponsor/ad-likelihood descoped to a future issue (issue comment 2026-09-19).
  - **Revision history**: round 1 of plan-critic review found 7 gaps (synthesis-input gating missing, source dimensions missing, reliability deferrable in rollback, acceptance thresholds unresolved, real 432.5–444s case unreproduced, decode count increase, inaccurate Tesseract/classifier claims) — addressed in the first revision. Round 2 found the first revision's fixes were incomplete in execution: `_safe_source` still drops resolution, the reliability signal had no defined transport path, the text-level "override" was unreachable, the decode cache was unbounded, Tesseract used two calls where one suffices, and YouTube resolution could mismatch the processed video. This is the round-3 revision addressing those six.

## Decision drivers
1. Issue #19's public contract (`extraction.ocr.status`, `representative_frames[].ocr.status`) must not change value or meaning — additive fields only.
2. Real CER anchors exist (#21 baseline) — any reliability threshold must be validated against them.
3. The true 432.5–444s case's frames are not available in-repo; this plan cannot claim to reproduce *that exact* case, only a documented proxy pending maintainer input.
4. Reuse existing, tested, unused code (`is_same_slide`) and an already-computed but discarded value (PaddleOCR confidence) before adding heuristics or dependencies.
5. "Trusted synthesis input" (`synthesis_input.json`) is a separate artifact from `evidence.json` built from a separate dict (`slide_dicts` vs. `representative_frame_dicts`) — any new signal must be explicitly threaded to both, not assumed to reach both from one change.
6. Every new field must be traced through to its actual public-manifest sanitizer (`_safe_source`, `build_evidence_manifest`'s per-frame loop) — a value computed deep in the pipeline is not "in the contract" until it survives the sanitizing boundary closest to the JSON output.
7. Peak RAM is an explicit benchmark gate; any new per-frame data retained across a whole `dedupe_frames` call must be bounded (O(1) frames resident), not accumulated across all candidates (O(N)).
8. Preserving raw OCR text (Requirement) and minimizing added engine invocations (Requirement: avoid unnecessary cost) both point to single-call APIs where the OCR library offers one (`pytesseract.run_and_get_multiple_output`).
9. A required Acceptance criterion (independently machine-readable reliability) cannot be quietly dropped if calibration is inconclusive — blocks and returns to planning instead.
10. Reported "source resolution" must describe the video actually processed (the downloaded/selected format), not an independently-fetched metadata field that can diverge from it.

## Options considered

### Dedupe — Option A: tune pHash threshold/persistence only
Single global knob, cannot distinguish compression-noise deltas from real small content changes. Rejected.

### Dedupe — Option B: replace pHash and text logic with SSIM end to end
Discards pHash's cheap first pass without evidence it's the problem; SSIM alone cannot distinguish "incremental build" from "new slide" (a content-containment question, not a pixel-structure one). Rejected.

### Dedupe — Option C (chosen, revised): `is_same_slide` as a bounded, streaming confirming gate at the image level only
When pHash's persistence gate confirms a candidate as visually "different," additionally require `not is_same_slide(hist_corr, ssim)` (from a **bounded, O(1)-resident** decode: only the currently-kept slide's and the current candidate's near-original arrays need to exist at once, matching `select_phash_keyframe_indices`'s strictly sequential scan) before keeping it as distinct; otherwise fold it into the kept slide as a duplicate. **No corresponding change at the OCR/text level** — a second override there was found unreachable/redundant in round-2 review and is dropped; `classify_slide_transition` stays exactly as it is today.

### Reliability signal — Option A: hand-rolled text heuristic
Rejected: language/domain-specific, doesn't generalize, duplicates work the OCR engine already did.

### Reliability signal — Option B (chosen, revised): PaddleOCR's own per-line confidence, threaded through an explicit data path; Tesseract confidence via `run_and_get_multiple_output`
Model-native, already computed once per PaddleOCR call. Explicit transport: `_ocr_paddle`/`_ocr_tesseract` return `(text, confidence: float | None)`; `ocr_image` returns `(text, engine, confidence)`; `Frame` gains `ocr_confidence: float | None`; `ocr_frames` sets it once per frame. Both `cli.py` dict-builders (`slide_dicts`, `representative_frame_dicts`) read `frame.ocr_confidence` independently — this is what makes both `evidence.json` and `synthesis_input.json` actually receive the signal, per Decision driver 5. Tesseract uses `run_and_get_multiple_output(image, extensions=["txt", "tsv"], lang=...)`: the `txt` result is the unmodified raw-text source (preserves the Requirement), the `tsv` result's non-negative `conf` column feeds the same confidence aggregation as PaddleOCR — one Tesseract invocation, not two.

## Chosen approach

### 1. Fix repeated PaddleOCR engine construction (Requirement: avoid repeated OCR setup cost)
Construct `PaddleOCR(...)` once per `ocr_frames` call, reused across all frames in that call. `engine_used` return value and Tesseract-fallback behavior unchanged.

### 2. Bounded, streaming image-level dedupe confirmation
Rework `visual.dedupe_frames`/`select_phash_keyframe_indices` to decode at most two frames' near-original arrays at a time (the current kept slide's, and the current candidate's), deriving the 32×32 pHash input from the same decode rather than a separate disk read. When pHash confirms a persistence-gated candidate as new, additionally require `not is_same_slide(hist_corr, ssim)` computed from these two resident arrays before actually keeping it as distinct. Evict the previous kept slide's array once a new one is confirmed kept, so peak resident decoded-image memory stays O(1) regardless of candidate-frame count (fixes the round-2 multi-gigabyte risk). Record pHash distance, hist_corr, and SSIM in `frame.meta` for each decision.

### 3. Text-transition classifier: unchanged
Per round-2 finding, no text-level structural override is added; `classify_slide_transition`/`dedupe_incremental_texts` are untouched by this plan. The image-level gate in §2 is the single dedupe decision point.

### 4. Reliability signal (`ocr.reliable`), threaded end to end, gated at both consumers
- `_ocr_paddle` returns `(text, confidence)` — confidence is the mean of per-line scores from the existing `.ocr()` call (no new PaddleOCR cost).
- `_ocr_tesseract` uses `run_and_get_multiple_output(image, extensions=["txt", "tsv"], lang="kor+eng")`: returns `(txt_result, confidence)`, confidence from the mean of non-negative `conf` values in the `tsv` result. `txt_result` is returned exactly as before — no reconstruction from TSV rows, so raw text is unmodified.
- `ocr_image` returns `(text, engine, confidence)`; `ocr_frames` sets `frame.ocr_confidence` (new `Frame` field, default `None`) once per frame from that return.
- `cli.py`'s `representative_frame_dicts` (`cli.py:396-404`) adds `"reliable": <threshold check on frame.ocr_confidence, or None>` (`None` when `ocr_status` is `skipped`/`failed` or the frame has no text) and `"width"`/`"height"` from `frame.meta` (see §6). `evidence.build_evidence_manifest`'s per-frame loop reads these and places them on `representative_frames[].ocr.reliable`/`representative_frames[].width`/`.height` — `evidence.json`'s raw `text` field is never filtered.
- `cli.py`'s `slide_dicts` (`cli.py:347-355`) independently reads the **same** `frame.ocr_confidence`/threshold to decide `ocr_text`: unreliable → `""` (same empty-string convention `ocr_frames` already uses for non-slide frames), reliable → the actual text. This is what satisfies "excluding low-quality text from trusted synthesis input," since `synthesis_input.json` is built from this dict, not from `evidence.json`. No `SCHEMA_VERSION` bump: `slides[].ocr_text`'s type/meaning is unchanged, only its population rule gains a condition.
- Calibrate the confidence threshold against #21's CER anchors (L1 blur CER 0.027–0.185 → reliable; L2 defocus CER 0.676–0.870 → not; clean-slide CER 0.384–0.538 inspected closely); record the confidence-vs-CER correlation in `docs/benchmark_definition.md` or a new report.
- **If PaddleOCR confidence does not correlate usefully with the CER anchors**, this blocks the PR and returns to planning — not shipped as a silently omitted field (Decision driver 9).

### 5. Mapping onto Issue #19's states
- `extraction.ocr.status` (run-level, unchanged) — execution axis.
- `representative_frames[].ocr.status` (per-frame, unchanged) — detection axis.
- `representative_frames[].ocr.reliable` (new, `bool | null`) — quality axis, meaningful only when `status == "text"`.
Purely additive; no existing enum value changes.

### 6. Source and representative-frame resolution, surviving the sanitizer
- Representative-frame resolution: captured during §2's bounded decode, stored as `frame.meta["width"]`/`["height"]`, surfaced via `representative_frame_dicts` → `build_evidence_manifest`'s per-frame loop (which already iterates `representative_frames` and can read these two new dict keys directly — no sanitizer gap here, this loop is not `_safe_source`). Applies independent of `--skip-ocr`.
- Source resolution: extend `SourceMetadata` with `width`/`height`. For **local video and YouTube alike**, probe the file that is actually used for frame extraction — after `media._download_video`/`_resolve_video_local_video` resolves a concrete video path, run ffprobe on that path (ffprobe ships with the already-required `ffmpeg` binary). This guarantees the reported resolution matches the `bestvideo[height<=720]` format actually downloaded for YouTube, not a separate unconstrained metadata field (round-2 finding). Local audio: `None`/`None` (no video stream).
- **Extend `_safe_source` itself** (`lectural/evidence.py:175-191`) to accept and copy a nested nullable `resolution: {width, height}` from the input dict into its fixed-shape return — this is the fix for the round-2 finding that `_safe_source`'s enumerated shape silently drops unknown keys. Merge `resolution` into the dict passed as `source` at the `cli.py` call site, same as the first revision proposed, but now the sanitizer actually preserves it.
- No gating change: sub-720p stays fully processable.

## Contract and dependency impact
- `docs/contracts/evidence.schema.json`: add `reliable` (nullable boolean) under `representative_frames[].ocr`, `width`/`height` (nullable integers) under `representative_frames[]`, `resolution` (object, nullable `width`/`height`) under `source`. Additive; `EXTRACTION_CONTRACT_VERSION`/`EXTRACTION_SCHEMA_VERSION` stay at `1`.
- `docs/contracts/cli.md`: document the new fields and the Issue #19 state mapping.
- No new runtime dependency: `pytesseract.run_and_get_multiple_output` ships with the already-depended-on `pytesseract`; ffprobe ships with the already-required `ffmpeg` binary.
- `lectural/config.py`: new named constant(s) for the reliability confidence threshold and any changed dedupe thresholds.
- `synthesis_input.json`'s `SCHEMA_VERSION` (currently 2) unaffected — population-rule change, not shape change.

## Execution slices
1. Fix repeated PaddleOCR instantiation in `ocr.ocr_frames`/`_ocr_paddle`.
2. Rework `visual.dedupe_frames` for bounded (O(1)-resident) decode; wire `is_same_slide` as the confirming gate; record decision metadata in `frame.meta`, including width/height.
3. Add a compression/OCR-noise-induced near-duplicate benchmark fixture, documented explicitly as a proxy (not the verified real case — see Open decisions); verify pre/post behavior; verify `near_duplicate_dropped` stays `true` on the existing case and incremental-content fixtures are not regressed.
4. Thread the reliability signal end to end: `_ocr_paddle`/`_ocr_tesseract` → `ocr_image` → `Frame.ocr_confidence` → both `slide_dicts` (synthesis gate) and `representative_frame_dicts` (evidence field). Switch `_ocr_tesseract` to `run_and_get_multiple_output`.
5. Extend `_safe_source` to preserve nested `resolution`; extend `SourceMetadata`; add post-download ffprobe for both local video and the resolved YouTube video file; merge into the `source` dict at the `cli.py` call site.
6. Calibrate the reliability threshold against #21's CER anchors; document the correlation; add the named constant to `config.py`; if inconclusive, stop and report per Decision driver 9.
7. Update `docs/contracts/evidence.schema.json` and `docs/contracts/cli.md`; extend contract tests, including a test that `_safe_source` actually preserves `resolution` (the exact gap round 2 found).
8. Before/after benchmark run (`scripts/benchmark.py`, warm, `n=3`): OCR CPU, peak RAM (explicitly checked against the O(1)-decode-cache claim in §2), temp/final storage, decode count, wall time, plus the `--skip-ocr` on/off comparison already scoped by #21's harness.

## Verification
- `uv run --with pytest --with numpy pytest -q` stays green; new/changed unit tests cover: the bounded image-level gate, the new fixture's dedupe outcome, `ocr.reliable` null/bool cases end to end (both `evidence.json` and `synthesis_input.json` sides), `_safe_source` preserving `resolution`, width/height presence for both source and representative frames.
- `docs/contracts/evidence.schema.json` validates existing fixtures plus a fixture exercising every new field.
- `scripts/benchmark.py --reps 3 --warm` (plus one `--skip-ocr` pair) before/after, on EN/KO/mixed fixtures plus the new near-duplicate fixture: `near_duplicate_dropped: true` preserved, new fixture also dropped, no incremental-content fixture regressed, reduced OCR CPU/wall time, **peak RAM not increased** (direct check on §2's bounded-decode claim), reduced decode count, and the confidence-vs-CER correlation on the L1/L2/clean anchors.
- Explicit pass/fail rule for the benchmark gate: for each of three repeated runs, the median OCR CPU-seconds and wall-time must not exceed the corresponding #21 baseline-report value; recall/duplicate-rate/timestamp-integrity metrics must not fall below their #21 baseline-report value on the equivalent fixture. The numeric tolerance band is a pending maintainer decision (see Open decisions); the statistic and comparison rule are fixed here.
- `lectural doctor` remains `ready`.
- A public CLI smoke result (`lectural extract <local fixture> --out ... --json`) showing `reliable`, `width`/`height`, and `source.resolution` present and schema-valid, confirming `_safe_source` did not strip them.

## Rollout
No runtime-breaking change for existing consumers (additive fields only). `--skip-ocr` behavior unchanged except width/height metadata now also present. Merges behind the normal PR gate.

## Rollback or mitigation
Revert the PR; no consumer contract narrows. An inconclusive reliability-threshold calibration is not a silent-ship condition (Decision driver 9): it sets the work to blocked and returns to planning for a different validated signal or a maintainer-approved formal re-scope. The dedupe/decode/engine-reuse/resolution-metadata slices are independently valuable and not gated on the reliability signal succeeding, but the PR as a whole does not close Issue #22 without it.

## Open decisions
- **Requires maintainer input before this plan can be marked Ready:**
  - The numeric tolerance for "maintainer-approved" recall/timestamp-integrity/accepted-OCR limits (Acceptance criteria) — this plan fixes the *comparison rule* (median of 3 runs vs. #21 baseline) but the tolerance number is open.
  - **The real 432.5–444s duplicate case's source frames are not present in this repository.** Options: (a) maintainer supplies the original clip/frames so the fixture is a verified reproduction; (b) proceed with a documented synthetic proxy, recorded as a known evidence gap in the eventual PR rather than presented as a verified fix.
- Exact aggregation method for per-frame confidence (mean vs. min vs. low-percentile) — default mean, revisit if calibration disagrees.
- Exact new threshold values for `PHASH_HAMMING_THRESHOLD`/`DEDUP_HIST_THRESHOLD`/`DEDUP_SSIM_THRESHOLD` and the reliability-confidence constant — determined empirically in slices 3 and 6.
- Whether other `notes.md`-facing code beyond `build_section_hints` also needs the reliability gate — slice 4 covers the confirmed path; if review finds another path, it's added to the same slice.

## Pre-mortem
Not required (risk:medium, not risk:high). The main credible failure mode — a reliability threshold that doesn't correlate with real OCR error — is addressed structurally in §4 and Rollback (blocks and returns to planning, not shipped unvalidated). The secondary failure mode raised in review — unbounded memory growth from a naive decode cache — is addressed structurally in §2 (bounded to O(1) resident frames) and directly checked in Verification's peak-RAM benchmark gate.
