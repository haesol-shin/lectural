# G001 Architect Review — LecturAL P1–P6 Deterministic Core

## Summary
G001 delivers a clean, import-safe deterministic core. Heavy deps (ffmpeg, opencv, paddleocr, faster-whisper, yt-dlp, youtube-transcript-api) are all lazily imported; module-level imports are stdlib + local only, matching the 22-passing offline test run. The speech-gap metric is semantically correct (silence cannot count) and a real >60s untranscribed speech span is detectable; the dedup AND-guard is sound and conservatively biased toward retention. No CRITICAL/HIGH issues; a small cluster of MEDIUM diagnostics concerns (silent broad-except, global-SSIM approximation) warrant follow-up but do not block.

## Analysis

### Lazy-import discipline (Point 3) — verified offline-safe
Module-level imports audited per file:
- vad.py: re only; CUE_MAX_COVER_SEC imported inside transcript_coverage_spans; ffmpeg via subprocess in detect_speech_spans behind require_binary.
- visual.py: dataclasses + .config only; cv2/numpy imported inside _pair_metrics; ffmpeg subprocess behind require_binary.
- acquisition.py: json/re/subprocess/dataclasses (stdlib); youtube_transcript_api lazy in fetch_caption_segments; .speech imported lazily inside acquire_speech (also breaks the speech.py -> acquisition.py cycle).
- speech.py: imports acquisition+config at top (local, light); faster_whisper lazy.
- ocr.py: re/warnings/.config/.visual; paddleocr/pytesseract/PIL lazy.
- deps.py uses importlib.util.find_spec (never imports the heavy module); config.py and __init__.py stdlib/local only.
No import-time dependency on ffmpeg/opencv/paddleocr. CLEAR.

### Speech-gap metric (Point 1) — semantically correct
max_non_silence_untranscribed_gap = max width of subtract_spans(speech_spans, coverage_spans). Silence is never in speech_spans, so it structurally cannot contribute — silence truly does not count. transcript_coverage_spans caps each cue at CUE_MAX_COVER_SEC=30s, so a cue-less stretch during speech stays uncovered. Traced test_real_speech_gap_fails: speech [(0,300)], cues [0,50,100,280,290] gives coverage [(0,30),(50,80),(100,130),(280,300)] and uncovered max (130,280)=150s > MAX_GAP_SEC(60). A real >60s untranscribed speech span is detected. Pre-first-cue and post-last-cue speech are also uncovered (detected). Modeling assumption: cue spacing must exceed ~90s (30s cover + 60s gap) to FAIL, which is appropriately sparse. CLEAR.

### Dedup over/under guard (Point 2) — sound
is_same_slide collapses only when hist_corr>=0.90 AND ssim>=0.92. The AND biases toward KEEPING frames when either metric is low, i.e. errs toward under-dedup / retention — the safe direction for a 'capture ALL scenes' product. test_over_dedup_guard (high hist 0.99 + low ssim 0.50 -> kept) confirms the layout-change-same-palette case is preserved. Downstream OCR-text incremental dedup (dedupe_incremental_texts) mitigates the resulting near-dup retention cost. Sound. CLEAR.

### _ssim global approximation (Point 4) — defensible weakness, not a G001 risk
_ssim computes a single global-window SSIM (whole-image mean/var/cov) rather than the standard 11x11 windowed local SSIM. The constant terms (C1=(0.01*255)^2, C2=(0.03*255)^2) match the SSIM index. Global SSIM is spatially insensitive: two slides with matching global luminance stats but different text layout can score high, raising over-dedup risk on the real-image integration path. It is NOT exercised in G001 (tests feed hand-crafted metrics; numpy is not even a test dep), and the conservative AND-guard partially offsets it. Defensible as a documented approximation for the deterministic-core story, but should be hardened (windowed SSIM) or covered by a real-image smoke test before the visual pipeline is wired end-to-end.

## Root Cause
N/A — no defect under repair. The reviewable risks are diagnostic/approximation choices, not regressions.

## Findings

- MEDIUM — acquisition.py acquire_speech 'except Exception as exc: _ = exc': the captions->STT fallback is the intended product contract, but it swallows ALL exceptions and discards the reason (the assignment is a dead no-op). A genuine bug (API misuse, auth/network error that should surface or retry) is silently masked and triggers an expensive STT download+transcribe. Failure evidence is not preserved, violating the narrow-fallback bar. Fix: narrow to expected exception types (transcript-api NoTranscriptFound/TranscriptsDisabled/network) and/or emit a RuntimeWarning recording why captions failed, and record source degradation in SpeechTrack.meta.
- MEDIUM — visual.py _ssim is global SSIM; over-dedup risk on real images (see Analysis Point 4). Fix: windowed SSIM or a real-frame smoke test before integration.
- LOW — Diagnostic inconsistency: ocr.ocr_image warns on the Paddle->Tesseract fallback (good), but acquisition silently falls back to STT. Align the two so degraded runs are observable in coverage output.
- LOW — vad.detect_speech_spans runs ffmpeg without check=True; on a runtime ffmpeg error proc.stderr yields no silences, invert gives whole timeline as speech, producing a spurious completeness FAIL. Safe-ish direction but misleading; consider validating returncode.
- LOW — Untested pure helpers: _ssim (numpy not a test dep), should_warn_long_video, and transcript_coverage_spans pre/post-cue boundaries (covered only indirectly). select_keyframe_indices([]) returns [0] referencing a nonexistent frame, but dedupe_frames guards len<=1, so it is safe in practice.

## Recommendations
1. Narrow the acquire_speech catch and preserve/surface the failure reason; stamp source-degradation in meta (addresses the only MEDIUM with product-diagnostic impact).
2. Track _ssim hardening (windowed SSIM) or a real-image dedup smoke test as a visual-integration follow-up.
3. Make the STT fallback observable (warning) to match the OCR fallback pattern.
4. Add direct tests for transcript_coverage_spans boundaries and (with numpy in the test extra) _ssim, plus an ffmpeg-failure guard in detect_speech_spans.

## Architectural Status
CLEAR

## Code Review Recommendation
COMMENT

## Trade-offs
- Global SSIM vs windowed SSIM: faster/simpler, import-safe pure-numpy, but spatially blind, higher over-dedup risk. Acceptable for deterministic-core; revisit for the real-image path.
- Broad except (current) vs typed except: broad keeps the fallback resilient to unknown caption-API errors but masks bugs and discards evidence; typed+warn preserves resilience while surfacing diagnostics — preferred.
- AND-guard dedup: conservative retention (more frames, more OCR cost) traded for not losing distinct slides — correct for a completeness-first product.
