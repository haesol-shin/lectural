# LecturAL 구현 계획 v4 (Planner / RALPLAN-DR, 재검토 반영)

> 출처: `.gjc/specs/deep-interview-lectural.md` (li-2026-0613, PASSED). 모든 태스크는 AC-1..AC-13에 매핑. 산문은 한국어, 식별자/경로/명령/JSON 키는 영어.
> 이번 개정(stage_n=4)은 Architect WATCH(4 HIGH) + Critic ITERATE 반영: (A-prime 헤드리스 검증, VAD 기반 gap, 훅 run 포인터/구조검증, AC 매트릭스, OCR/visual 강화).

## 1. RALPLAN-DR 요약 (개정)

### Principles
- **P1 결정론 우선, LLM 토큰 0**: raw 전사본·OCR·dedup·coverage **및 baseline summary.md**까지 전부 비-LLM 결정론 파이프라인으로 생성. 외부 API 토큰 0. 호스트 에이전트 요약은 baseline 위 **선택적 enrichment 레이어**일 뿐, 산출물 존재/검증은 헤드리스로 보장. (AC-7, AC-8, AC-9, AC-11, AC-13)
- **P2 파이프라인/스킬 분리**: 핵심 로직은 `lectural` 파이썬 패키지(CLI 단독 실행, 호스트 없이 완주). 스킬은 얇은 래퍼 + enrichment. (AC-10, AC-11)
- **P3 CPU 우선·외부 바이너리 명시**: faster-whisper int8 CPU, ffmpeg/yt-dlp 시작 시 탐지·없으면 명확 실패. (CPU 제약)
- **P4 완전성은 자동 게이트로 강제**: 신뢰는 사람이 아니라 coverage.json + Python hook이 보증. (AC-13)
- **P5 캡션 우선·압축 입력·침묵 인지**: 자막 있으면 STT 생략, 프레임 dedup·압축 텍스트만 enrichment에 투입. 커버리지는 wall-clock이 아니라 VAD 기반 침묵 마스크로 판정. (AC-3, AC-9, 토큰 최소화)

### Decision Drivers (top 3)
1. **토큰/비용 최소화**: 외부 API 토큰 0, 컨텍스트 입력 최소화.
2. **CPU 노트북 실행 가능성**: GPU 없는 Intel Core Ultra 5 합리적 시간 완주.
3. **완전성 보증 + 헤드리스 검증 가능성**: 호스트 없이도 산출물이 존재·검증되어야 한다(Architect HIGH-4).

### Viable Options (아키텍처)
**Option A-prime — 결정론적 baseline summary + 선택적 호스트 enrichment (채택, 개정)**
- 코어: `lectural`가 acquisition→speech→visual→ocr→synthesis→coverage까지 결정론적으로 실행. `synthesis.py`가 `synthesis_input.json`으로부터 **baseline `summary.md`를 결정론적으로 작성**(필수 앵커: TOC, coverage 헤더, 섹션별 timestamp + slide 링크). 그 위에 호스트 에이전트가 산문 품질을 보강(enrichment)하되, 보강이 없어도 AC-7/AC-8/AC-13은 충족.
- Pros: 외부 토큰 0 유지(baseline은 LLM 무관, enrichment는 호스트=외부 API 0), 결정론적 raw 유지, CPU-only, **헤드리스 검증 가능**(HIGH-4 해소), AC-7/8/11/13 동시 충족.
- Cons: baseline 요약은 추출형(섹션 라벨/요지)이라 산문 품질은 enrichment 전까지 제한적 → 의도된 트레이드오프.
- 이전 Option A(요약을 호스트에만 의존)는 산출물이 호스트 없이는 미존재/미검증이라 AC-13 헤드리스 게이트와 충돌 → A-prime로 대체.

**Option B — 코어가 로컬 LLM(Ollama)로 요약 완결**
- Pros: 스킬 외부에서도 요약 완결.
- Cons: 로컬 LLM 설치/무게, CPU 추론 느림, 스펙 명시 **defer**. → v1 무효.

**Option C — 영상을 멀티모달 LLM에 직접 투입해 전사+요약 일괄**
- Pros: 파이프라인 단순.
- Cons: 토큰 폭발(핵심 제약 위반), 긴 강의 비현실, 결정론적 완전성 보증 불가. → 무효.

### Invalidation Rationale
B/C는 토큰-0/defer 제약 위반으로 무효. 구(舊) Option A는 헤드리스 검증 불가로 무효화하고 **Option A-prime 채택**: baseline 결정론 + enrichment 선택.

---

## 2. 제안 리포지토리 레이아웃 (개정)

```
LecturAL/
  pyproject.toml              # 패키지 메타+의존 — AC-11
  requirements.txt            # 핀 고정 의존(yt-dlp 등) — AC-11, 리스크 완화
  README.md                   # 사용법/바이너리 사전조건/OCR 설치
  lectural/                   # 재사용 코어 패키지 — AC-11
    __init__.py
    cli.py                    # argparse 엔트리(단일/순차배치, --force-stt, --model) + active-run 포인터 기록 — AC-1,AC-2,AC-3,AC-4,AC-11
    config.py                 # 임계값 상수(HIST_DEDUP_THRESHOLD, SSIM_DEDUP_THRESHOLD, MAX_GAP_SEC, SCENE_BUCKETS 등) — AC-4,AC-5,AC-9
    binaries.py               # ffmpeg/yt-dlp 탐지·버전체크 — 제약(바이너리)
    runstate.py               # active-run 포인터 read/write(.gjc/state 또는 env LECTURAL_OUTPUT_DIR) — AC-13
    acquisition.py            # yt-dlp 캡션우선 + audio 폴백 + 메타 — AC-1,AC-2,AC-3
    speech.py                 # faster-whisper medium int8 CPU STT — AC-3,AC-4
    vad.py                    # ffmpeg silencedetect / webrtcvad 침묵 마스크 — AC-9,AC-13
    visual.py                 # ffmpeg I-frame/scene 추출 + dedup(임계 상수) — AC-5
    ocr.py                    # PaddleOCR 1차 / Tesseract 폴백 + preflight + 슬라이드 re-split — AC-6,AC-13
    synthesis.py              # 트랙 정렬→transcript.md + synthesis_input.json + baseline summary.md — AC-7,AC-8,AC-9
    coverage.py               # coverage.json 생성(speech gap/ scene/ artifact/ ocr_engine) — AC-12,AC-13
    summary_validate.py       # summary.md 구조(TOC/coverage 헤더/링크) 검증 — AC-8,AC-13
    models.py                 # dataclass: Segment, Frame, SpeechMask, CoverageReport
    utils.py                  # 타임스탬프 포맷, slug, io
  scripts/
    run_lectural.py           # 스킬 thin runner(cli 위임) — AC-10
    completeness_hook.py      # Stop 훅(파이썬, exit 2), run 포인터 사용 — AC-8,AC-13
  .claude/
    skills/lectural/SKILL.md  # frontmatter + body(<=2000단어) — AC-10
    settings.json             # Stop 훅 wiring(python) — AC-13
  references/
    pipeline.md
    synthesis_contract.md     # synthesis_input.json 스키마 + baseline/enrichment 규칙
    troubleshooting.md        # yt-dlp 깨짐/STT 길이/OCR 설치
  tests/
    test_dedup.py             # over/under-dedup + 점증 슬라이드 re-split — AC-5
    test_coverage.py          # VAD gap(침묵 PASS / 실공백 FAIL) + scene + artifact — AC-9,AC-13
    test_synthesis.py         # synthesis_input 스키마 + baseline summary 앵커 — AC-7,AC-8
    test_summary_validate.py  # 구조 검증 — AC-8
    test_hook.py              # exit 0/2 + no-op(비-LecturAL run) — AC-13
    fixtures/
      captions_video/         # 캡션 보유(AC-3 caption 경로)
      nocaption_video/        # 무자막(AC-3/4 STT 경로) 또는 --force-stt
      long_silence/           # 긴 정당 침묵 → gap 게이트 PASS
      real_gap/               # 실제 미전사 구간 → gap 게이트 FAIL
      slide_ko/ slide_en/     # OCR ko/en 픽스처
      incremental_slide/      # 한 줄씩 자라는 슬라이드(re-split 대상)
      frames_seq/             # dedup 단위용 합성 프레임열
  output/                     # 런타임 산출물(.gitignore) — AC-12
    <video-title>/
      transcript.md  summary.md  coverage.json  synthesis_input.json  frames/*.png
```
AC 정당화: `synthesis.py`(baseline summary → AC-7/8 헤드리스), `vad.py`+`coverage.py`(AC-9/13), `runstate.py`+`completeness_hook.py`(AC-13 run 식별), `summary_validate.py`(AC-8 구조), `ocr.py`(AC-6 degraded-mode/ocr_engine), `cli.py --force-stt`(AC-3/4 테스트가능).

---

## 3. 단계별 태스크 (Phase 1..11) — AC 매핑

**Phase 1 — Scaffold + 의존 + 바이너리 탐지** (AC-11, AC-1)
- T1.1 pyproject/requirements 핀(yt-dlp/faster-whisper/paddleocr/pytesseract/youtube-transcript-api/opencv/Pillow/webrtcvad). (AC-11)
- T1.2 `binaries.py`: ffmpeg/yt-dlp 탐지, 없으면 설치 안내 포함 명확 에러. (제약)
- T1.3 `config.py` 임계 상수 + `models.py`/`utils.py` 골격. (AC-4,AC-5,AC-9,AC-12)
- T1.4 `cli.py` argparse: `urls+`, `--model`, `--force-stt`, `--max-duration-warn`, `--output-dir`. (AC-1,AC-2,AC-3,AC-4)

**Phase 2 — Acquisition (캡션 우선 + 오디오 폴백)** (AC-1,AC-2,AC-3)
- T2.1 메타(title/duration/lang) + `output/<slug>/` 생성. (AC-1,AC-12)
- T2.2 yt-dlp `--write-subs --write-auto-subs --skip-download`(json3/vtt) 파싱. (AC-3)
- T2.3 `youtube-transcript-api` 텍스트 폴백. (AC-3)
- T2.4 캡션 부재/부실 또는 `--force-stt` 시 오디오 다운로드. (AC-3)
- T2.5 다중 URL 순차 + URL별 폴더/에러 격리. (AC-2)

**Phase 3 — Speech (faster-whisper CPU int8)** (AC-3,AC-4)
- T3.1 medium int8 CPU 로드, ko/en 자동. (AC-4)
- T3.2 타임스탬프 세그먼트 STT → `Segment[]`. (AC-4)
- T3.3 긴 영상 경고 + `--model` 오버라이드. (AC-4)
- T3.4 caption/STT 동일 `Segment` 정규화. (AC-3)

**Phase 4 — VAD / 침묵 마스크** (AC-9,AC-13) [HIGH-1]
- T4.1 ffmpeg `silencedetect`(1차) / webrtcvad(폴백)로 `SpeechMask`(speech 구간 리스트) 생성. (AC-9)
- T4.2 transcript 세그먼트와 speech 마스크 비교 → `max_non_silence_untranscribed_gap_sec` 산출(침묵 구간 제외). (AC-9,AC-13)

**Phase 5 — Visual (키프레임 + dedup)** (AC-5) [HIGH-OCR/visual]
- T5.1 ffmpeg I-frame+scene(2fps) 추출. (AC-5)
- T5.2 dedup: `HIST_DEDUP_THRESHOLD`/`SSIM_DEDUP_THRESHOLD` 상수 기반 히스토그램+SSIM. (AC-5)
- T5.3 슬라이드/장면 분류 + `frames/` 저장 + `Frame` 메타. (AC-5,AC-12)

**Phase 6 — OCR (PaddleOCR / Tesseract)** (AC-6,AC-13) [HIGH-OCR/visual]
- T6.1 PaddleOCR preflight(import/모델 로드 점검); 실패 시 Tesseract degraded-mode + 경고 로그 + `ocr_engine` 기록. (AC-6,AC-13)
- T6.2 PP-OCRv5 ko/en 1차 OCR. (AC-6)
- T6.3 post-OCR re-split: 점증 슬라이드(줄 단위 누적)가 1장으로 collapse되지 않도록 텍스트 증분 기준 분리. (AC-5,AC-6)
- T6.4 `Frame.ocrText` 결합, 빈텍스트 허용(비슬라이드 정상). (AC-6,AC-13)

**Phase 7 — Synthesis (결정론 raw + baseline summary)** (AC-7,AC-8,AC-9) [HIGH-4]
- T7.1 두 트랙 시간축 정렬·병합. (AC-7)
- T7.2 `transcript.md`(raw, 타임스탬프) 결정론 생성. (AC-7)
- T7.3 `synthesis_input.json` 생성(압축). (토큰 최소화)
- T7.4 **baseline `summary.md` 결정론 생성**: TOC + coverage 헤더 + 섹션별 `transcript.md` 앵커/`frames/NNNN.png` 링크. (AC-7,AC-8)

**Phase 8 — Coverage 체커** (AC-9,AC-12,AC-13)
- T8.1 dialogue gap: VAD 마스크 기반 `max_non_silence_untranscribed_gap_sec <= MAX_GAP_SEC(60)`. (AC-9)
- T8.2 scene coverage: 전 구간 `SCENE_BUCKETS` 분할 각 버킷 키프레임 1+ AND `slides_with_text >= 1`. (AC-13)
- T8.3 artifact 존재·비어있음 + `ocr_engine` 기록 → `coverage.json`. (AC-12,AC-13)

**Phase 9 — SKILL.md 패키징 + 핸드오프 계약** (AC-10)
- T9.1 SKILL.md frontmatter + body(<=2000단어): 코어 호출 + baseline 설명 + enrichment 규칙 + 게이트. (AC-10)
- T9.2 `references/synthesis_contract.md`: synthesis_input → enrichment 규칙(baseline 앵커 보존 필수). (AC-8,AC-10)

**Phase 10 — 완료 훅** (AC-8,AC-13) [HIGH-2/HIGH-3]
- T10.1 `cli.py`가 run 시작 시 active-run 포인터(`runstate.py`: env `LECTURAL_OUTPUT_DIR` + `.gjc/state/lectural/active.json`) 기록; 배치는 마지막 완료 run을 검증 대상으로 명시. (AC-13)
- T10.2 `scripts/completeness_hook.py`: stdin JSON 읽기 → run 포인터로 output dir 결정 → 포인터 없거나 비-LecturAL run이면 **no-op(exit 0)** → coverage.json 3검사 + `summary_validate`로 summary.md 앵커 검증 → 실패 시 stderr 사유 + exit 2. (AC-8,AC-13)
- T10.3 wiring: `.claude/settings.json` **Stop** 훅(matcher 전체), 명령 `python scripts/completeness_hook.py`(Windows 포터빌리티). SKILL frontmatter는 문서 참조만. (AC-13)

**Phase 11 — 검증** (AC-1..AC-13)
- T11.1 단위(dedup/re-split/coverage VAD/synthesis/summary_validate/hook). 
- T11.2 §6 매트릭스대로 E2E 스모크(캡션/STT/배치).

---

## 4. Synthesis 핸드오프 계약 (개정)

`synthesis.py`는 (1) `transcript.md`(전체 raw) (2) `synthesis_input.json`(압축) (3) **baseline `summary.md`**(앵커 포함, 결정론)을 생성한다. 호스트 enrichment는 baseline 앵커를 보존하며 산문만 보강한다.

```json
{
  "video": { "title": "string", "url": "string", "duration_sec": 0, "language": "ko|en", "transcript_source": "caption|stt" },
  "outline": [ { "t": 0.0, "label": "string(섹션 힌트)" } ],
  "segments": [ { "t": 0.0, "end": 0.0, "text": "compact speech text" } ],
  "slides": [ { "t": 0.0, "frame": "frames/0001.png", "ocr": "deduped slide text" } ],
  "coverage": { "max_non_silence_untranscribed_gap_sec": 0, "speech_duration_sec": 0, "scene_buckets_covered": 0, "scene_buckets_total": 0, "slide_count": 0, "slides_with_text": 0, "ocr_engine": "paddleocr|tesseract" },
  "links": { "transcript_md": "transcript.md", "frames_dir": "frames/" }
}
```
**토큰 최소화**: caption-first(STT 생략), frame dedup(1000→~30장, 경로만 전달·픽셀 미투입), compact text only(전체 raw는 파일 링크). baseline summary는 추출형이라 LLM 불필요.

baseline `summary.md` 필수 앵커(AC-8): 상단 TOC, coverage 헤더(gap/scene/slides/ocr_engine), 각 섹션 `[t]( transcript.md#Lxx )` + `![slide]( frames/NNNN.png )` 링크. `summary_validate.py`가 이 앵커 존재를 검증.

---

## 5. 완료 훅 설계 (개정, HIGH-2/3)

- **run 식별(추측 금지)**: `cli.py`가 시작 시 `runstate.write(output_dir)` → env `LECTURAL_OUTPUT_DIR` 및 `.gjc/state/lectural/active.json`. 훅은 stdin hook JSON + 이 포인터로 검증 대상 output dir을 결정.
- **배치 의미**: 순차 배치는 각 run 종료마다 포인터 갱신; Stop 훅은 **마지막 완료 run** 검증(각 run 폴더는 디스크에 남아 후속 점검 가능).
- **no-op**: 포인터 없음/비-LecturAL run/coverage.json 부재면 exit 0(무간섭).
- **트리거**: `.claude/settings.json`의 **Stop** 훅(matcher: 전체). PostToolUse 아님(완료 시점 차단이 목적).
- **3검사 + summary 구조검사**:
  1. speech gap: `max_non_silence_untranscribed_gap_sec <= 60`(VAD 마스크 기반, 침묵≠미전사). (AC-9)
  2. scene: `scene_buckets_covered == scene_buckets_total` AND `slides_with_text >= 1`. (AC-13)
  3. artifact: `transcript.md`·`summary.md` 존재+비어있지 않음. (AC-7,AC-12)
  4. summary 구조: `summary_validate`로 TOC/coverage 헤더/섹션 링크 앵커 존재. (AC-8)
- **차단**: 하나라도 실패 시 stderr 사유 + **exit 2**. 통과 exit 0. 명령은 `python scripts/completeness_hook.py`(Windows 포터빌리티).

---

## 6. AC-1..AC-13 검증 매트릭스

| AC | 명령 | URL/픽스처 | 기대 산출물 | 기대 coverage.json | 훅 exit |
|----|------|-----------|------------|--------------------|---------|
| AC-1 | `python -m lectural.cli <URL>` | captions_video(공개 짧은 강의) | `output/<slug>/` 생성 | 생성됨 | 0 |
| AC-2 | `python -m lectural.cli <URL1> <URL2>` | captions_video x2 | slug별 2폴더 | 각 폴더 coverage | 0 |
| AC-3 | `cli <URL>` vs `cli --force-stt <URL>` | captions_video / nocaption_video | transcript.md | `transcript_source: caption` vs `stt` | 0 |
| AC-4 | `cli --force-stt <URL>` | nocaption_video | 타임스탬프 transcript.md | source=stt, gap<=60 | 0 |
| AC-5 | `pytest tests/test_dedup.py` | frames_seq, incremental_slide | frames/ 축소 | slide_count 합리 | n/a |
| AC-6 | `pytest`(ko/en) + 스모크 | slide_ko/slide_en | OCR 텍스트 | ocr_engine 기록, slides_with_text>=1 | n/a |
| AC-7 | E2E | captions_video | transcript.md + summary.md | artifact ok | 0 |
| AC-8 | `pytest tests/test_summary_validate.py` | baseline summary.md | TOC/헤더/링크 | n/a | 0(있음)/2(없음) |
| AC-9 | `pytest tests/test_coverage.py` | long_silence(PASS), real_gap(FAIL) | n/a | gap<=60 vs >60 | 0 vs 2 |
| AC-10 | 스킬 호출 | SKILL.md | 산출물 | ok | 0 |
| AC-11 | `python -m lectural.cli --help` + E2E(호스트 없이) | captions_video | 산출물 완주 | ok | 0 |
| AC-12 | E2E | captions_video | transcript/summary/coverage.json/frames/ | 모든 필드 | 0 |
| AC-13 | `pytest tests/test_hook.py` + E2E | 통과/실패 coverage 주입 | n/a | 실패 케이스 | 0 / 2 |

단위 결정론: dedup/re-split/VAD gap/synthesis/summary_validate/hook. 실영상 스모크: acquisition/speech/ocr 정확도(공개 짧은 강의 + 무자막은 `--force-stt`로 강제).

---

## 7. 리스크 + 완화 (개정)

- **yt-dlp 깨짐**: 버전 핀 + troubleshooting 업그레이드 절차, acquisition 실패 시 youtube-transcript-api 폴백 + 명확 에러. 분기당 점검.
- **CPU STT 지연**: medium int8 기본, `--max-duration-warn` + `--model` 다운그레이드 오버라이드, 진행 로그.
- **PaddleOCR Windows 설치 무게**: T6.1 preflight, 실패 시 Tesseract degraded-mode 자동 + 명시 경고 + `ocr_engine` coverage 기록, README 설치/대안 명시.
- **frame-dedup 튜닝**: `HIST_DEDUP_THRESHOLD`/`SSIM_DEDUP_THRESHOLD` config 상수 + over/under-dedup 단위 테스트 회귀.
- **점증 슬라이드 collapse**: post-OCR re-split(T6.3) + incremental_slide 픽스처 테스트.
- **한국어 OCR 정확도**: PP-OCRv5 ko 우선, ko/en 픽스처 테스트, 저신뢰는 enrichment 비전 보강(토큰 주의, 선택), 게이트는 OCR 실패율 미사용.
- **침묵 오판(HIGH-1)**: VAD 마스크로 침묵≠미전사 분리, long_silence(PASS)/real_gap(FAIL) 픽스처로 회귀.

---

## 8. 비목표 / Deferred (재확인)
병렬 배치(순차만), 로컬 LLM(Ollama) 요약 폴백, 비개발자 UI/웹/데스크톱, GPU 가속 경로, 화자 분리·자동 번역·퀴즈 생성, OCR 실패율을 완료 게이트로 사용. 모두 v1 제외(모듈 분리로 확장 여지 유지). 호스트 enrichment는 baseline 위 선택적 레이어로만 존재.

---

## 9. Handoff
- **Architect**: A-prime baseline summary 구조의 충분성, runstate 포인터 동시성(배치), VAD 엔진 선택(silencedetect vs webrtcvad) 검토.
- **Critic**: 임계 상수 기본값(MAX_GAP_SEC/SCENE_BUCKETS/dedup), 픽스처 커버리지(long_silence/real_gap/incremental_slide/ko/en) 충분성.
- **executor**: Phase 1→11 순차 구현, 단위 테스트 동반.
- **ultragoal/team**: 다회차면 Phase 단위 goal 분할.
