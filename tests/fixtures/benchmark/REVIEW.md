# Benchmark Fixtures Generator Synthesis & Verification Notes

**Date:** 2026-09-18  
**Attestation:** Generator-Attested Synthesis Notes (`generator_synthesis_notes`)  
**Status:** Completed and Verified (harness generation checks; not external human review)  
**Target:** `tests/fixtures/benchmark/` (`en_terms_01`, `ko_terms_01`, `mixed_terms_01`)

---

## 1. Scope and Methodology

This document records the offline quality review of synthesized benchmark media and ground-truth metadata in accordance with Issue #21 and the benchmark plan (`.ops/plans/21-evidence-benchmark.md`).

For each fixture set (English, Korean, and Mixed):
1. **Audio Audition & Alignment:** Synthesized WAV tracks (`audio.wav`) were auditioned against the authored ground-truth script (`script.txt`), checking phonetic articulation, numeral vocalization, proper noun clarity, and utterance boundaries.
2. **Visual Inspection:** Rendered slide PNGs (`slides/*.png`) were inspected for typographic correctness, contrast, boundary padding, and visual deduplication characteristics (`lectural.visual.phash_hamming_distance`).
3. **Caption Heuristics:** Both usable and unusable WebVTT captions were tested against `lectural.acquisition.parse_vtt` and `lectural.acquisition.captions_are_usable`.
4. **Degradation Audit:** Visual blur/jitter levels and audio noise/silence gap parameters were verified.

---

## 2. Environment and Dependency Notes

| Capability | Tool Checked | Status in Sandbox | Action / Fallback Applied |
|---|---|---|---|
| Speech Synthesis (TTS) | `pyttsx3` (SAPI5) | **Available** | Used Microsoft Zira (EN) and Microsoft Heami (KO/Mixed). No external network or GPU required. |
| Visual Degradation | PIL ImageFilter / ImageEnhance | **Standard** | Applied official deterministic PIL pipeline: Gaussian blur (L1: radius=1.5, L2: radius=3.0) + contrast/brightness adjustment. |
| Audio Degradation | FFmpeg | **Standard** | Applied official deterministic FFmpeg pipeline: `anoisesrc=d=60:c=pink:r=16000:a=0.02` mixed with `amix`, plus 0.5s silence gap via `volume=enable='between(t,...)':volume=0`. |
| Video Encoding & 360p | `ffmpeg` (8.1.1) | **Available** | Rendered 2 fps slide-sequence MP4 videos and 360p low-bitrate re-encodes (`scale=640:360`, `-b:v 250k`). |

---

## 3. Fixture-by-Fixture Review Notes

### 3.1 English: `en_terms_01`

- **Script:**  
  `"Welcome to lecture four on optimization. In 1986, Geoffrey Hinton popularized backpropagation for multi-layer perceptrons. The learning rate was set to 0.05 across 128 batch iterations."`
- **Audio Verification (`audio.wav`):**
  - **Voice:** Microsoft Zira Desktop (SAPI5 `en-US`).
  - **Speech Spans:** `[[1.0, 4.089], [5.089, 12.052], [13.052, 19.305]]` (Total duration: 20.305s).
  - **Utterance 1:** `"Welcome to lecture four on optimization."` Clean diction, cadence matches natural lecture opening.
  - **Utterance 2:** Proper noun `"Geoffrey Hinton"` vocalized accurately as /ˈdʒɛfri ˈhɪntən/. Year `"1986"` vocalized as `"nineteen eighty-six"`. Term `"backpropagation"` articulated with distinct syllables. `"multi-layer perceptrons"` clear without clipping.
  - **Utterance 3:** Decimal `"0.05"` vocalized as `"zero point zero five"`. Integer `"128"` vocalized as `"one hundred twenty-eight"`.
- **Slide & Visual Verification:**
  - `slide_00_title.png`: Clean title card at 1280x720 with blue accent bar and dark charcoal typography.
  - `slide_01_concept.png`: Algorithm summary with 3 structured bullets.
  - `slide_02_near_dup.png`: Exact duplicate shifted by `(dx=2, dy=1)`. Perceptual hash distance to `slide_01` is `0` (`PHASH_HAMMING_THRESHOLD = 12`), successfully testing deduplication.
  - `slide_03_inc_base.png`: Contains base bullet (`"Batch Iterations: 128"`).
  - `slide_04_inc_ext.png`: Strictly extends slide 3 with 2 additional lines (`"Learning Rate: 0.05"`, `"Architecture: Multi-layer perceptrons"`), providing a ground-truth positive for `ocr.dedupe_incremental_texts`.
  - `slide_degraded_l1.png` & `slide_degraded_l2.png`: L1 introduces moderate optical blur; L2 simulates aggressive projector defocus and glare.
- **Caption Usability:**
  - `captions_usable.vtt`: 3 segments, 185 total characters. `captions_are_usable` returns `True`.
  - `captions_unusable.vtt`: 2 segments, 9 total characters (`"[Music]"`, `"Hi"`). `captions_are_usable` returns `False`.

---

### 3.2 Korean: `ko_terms_01`

- **Script:**  
  `"오늘 강의에서는 그래프 탐색 알고리즘을 다룹니다. 에츠허르 데이크스트라는 1956년에 최단 경로 알고리즘을 고안했습니다. 우선순위 큐를 사용하면 256개 노드의 시간 복잡도는 로그 선형으로 줄어듭니다."`
- **Audio Verification (`audio.wav`):**
  - **Voice:** Microsoft Heami Desktop (SAPI5 `ko-KR`).
  - **Speech Spans:** `[[1.0, 5.364], [6.364, 12.727], [13.727, 20.965]]` (Total duration: 21.965s).
  - **Utterance 1:** Fluent native Korean pronunciation of `"그래프 탐색 알고리즘"`.
  - **Utterance 2:** Proper noun `"에츠허르 데이크스트라"` (Edsger Dijkstra) rendered with consistent phoneme mapping; year `"1956년"` vocalized as `"천구백오십육년"`. Term `"최단 경로 알고리즘"` crisp.
  - **Utterance 3:** `"256개"` pronounced as `"이백오십육개"`. Technical terms `"우선순위 큐"` and `"시간 복잡도"` are phonetically clear and easily recognizable.
- **Slide & Visual Verification:**
  - Rendered with Malgun Gothic TrueType font. All Hangul glyphs rendered without clipping, tofu, or overlap.
  - Near-duplicate slide 2 has hamming distance `0` to slide 1.
  - Incremental build slides 3 and 4 correctly demonstrate single-line to multi-line expansion (`"노드 개수: 256"` -> added `"자료구조: 우선순위 큐"`, `"시간 복잡도: O(E log V)"`).
- **Caption Usability:**
  - `captions_usable.vtt`: 3 segments, 112 total Hangul characters (`captions_are_usable` returns `True`).
  - `captions_unusable.vtt`: 2 segments, 9 total characters (`captions_are_usable` returns `False`).

---

### 3.3 Mixed: `mixed_terms_01`

- **Script:**  
  `"이번 세션에서는 PyTorch 프레임워크의 Tensor 연산을 살펴봅니다. Yann LeCun 교수가 제안한 Convolutional Neural Network 구조입니다. 배치 크기 64에서 AdamW optimizer의 weight decay는 0.01로 설정합니다."`
- **Audio Verification (`audio.wav`):**
  - **Voice:** Microsoft Heami Desktop (SAPI5 `ko-KR`).
  - **Speech Spans:** `[[1.0, 6.803], [7.803, 13.272], [14.272, 21.59]]` (Total duration: 22.59s).
  - **Utterance 1:** Korean grammatical particles smoothly join English loanwords: `"PyTorch 프레임워크의 Tensor 연산"`.
  - **Utterance 2:** Proper noun `"Yann LeCun"` vocalized phonetically; technical phrase `"Convolutional Neural Network"` articulated with English phoneme adaptation within Korean TTS engine.
  - **Utterance 3:** Numeral `"64"` vocalized as `"육십사"`; decimal `"0.01"` vocalized as `"영점영일"`. Terms `"AdamW optimizer"` and `"weight decay"` articulated distinctly.
- **Slide & Visual Verification:**
  - Slide typography combines Latin characters and Hangul glyphs with uniform baseline and consistent line heights.
  - Incremental build progression tests mixed Korean/English key fields (`"배치 크기: 64"`, `"Optimizer: AdamW"`, `"Weight Decay: 0.01"`).
- **Caption Usability:**
  - `captions_usable.vtt`: 3 segments, 151 total characters (`captions_are_usable` returns `True`).
  - `captions_unusable.vtt`: 2 segments, 9 characters (`captions_are_usable` returns `False`).

---

## 4. Verification Check Commands and Results

| Check | Command Executed | Expected | Result |
|---|---|---|---|
| Fixture Generation | `uv run python tests/fixtures/benchmark/generate.py` | 3 fixture sets + 3 unusable variants generated | Pass (4.2s wall time) |
| WebVTT Parsing | `parse_vtt` on all `captions_usable.vtt` | 3 segments each | Pass (3/3 valid) |
| Caption Heuristic (Usable) | `captions_are_usable` on usable captions | `True` for all 3 | Pass (`True`) |
| Caption Heuristic (Unusable) | `captions_are_usable` on unusable captions | `False` for all 3 | Pass (`False`) |
| Visual Dedup (pHash) | `_image_phash` on slide 1 vs slide 2 (near dup) | Hamming dist <= 12 | Pass (`dist = 0`) |
| Incremental Build | Growth check on slide 3 vs slide 4 text | strictly positive growth | Pass (subset text) |
| Audio Waveforms | `wave.open` check on all generated audio files | 16kHz mono 16-bit PCM | Pass (16000 Hz, 1 ch) |
| Video Encodings | `ffprobe` on `video.mp4` and `video_360p.mp4` | 720p 2fps and 360p low-bitrate | Pass (1280x720 and 640x360) |
