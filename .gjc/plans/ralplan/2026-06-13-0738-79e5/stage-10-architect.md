## Summary
G002 deterministic synthesis + coverage core is clean, pure, and token-zero, with summary.md anchors fully aligned to docs/synthesis_contract.md and shared as constants for the G003 hook. Two MEDIUM design gaps warrant attention before the gate is fully trusted: (a) scene_coverage frame_times semantics are undefined and the keyframe-in-every-speech-bin rule can spuriously FAIL low-visual-change lectures, and (b) summary.md section windowing silently omits speech before the first slide. The core ALL-speech promise is upheld by transcript.md, so there are no hard blockers. Recommendation: COMMENT.

## Analysis

### (1) Anchor set sufficiency + contract/hook consistency — OK
synthesis.py defines TOC_ANCHOR (## 목차), COVERAGE_ANCHOR (## 커버리지 요약), SECTION_PREFIX (## 섹션), ENRICH_MARKER (<!-- lectural:baseline -->). render_summary_md emits ENRICH_MARKER as line 0, the coverage header, the TOC with intra-doc links [HH:MM:SS · title](#sec-N) over <a id=sec-N></a> anchors, per-section headings ## 섹션 N. [HH:MM:SS] title, and slide image links ![...](frames/...). All five contract-table anchors are produced and match docs/synthesis_contract.md exactly. The literal bracketed timestamp [HH:MM:SS] appears in section headings and body bullets, satisfying the documented hook check. Constants are exported so the G003 hook can import (not re-hardcode) them.

Caveat (LOW): the contract phrases one hook check as at least one [HH:MM:SS] timestamp LINK. The bracketed timestamps in section headings/body bullets are plain text, not markdown links; the TOC entries ARE links but their link text is HH:MM:SS · title (not a bare [HH:MM:SS]). If the G003 hook regexes for a bracketed timestamp substring it passes; if it requires a markdown link whose text is exactly HH:MM:SS it would miss. The hook (G003) must import the synthesis constants and match the bracketed-timestamp form to stay consistent.

### (2) scene_coverage with SCENE_BINS_N=20 — MEDIUM
Bin width = duration/20, so the rule keyframe-in-every-speech-bin scales with length (6 min bins at 2h, 30s bins at 10 min). Soundness depends entirely on what frame_times contains, which is undefined here (no G002 caller; wiring is G003). If frame_times are deduped slide-change timestamps, a legitimately static/low-change lecture (one slide held for minutes) yields frames in only a few bins, so many speech bins are uncovered and scene_coverage FAILS even though capture is complete — a false-negative gate. If frame_times are raw sampled frames (SAMPLE_FPS), every speech bin is trivially covered and the check becomes a near-no-op. Either reading is problematic; the contract does not pin frame_times semantics. Recommend documenting frame_times as the keyframe-sample times and/or relaxing to a carry-forward rule (a speech bin is covered if a keyframe exists at or before it, since a slide persists), so persistent slides do not trip a spurious FAIL.

slide-text check: slide_frames_with_text >= slide_frames_total correctly enforces every slide frame has OCR text (with_text never exceeds total in practice; equality == all-have-text). Using >= rather than == is a slightly loose but safe guard. slide_frames_total=0 -> trivially OK. Correct.

### (3) Section windowing — MEDIUM (segment loss, summary only)
build_section_hints opens a section at each slide t running to the next slide t (last -> duration); _segments_in_window uses t0 <= t < t1. Two loss conditions:
- BEFORE first slide: the first section starts at slides[0].t. If the first detected slide/keyframe is at t>0 (intro narration before the first slide appears), every segment with t in [0, slides[0].t) lands in NO section and is silently absent from summary.md (TOC + bodies). It IS still in transcript.md.
- AFTER last slide: covered — the last window extends to duration. Only a cue exactly at t==duration would drop (exclusive upper bound); negligible.
Impact is confined to summary.md fidelity; transcript.md (the ALL-speech promise) is unaffected. In practice the visual pipeline usually emits a t≈0 keyframe, masking the gap, and summary.md is explicitly a baseline a host may enrich — so this is WATCH, not BLOCK. It becomes a blocker only if summary.md itself is contractually required to be lossless. Fix: anchor the first section start at 0.0 (start first hint at min over {0.0, first slide t}) so intro speech is never orphaned.

### (4) transcript.md ALL-utterance guarantee — OK
render_transcript_md iterates for s in segments over the full input list with no filtering or windowing; every segment is rendered as [HH:MM:SS] text. No loss within this layer; completeness reduces to the caller passing every utterance (G003). Empty-text segments render a harmless blank line. The capture-ALL-speech promise is met by transcript.md.

### (5) LLM / network / binary imports — OK (token-zero preserved)
synthesis.py imports only json + config. coverage.py imports json, os (file stat only), dataclass, config, vad. The vad functions used by the gate (transcript_coverage_spans, max_non_silence_untranscribed_gap, subtract_spans) are pure interval algebra. The only subprocess/binary path (ffmpeg silencedetect + deps.require_binary) is lazily imported inside detect_speech_spans, which is input-prep and NOT invoked by the deterministic artifact/coverage builders. No LLM, no network. Deterministic/token-zero contract holds.

### (6) schema_version discipline — OK (minor doc gap)
SCHEMA_VERSION=1 is centralized in config.py. build_synthesis_input and build_coverage both stamp schema_version; test asserts reloaded coverage schema_version==1. Contract documents schema_version for synthesis_input.json and the bump rule. LOW: the coverage.json section of the contract does not explicitly document its schema_version field even though build_coverage emits it — document it for reader symmetry.

## Root Cause
Not a defect review. The two latent gaps share one root: completeness for summary.md and for scene_coverage is asserted structurally without pinning the upstream data contract (frame_times semantics; first-section lower bound), so behavior is correct only under unstated assumptions about the G003 wiring.

## Findings
- MEDIUM — lectural/synthesis.py build_section_hints / _segments_in_window: segments before the first slide are dropped from summary.md sections when slides[0].t > 0. Impact: silent omission of intro narration from the baseline summary (transcript.md unaffected). Fix: start the first section at 0.0.
- MEDIUM — lectural/coverage.py scene_coverage: keyframe-in-every-speech-bin is sound only under an unstated frame_times definition; deduped-slide times cause spurious FAIL for static lectures, raw samples make it a no-op. Fix: pin frame_times semantics in the contract and/or use carry-forward bin coverage.
- LOW — docs/synthesis_contract.md vs hook: clarify whether the timestamp check matches a bracketed [HH:MM:SS] substring (present) or a markdown link with HH:MM:SS text (not present); ensure the G003 hook imports synthesis constants.
- LOW — lectural/synthesis.py render_summary_md TOC line [ts · title](#sec-N): section titles come from OCR via _first_line and are not escaped; a title containing a closing bracket or paren can break the markdown link. Fix: sanitize/escape title in link text.
- LOW — docs/synthesis_contract.md: coverage.json schema_version field is emitted but undocumented.

## Recommendations
1. Anchor the first summary section at 0.0 so no utterance before the first slide is orphaned (closes the only segment-loss path).
2. Pin frame_times semantics in docs/synthesis_contract.md and relax scene_coverage to carry-forward coverage so persistent slides do not trip false FAILs; add a static-single-slide test case.
3. When wiring G003, import ENRICH_MARKER/COVERAGE_ANCHOR/TOC_ANCHOR/SECTION_PREFIX from synthesis.py and match the bracketed-timestamp form; add a hook contract test.
4. Escape section-title text used inside TOC markdown links.
5. Document coverage.json schema_version in the contract.

## Architectural Status
WATCH

## Code Review Recommendation
COMMENT

## Trade-offs
- scene_coverage strictness: every-bin keyframe (current) is simple and catches true visual gaps but risks false FAIL on static lectures; carry-forward coverage tolerates persistent slides at the cost of missing a genuinely missing mid-section keyframe. Carry-forward is the better fit for lectures.
- summary first-section bound: starting at first slide t keeps headings slide-aligned but loses pre-slide speech; starting at 0.0 guarantees no loss with a slightly less tidy first heading. Lossless wins for a study-notes product.

## Three-lane status
- Architecture: WATCH
- Product: WATCH
- Code: CLEAR
- Recommendation: COMMENT
- Blockers: 0 (transcript.md upholds the ALL-speech promise; summary/scene gaps are WATCH-level and fixable, not hard blockers)
