# Multi-language STT extraction baseline — 2026-09-19

Official CPU STT and OCR extraction quality and resource baseline for Issue #21, establishing decision-grade performance metrics on committed synthetic fixtures before Issue #22 (visual) and Issue #23 (speech) implementation.

## Exact command

```bash
uv pip install -e ".[run,bench]"
uv run --with psutil python scripts/benchmark.py \
  --fixtures-dir "tests/fixtures/benchmark/en_terms_01_force_stt,tests/fixtures/benchmark/ko_terms_01_force_stt,tests/fixtures/benchmark/mixed_terms_01_force_stt" \
  --out "output/benchmark-stt-baseline" \
  --platform-label "x86_64-win" \
  --warm --reps 1 --model medium
```

Raw report: [`real_stt_baseline_x86_64-win_2026-09-19.json`](real_stt_baseline_x86_64-win_2026-09-19.json).

## Environment

| Item | Specification |
|---|---|
| Platform | Windows-10-10.0.26200-SP0 (Intel64 Family 6 Model 189 Stepping 1) |
| CPU cores | 8 |
| Python | 3.11.15 |
| faster-whisper | 1.2.1 (model: `medium`, compute_type: `int8`) |
| paddleocr | 2.10.0 |
| ffmpeg (binary) | 8.1.1-full_build-www.gyan.dev |

## Multi-language STT quality and resource summary

All runs exercised the actual Faster-Whisper STT path (`speech_source: "stt"`) with full slide extraction and OCR:

| Metric | EN (`en_terms_01_force_stt`) | KO (`ko_terms_01_force_stt`) | Mixed (`mixed_terms_01_force_stt`) |
|---|---:|---:|---:|
| Fixture duration (s) | 19.31 | 21.97 | 22.59 |
| Total wall time (s) | 51.17 | 41.61 | 45.26 |
| Real-time factor (RTF) | 2.65 | 1.98 | 2.10 |
| Speech source | `stt` | `stt` | `stt` |
| **STT WER** | **0.148** | **0.261** | **0.480** |
| **STT CER** | **0.011** | **0.080** | **0.500** |
| Technical terminology recall | 0.667 | 0.600 | 0.333 |
| Cue timestamp median error (s) | 0.191 | 0.727 | 0.803 |
| Cue timestamp P95 error (s) | 0.919 | 0.973 | 0.980 |
| Voiced speech recall | 0.837 | 0.850 | 0.850 |
| Max untranscribed speech gap (s) | 0.772 | 0.779 | 0.782 |
| Near-duplicate slide dropped | `true` | `true` | `true` |
| Candidate frame drop rate | 0.950 | 0.953 | 0.956 |
| Video slide OCR CER (vs authored text) | 0.384 | 0.538 | 0.483 |
| Degraded slide L1 CER (moderate blur) | 0.029 | 0.185 | 0.027 |
| Degraded slide L2 CER (severe defocus) | 0.796 | 0.870 | 0.676 |

## Analysis and findings

1. **STT Quality Baseline across Languages**:
   - English achieves high accuracy (WER 14.8%, CER 1.1%), with proper nouns like *"Geoffrey Hinton"* correctly recognized. Missed terms are primarily formatting representations of numbers (e.g. *"0.05"* articulated as *"zero point zero five"* vs numeral output).
   - Korean achieves WER 26.1% and CER 8.0%, accurately capturing technical terms like *"우선순위 큐"* and Dijkstra's Korean transliteration (*"에츠허르 데이크스트라"*).
   - Mixed-language code-switching (Korean phrasing with English terms like *"Convolutional Neural Network"*, *"AdamW"*, *"weight decay"*) exhibits the highest error rate (WER 48.0%, CER 50.0%), establishing a clear baseline for Issue #23 speech improvements.
2. **Visual Deduplication Fidelity**:
   - `near_duplicate_dropped: true` on all three fixtures confirms `lectural.visual.dedupe_frames` correctly drops the shifted duplicate slide (`slide_02_near_dup.png`) under perceptual hash comparison.
3. **OCR Degradation Sensitivity**:
   - Standalone degraded slides show predictable error scaling: L1 moderate blur retains usable accuracy (CER 0.027–0.185), whereas L2 defocus causes severe degradation (CER 0.676–0.870), validating the degradation fixture design.
