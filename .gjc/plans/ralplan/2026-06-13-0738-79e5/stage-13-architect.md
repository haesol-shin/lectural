## Summary
G002 of LecturAL: the prior stage-12 WATCH ('scene_coverage requires RAW frame times but no call site enforces it; enforce when the orchestrator is built') is resolved at the library boundary. coverage_inputs_from_extraction is a keyword-only constructor that routes raw sampled keyframe times into frame_times and derives slide counts from the deduped slides, making the carry-cap contract the path of least resistance. Recommend APPROVE; both architecture and product move to CLEAR.

## Analysis
- lectural/coverage.py:132-165 — coverage_inputs_from_extraction(*, ...) is keyword-only (leading *), so a caller cannot positionally swap raw samples and slides. raw_sample_times is routed verbatim (defensive copy via list(...)) into CoverageInputs.frame_times, which build_coverage (line 171) feeds straight to scene_coverage. slide_frames_total = len(slides) and slide_frames_with_text derive from the deduped slide dicts ocr_text, so a caller cannot accidentally feed deduped frames into the scene-coverage carry path and defeat the cap.
- lectural/coverage.py:113-130 — CoverageInputs gains a raw_frame_times property aliasing frame_times, documenting that the field MUST be RAW (pre-dedup) samples. Docstrings on both scene_coverage and the new constructor name the invariant explicitly and point at visual.extract_candidate_frames as the raw source vs dedupe_frames.
- tests/test_coverage.py:107-130 — new test_coverage_inputs_from_extraction_routes_raw_times_and_counts asserts (a) raw is routed to frame_times/raw_frame_times unchanged, (b) slide_total=2 and with_text=1 are derived (one empty ocr_text), (c) dense raw produces scene_coverage uncovered_speech_bins == [], and (d) overall_pass is False because the slide-text gate fails. This exercises raw routing, count derivation, and slide-text gate independence from scene coverage in one case.
- Supporting coverage already present: carry-cap stall detection, static-slide pass with dense raw, uncovered pre-keyframe bins, slide-lacks-text fail.

## Root Cause
The stage-12 WATCH root cause was a missing enforcement seam: scene_coverage documented a RAW-samples precondition but nothing constrained how a future caller would assemble its inputs, so deduped frames could silently flow in and neutralize the carry cap. The fix adds the boundary constructor that makes correct assembly the default and ties slide counts to deduped slides — directly addressing the named gap.

## Findings
- LOW — lectural/coverage.py:113 — CoverageInputs remains a plain public dataclass, so direct construction (used by test_build_and_write_coverage and test_redteam_synthesis) can still pass deduped frames into frame_times. The new constructor is the documented/recommended path, not a hard barrier. Acceptable as a test seam; the raw_frame_times alias plus docstrings carry the contract. No code change required.
- INFO — No orchestrator/CLI module exists yet (lectural has no main/__main__/cli; __init__ only re-exports config). There is therefore no live production call site of the new constructor; verification rests on the unit test. The prior WATCH was conditional on the orchestrator, and the library now exposes the exact shape the orchestrator must use, so the conditional is satisfied at the boundary.

## Recommendations
1. When the orchestrator/CLI is implemented, wire visual.extract_candidate_frames raw timestamps and dedupe_frames slides through coverage_inputs_from_extraction (not the bare dataclass) and add one integration test asserting raw times reach scene_coverage.
2. (Optional) If stronger guarantees are wanted later, make CoverageInputs construction private to the module and expose only the enforcing constructor.

## Architectural Status
CLEAR

## Code Review Recommendation
APPROVE

## Trade-offs
- Soft contract (keyword-only constructor plus alias plus docstrings) vs hard contract (private dataclass): soft keeps test seams and direct construction simple while still steering production to the safe path; hard would fully prevent misuse but complicates the existing pure-function tests. Soft is the right call at this stage; revisit if a non-orchestrator caller is added.

Note: 78 tests reported passing by the implementer; restricted-bash prevented an independent pytest run here, so test-pass is taken from the change context plus static reading of the assertions.
