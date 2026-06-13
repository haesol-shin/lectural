# G002 LecturAL — Stage-12 Final Re-Review (Architect)

## Summary
The carry-forward MEDIUM and three LOWs are RESOLVED with file-backed evidence and targeted tests. The reviewed change is correct and well-bounded; the only residual is an unenforced caller contract (raw vs deduped frame times) with no in-repo orchestrator. No blockers.

## Analysis

### (1) Capped carry-forward — mid AND tail stall detection + static-slide pass
lectural/coverage.py scene_coverage (L67-95): bin loop computes idx = bisect.bisect_right(times, b1) - 1 (most-recent keyframe at or before bin END b1) and marks covered iff idx >= 0 and (b0 - times[idx]) <= carry_max_sec (within carry_max of bin START b0). This is exactly the described bisect contract.
- Forward carry window for a keyframe kf = bins containing kf .. bins whose b0 <= kf+carry; no backward over-carry.
- Mid stall: test_scene_coverage_mid_video_stall_detected_by_carry_cap (frames 0..99 + 590,595, dur=600, bins=20, carry=120) — bins ~8..18 have nearest prior keyframe at 99, b0-99 > 120 -> uncovered -> pass False. Confirmed by trace.
- Tail stall: pre-existing test_scene_coverage_uncovered_speech_bin_fails and the mid test tail bins (b0-99>120) FAIL; pre-first-keyframe speech (frames=150, bins 0..6 get idx=-1) -> uncovered. All three stall classes detected.
- Static slide with dense raw samples: test_scene_coverage_static_slide_passes_with_dense_raw_samples (frames 0..599 step 1) — every bin has an in-bin keyframe (b0-times[idx] <= 0) -> pass True, uncovered empty. Confirmed.
- carry_max_sec recorded in output dict (L88). build_coverage uses FRAME_CARRY_MAX_SEC default.

### (2) Title escaping
synthesis.py _safe_title (L43-50): collapses whitespace/newlines via space-join of text.split(), then replaces open-bracket->open-paren, close-bracket->close-paren, pipe->slash. Applied to BOTH TOC link text and section headings. test_summary_escapes_markdown_special_titles asserts no close-bracket in link-text segment and no pipe. Numeric sec-{index} anchors are inherently safe. Broken-link/heading vector closed.

### (3) Empty-intro skip never drops a segment
build_section_hints prepends a synthetic 도입 intro (frame=None) only when first slide t>0. _renderable (render_summary_md): single-section always rendered; otherwise rendered iff frame present OR bucket non-empty. assign_segments_to_sections owns a pre-slide segment (t < first slide win_start) to the intro bucket -> intro becomes renderable, so a pre-slide segment FORCES intro render. When intro bucket is empty it is skipped, but by construction it holds no segments -> zero drops; union-of-buckets invariant preserved. test_summary_skips_empty_intro_section_but_keeps_pre_slide_speech covers both: t=120-only hides 도입 (segment lands in slide section), t=5 forces 도입부 발화 to appear. Confirmed.

### (4) Doc drift
config.py: SCENE_BINS_N comment rewritten for capped carry; FRAME_CARRY_MAX_SEC documented as RAW dense-sample expectation plus stall catch. coverage.py module and scene_coverage docstring updated to state RAW pre-dedup frame_times requirement and the three stall classes. Consistent across both files.

## Root Cause
N/A — no defect under review; this is a fix-verification pass.

## Findings
- LOW (residual, pre-existing): lectural/coverage.py scene_coverage contract requires RAW extract_candidate_frames timestamps (dense, ~SAMPLE_FPS), NOT dedupe_frames output. The repo has no orchestrator wiring visual.py -> CoverageInputs; the contract lives only in docstring/config comments. If a future integrator passes deduped keyframes, a static slide will FAIL falsely again (the very bug just fixed). Impact: latent correctness risk at integration time. Fix: when an orchestrator is added, route extract_candidate_frames timestamps into frame_times and consider a guard or typed wrapper distinguishing raw-sample-times from keyframe-times.

## Prior-item disposition
- MEDIUM-1 summary drops: RESOLVED.
- MEDIUM-2 static false-FAIL: RESOLVED.
- MEDIUM carry-forward blind to mid/tail/pre-first-keyframe stall: RESOLVED (cap + 3 stall classes + static-pass tests).
- LOW doc drift: RESOLVED.
- LOW empty intro section: RESOLVED.
- LOW unescaped bracket/pipe in titles: RESOLVED.

## Recommendations
1. APPROVE the change as-is.
2. (Non-blocking) When the end-to-end pipeline/orchestrator is implemented, enforce the raw-sample-times contract at the call site so the carry cap cannot be defeated by passing deduped keyframes.

## Architectural Status
WATCH

## Code Review Recommendation
APPROVE

## Trade-offs
- Carry measured to bin START (b0) not END: slightly lenient at bin tail (~one bin_width) but prevents backward over-carry and keeps detection deterministic. Acceptable.
- Fixed 120s cap plus reliance on raw dense sampling: simple and testable, but couples correctness to an unenforced upstream contract (the residual WATCH).
