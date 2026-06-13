## Summary
Re-review of LecturAL G001 after fixes to the prior stage-08 COMMENT/WATCH items. All four prior findings are RESOLVED with file-backed evidence; the windowed SSIM box-filter math is mathematically correct (summed-area integral image, edge padding, exact k*k mean), returns 1.0 for identical inputs and < 1 for layout changes with matching global stats. Recommendation: APPROVE.

## Analysis
Inspected lectural/acquisition.py (acquire_speech), lectural/visual.py (_ssim), lectural/vad.py (detect_speech_spans), tests/test_ssim.py.

Finding 1 (MEDIUM, prior) acquire_speech caption fallback reason: fallback_reason is now set in every branch -- 'force_stt requested', 'captions present but unusable (N cues)', and on exception 'caption fetch failed: <Type>: <msg>'. It is surfaced two ways: warnings.warn(..., RuntimeWarning, stacklevel=2) mirroring the OCR Paddle->Tesseract pattern, and stamped onto track.meta['caption_fallback_reason']. The broad 'except Exception' is retained but justified by an explicit comment: youtube-transcript-api raises distinct types (NoTranscriptFound/TranscriptsDisabled/network) not importable without the optional dep. Per root-cause/fallback policy this is acceptable: scoped to a known optional-dep boundary, failure evidence preserved (type name + message), surfaced not swallowed, and it does not mask a controllable primary contract.

Finding 2 (MEDIUM, prior) _ssim global->windowed: _ssim now computes a win x win (default 7) local SSIM map via a separable box filter built on a cumulative-sum integral image, making it spatially sensitive. Result is clipped to [-1,1]. Math verified: pad edge by k//2, double cumsum, pad leading zero row/col -> SAT of shape (h+k,w+k); the four-corner difference yields exact window sums; /(k*k) = window mean. Identical inputs give num==den elementwise -> 1.0. den is strictly positive (c1,c2>0; va+vb+c2 dominated by c2~58.5).

Finding 3 (LOW, prior) detect_speech_spans returncode: now checks proc.returncode != 0 and raises RuntimeError including code and last 500 chars of stderr, instead of parsing empty stderr into a spurious all-speech span (which would cause a false completeness FAIL). Root cause addressed.

Finding 4 (LOW, prior) _ssim untested: tests/test_ssim.py adds 4 direct tests -- identical==1.0 (abs 1e-6), layout-change-same-global-stats < 0.9, small perturbation > 0.95, bounded [-1,1]. The layout test explicitly constructs equal-histogram/equal-mean images to prove spatial sensitivity that a global SSIM would miss.

## Root Cause
N/A -- this is a fix-verification pass; each prior defect's root cause was addressed at source (reason capture+surfacing; per-window statistics; explicit returncode check; direct unit coverage).

## Findings
No CRITICAL/HIGH/MEDIUM/LOW open issues. All prior findings RESOLVED.

Observations (non-blocking):
- LOW/informational: _ssim local variance can be marginally negative from float rounding, but the final clip to [-1,1] and the c2 stabiliser keep output bounded and den>0; no action needed.
- INFO: Verification per context: 'uv run --with pytest --with numpy pytest -q' => 49 passed. Restricted bash here cannot re-run pytest; relying on reported run plus math/code review.

## Recommendations
1. None required for merge. Optional: a future stage could add a parametrized test asserting _ssim monotonic decrease as block-swap fraction grows, but current coverage is sufficient.

## Architectural Status
CLEAR

## Code Review Recommendation
APPROVE

## Trade-offs
- Broad 'except Exception' vs typed catches: typed catches need the optional dep importable at module scope; broad-catch-with-preserved-reason is the correct tradeoff here and is documented.
- Windowed SSIM cost vs accuracy: integral-image box filter is O(N) per image and pure-numpy (no scipy), a good cost/accuracy/dependency tradeoff.
