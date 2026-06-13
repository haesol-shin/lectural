# Architect Re-Review — G002 LecturAL (stage 11, post-fix)

## Summary
The two prior MEDIUMs are RESOLVED in code and locked by tests: summary.md no longer drops any segment in 0<=t<=duration and assigns each to exactly one section (intro-section prepend + last-win_start ownership), and carry-forward scene_coverage now passes static single-slide lectures while flagging only pre-first-keyframe speech. No blockers. One NEW design tradeoff (carry-forward cannot detect a mid/tail frame-extractor stall) and stale module/config docstrings warrant WATCH; recommendation COMMENT.

## Analysis
### Claim 1 — no drops + single-owner (synthesis.py)
- build_section_hints (synthesis.py:44-78): when sorted first slide t>0, prepends an 'intro' (도입) section {index 0, t 0, win_start 0, t_end=first.t}. With no slides, returns one whole-video section. Slides past duration keep last t_end=duration. Verified by test_build_section_hints_adversarial_order_single_duplicate_and_past_duration.
- assign_segments_to_sections (synthesis.py:94-115): default owner = ordered[0]; each segment owned by the LAST section with win_start<=t. t<0 falls to first section; t>=0 always matches (intro/first win_start=0); t==duration and t past last win_start fall to the last real section. Each segment appended exactly once → union == input, single-owner.
- render_summary_md (synthesis.py:165-186) prints buckets.get(index) once per section.
- Tests: test_render_summary_md_assigns_each_in_duration_segment_once_and_boundary_to_one_section (boundary t==50 lands only in sec-1, not sec-0); test_render_summary_md_does_not_drop_in_duration_segments_before_first_slide_or_at_duration (t=0, 24.999, 100.0 each appear exactly once with first slide at 25). RESOLVED.

### Claim 2 — carry-forward scene_coverage (coverage.py:45-103)
- first_frame_bin = min bin among frame_times in [0,duration]; covered = {speech bins >= first_frame_bin}; uncovered = speech bins before first keyframe. Static single slide at t=0 → first_frame_bin=0 → all speech bins covered → pass (with slides_ok). Function docstring pins frame_times semantics ('deduped slide times are fine because of carry-forward'). The last keyframe carries to end-of-video, so docstring ('until the next keyframe') and impl ('>= first_frame_bin') are equivalent.
- Tests: test_scene_coverage_uncovered_speech_bin_fails (frame@150/dur200 → bins 0-6 uncovered, FAIL); test_scene_coverage_pass_when_every_speech_bin_has_frame; test_scene_coverage_empty_zero_duration_slide_text_fail_and_all_bins_pass (single keyframe covers all 4 bins). RESOLVED.

### Claim 3 — coverage.json schema_version
- build_coverage (coverage.py:124-144) sets 'schema_version': SCHEMA_VERSION (=1, config.py). docs/synthesis_contract.md now documents it ('schema_version is 1 ... readers MUST check it'). Tests assert reloaded['schema_version']==1. RESOLVED (prior LOW closed).

## Root Cause
Prior MEDIUMs stemmed from (a) a section-window model that left pre-first-slide and at-duration speech unowned, and (b) an over-strict per-bin keyframe rule. Both are fixed at the source: an explicit intro section + total ownership function, and carry-forward coverage that models slide persistence.

## Findings
- [MEDIUM] coverage.py:45-103 — Carry-forward blind spot. Because the last seen keyframe covers every later bin unconditionally, a mid/tail frame-extractor STALL (ffmpeg/scene-detect dies after the first frames) is undetectable: trailing speech bins are marked covered though no visual pass reached them. gap_check only inspects audio/transcript, and slides_ok (with_text>=total) does not detect a truncated extraction. This is an inherent, deliberate tradeoff of carry-forward, but it weakens scene_coverage as a frame-completeness gate vs the old strict rule. Fix suggestion: add an independent extractor-completeness signal (e.g. assert last keyframe time is within N bins/seconds of duration, or record expected-vs-emitted frame count) so a truncated visual pass still FAILs. Not a blocker; tracked as WATCH.
- [LOW] coverage.py:5-6 (module docstring) and config.py SCENE_BINS_N comment ('each bin that contains speech must also contain at least one extracted keyframe ... to pass') — STALE: still describe the OLD strict per-bin rule, contradicting the new carry-forward semantics implemented in scene_coverage. Doc drift on the exact behavior that changed; update both to the carry-forward wording used in the function docstring.
- [LOW] synthesis.py:165-178 — Empty intro section. When the first slide starts >0 but no speech precedes it, the prepended 도입 section renders a heading with an empty body (and a TOC entry). Cosmetic only; anchors/hook unaffected. Optional: suppress sections whose bucket is empty AND frame is None.
- [LOW] synthesis.py:158-160, 168 — Unescaped OCR titles in TOC link text and section headings. Titles containing ']' or '|' (e.g. 'Boundary # [x] | y') break the markdown link/inline rendering of '[ts · title](#sec-N)'. Pre-existing (prior LOW), still UNRESOLVED; cosmetic, no drop/anchor impact. Escape ']'/'|' or strip markdown-special chars in _first_line.
- [INFO] Prior LOW 'hook timestamp-link wording' is in G003 hook territory, out of scope of the reviewed files; not re-evaluated here.

## Recommendations
1. (WATCH) Add an extractor-completeness check independent of carry-forward so a truncated/stalled visual pass cannot silently pass scene_coverage.
2. (LOW) Sync coverage.py module docstring + config.py SCENE_BINS_N comment to carry-forward semantics.
3. (LOW) Escape markdown-special chars in section titles; optionally suppress empty intro section body.

## Architectural Status
WATCH

## Product Status
WATCH

## Code Status
CLEAR

## Code Review Recommendation
COMMENT

## Trade-offs
- Strict per-bin rule: detects any missing visual coverage incl. tail stalls, but false-FAILs static/deduped lectures (prior bug).
- Carry-forward (chosen): correct for static lectures and deduped slide times (dominant case), but blind to mid/tail extractor stalls — mitigate with an independent completeness signal.

## Per-MEDIUM
- MEDIUM-1 (summary drops pre-first-slide / at-duration speech): RESOLVED
- MEDIUM-2 (scene_coverage false-FAIL on static deduped slides): RESOLVED

## Blockers
None (0).
