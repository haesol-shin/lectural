# RALPLAN Consensus Plan: LecturAL (pending approval)

- run_id: 2026-06-13-0738-79e5
- 합의: Architect = CLEAR / APPROVE, Critic = OKAY (2회 반복)
- 원천 명세: `.gjc/specs/deep-interview-lectural.md` (AC-1..AC-13)
- 상태: **pending approval** — 실행 승인 전까지 코드/변경 없음

---

## RALPLAN-DR Summary

### Principles
1. **토큰-0 합성**: 외부 LLM API 호출 없음. 비싼 토큰은 쓰지 않는다.
2. **결정론적 raw**: 전사본·OCR·커버리지는 LLM 없이 재현 가능하게 생성.
3. **CPU-only**: 대학생 노트북에서 GPU 없이 동작 (faster-whisper int8).
4. **헤드리스 검증 가능**: 호스트 에이전트 없이도 모든 산출물이 생성·검증된다.
5. **완전성은 강제**: 사람이 "다 정리됐다"고 *믿는* 게 아니라 훅이 *증명*한다.

### Decision Drivers
1. 시험 기간 — 누락 없는 완전성이 최우선 (모든 발화·화면·장면).
2. 토큰/비용 제약 — 결정론적 파이프라인 + 호스트 에이전트 합성.
3. 빠른 프로토타이핑 + 노트북(CPU) 실행 가능성.

### Viable Options
- **Option A (초안)**: 결정론적 코어가 `synthesis_input.json`만 산출, summary.md는 *오직* 호스트 에이전트가 작성.
  - 단점(치명): 호스트 없이는 summary.md가 없어 AC-7/AC-8/AC-11 헤드리스 검증 불가, 완료 훅이 정직하지 못함.
- **Option A-prime (채택)**: 코어의 `synthesis.py`가 `synthesis_input.json`에서 **baseline summary.md**(TOC + 커버리지 헤더 + 섹션별 timestamp/slide 링크)를 결정론적으로 생성. 호스트 에이전트 보강(enrichment)은 *선택* 레이어.
  - 장점: 토큰-0·결정론·CPU 원칙 유지하면서 헤드리스 검증·정직한 게이트 확보.
- **Option B (로컬 LLM 요약)**: Ollama로 요약. → defer 제약 위반, CPU에서 느림. **무효.**
- **Option C (영상 직접 LLM 투입)**: 멀티모달 LLM에 프레임 투입. → 토큰-0 위반, 비용 폭발. **무효.**

**채택: Option A-prime** — 유일하게 5대 원칙을 모두 만족.

---

## 아키텍처 개요 (Option A-prime)

```
URL(s) ──► [lectural core: 결정론적 CPU 파이프라인] ──► output/<video>/
                                                          ├─ transcript.md   (raw, 타임스탬프)
                                                          ├─ summary.md       (baseline, 결정론적)
                                                          ├─ frames/*.png      (슬라이드)
                                                          └─ coverage.json     (게이트 입력)
                          │
                          └─(선택) 호스트 에이전트 enrichment ─► summary.md 보강(앵커 보존)

[Stop hook] ── coverage.json + summary.md 앵커 검증 ── 실패 시 exit 2 (완료 차단)
```

핵심: 코어는 스킬과 **독립 실행 가능한 Python CLI/모듈**(AC-11). 스킬은 얇은 래퍼 + (선택) enrichment + 완료 게이트.

---

## 제안 리포지토리 레이아웃

```
LecturAL/
├─ pyproject.toml                 # deps: yt-dlp, youtube-transcript-api, faster-whisper, opencv-python, paddleocr, pytesseract(폴백), webrtcvad
├─ lectural/
│  ├─ __init__.py
│  ├─ cli.py                      # 진입점: lectural <url...> [--force-stt] [--model] [--out]  (AC-1, AC-2, AC-11)
│  ├─ deps.py                     # ffmpeg/yt-dlp/paddleocr preflight + 명확한 에러 (binary detection)
│  ├─ acquisition.py              # yt-dlp 자막 우선 + youtube-transcript-api 폴백, audio 추출 (AC-1,2,3)
│  ├─ speech.py                   # faster-whisper medium int8 CPU, ko/en auto, 길이 경고 (AC-3,4)
│  ├─ vad.py                      # ffmpeg silencedetect / webrtcvad 침묵 마스크 (AC-9)
│  ├─ visual.py                   # ffmpeg I-frame+scene 추출(2fps), 히스토그램/SSIM dedup (AC-5)
│  ├─ ocr.py                      # PaddleOCR(PP-OCRv5) 주 + Tesseract 폴백, 점증 슬라이드 re-split (AC-6)
│  ├─ synthesis.py                # synthesis_input.json + baseline summary.md(앵커) 결정론적 생성 (AC-7,8,12)
│  ├─ coverage.py                 # coverage.json 산출 (gap/scene/artifact) (AC-13)
│  ├─ runstate.py                 # active-run 포인터(env + state 파일) — 훅이 검증할 run 식별
│  └─ config.py                   # dedup 임계 등 명명 상수 (DEDUP_HIST_THRESHOLD, DEDUP_SSIM_THRESHOLD, MAX_GAP_SEC=60, SCENE_BINS_N)
├─ scripts/
│  └─ completeness_hook.py        # coverage.json + summary.md 앵커 검증, 실패 시 exit 2 (AC-13)
├─ .claude/
│  └─ skills/lectural/
│     ├─ SKILL.md                 # frontmatter + body(<=2000단어) + enrichment 지시 (AC-10)
│     └─ references/              # 상세 파이프라인/스키마 문서
│  └─ settings.json               # Stop 훅 wiring → python scripts/completeness_hook.py
├─ tests/
│  ├─ test_dedup.py  test_coverage.py  test_vad.py  test_ocr.py  test_summary_anchors.py
│  └─ fixtures/                   # long_silence, real_gap, ko_slide, en_slide, no_caption
└─ output/                        # 산출물 (gitignore)
```

---

## 단계별 작업 (AC 매핑)

| Phase | 작업 | AC |
|------|------|----|
| **P1 Scaffold** | pyproject + 패키지 골격, `deps.py` ffmpeg/yt-dlp/paddleocr preflight(없으면 명확 에러), `config.py` 상수 | AC-10, AC-11 |
| **P2 Acquisition** | yt-dlp 자막(`--write-subs/--write-auto-subs --skip-download` json3/vtt) + youtube-transcript-api 폴백; 자막 없거나 `--force-stt`면 audio 추출 | AC-1, AC-2, AC-3 |
| **P3 Speech** | faster-whisper medium int8 CPU, ko/en auto, 타임스탬프 세그먼트; 과길이 경고 + 모델 오버라이드 | AC-3, AC-4 |
| **P4 VAD/Coverage-speech** | `vad.py` 침묵 마스크 → `max_non_silence_untranscribed_gap_sec` 계산 (wall-clock 비율 폐기) | AC-9 |
| **P5 Visual** | ffmpeg I-frame+scene 추출(2fps), 히스토그램/SSIM dedup → 슬라이드 후보 `frames/` | AC-5 |
| **P6 OCR** | PaddleOCR(ko/en) 주 + Tesseract 폴백(+degraded 경고), `ocr_engine` 기록, 점증 슬라이드 re-split | AC-6 |
| **P7 Synthesis** | `synthesis_input.json`(schema_version) + baseline `summary.md`(TOC+coverage 헤더+섹션별 timestamp/slide 링크) + raw `transcript.md` 결정론적 생성 | AC-7, AC-8, AC-12 |
| **P8 Coverage** | `coverage.py` → `coverage.json` {gapCheck, sceneCoverage, artifactExists, ocr_engine} | AC-13 |
| **P9 Packaging** | SKILL.md(frontmatter+body) + settings.json Stop 훅 wiring + references; (선택) enrichment 지시 | AC-10 |
| **P10 Hook** | `completeness_hook.py`: runstate로 대상 run 식별, 비-LecturAL run no-op(exit0), 3검사+summary 앵커 검증, 실패 exit2 | AC-8, AC-13 |
| **P11 Verify** | AC 검증 매트릭스 전수 실행(아래) | AC-1..13 |

---

## Synthesis 핸드오프 계약 (토큰 최소화)

`synthesis_input.json` (코어가 결정론적으로 생성, 호스트 enrichment 입력):
```json
{
  "schema_version": 1,
  "video": {"title": "...", "url": "...", "duration_sec": 0, "language": "ko|en"},
  "transcript_segments": [{"t": 12.4, "text": "..."}],     // 압축·정규화된 텍스트만 (이미지 미포함)
  "slides": [{"t": 30.0, "frame": "frames/0003.png", "ocr_text": "...", "is_slide": true}],
  "section_hints": [{"t": 0, "title": "..."}]              // scene/슬라이드 경계 기반
}
```
- 토큰 절감: 자막 우선(전사 생략) → 프레임 dedup(시각 입력 최소) → **텍스트만** 호스트에 투입(원본 이미지 미투입) → 핵심 프레임만(STORM/MDP3 한계효용 근거).
- baseline summary.md는 코어가 이 JSON으로 **직접** 작성(토큰-0). 호스트 enrichment는 동일 앵커를 보존한 채 산문만 보강.

---

## 완료 게이트 훅 설계

- **트리거**: Stop 훅 (`.claude/settings.json`), `python scripts/completeness_hook.py` (Windows 이식성 위해 bash 대신 Python; 인터프리터는 `sys.executable`/`py -3` 해석 — follow-up D).
- **대상 식별**: `runstate.py`가 CLI 실행 시 active output-dir를 env/state 파일에 기록; 훅은 그 run의 `coverage.json`을 읽음. 비-LecturAL 실행이면 no-op(exit 0).
- **3검사** (하나라도 실패 → exit 2, 완료 차단):
  1. **gapCheck**: `max_non_silence_untranscribed_gap_sec <= 60` (VAD 침묵 마스크 기준 — 무음/미전사 혼동 제거).
  2. **sceneCoverage**: 전 구간 키프레임 존재 + 슬라이드 분류 프레임에 OCR 텍스트 존재.
  3. **artifactExists**: `transcript.md`, `summary.md` 존재·비어있지 않음 **AND** summary.md 필수 앵커(TOC, coverage 헤더, 섹션 링크) 검증(AC-8).

---

## AC 검증 매트릭스 (요약)

| AC | 명령/방법 | 픽스처/URL | 기대 결과 |
|----|-----------|-----------|-----------|
| AC-1 | `lectural <url>` | 자막 있는 짧은 공개 강의 | `output/<title>/` 생성 |
| AC-2 | `lectural <url1> <url2>` | 2개 URL | URL별 폴더, 순차 |
| AC-3 | 자막 경로 vs `--force-stt` | no_caption 픽스처 | 자막 없으면 STT 자동 |
| AC-4 | STT 단독 | no_caption | medium int8, 타임스탬프 전사 |
| AC-5 | `test_dedup.py` | 합성 프레임열 | over/under dedup 경계 통과 |
| AC-6 | `test_ocr.py` | ko_slide, en_slide | OCR 텍스트 추출, `ocr_engine` 기록 |
| AC-7 | 산출 확인 | 위 URL | transcript.md + summary.md |
| AC-8 | `test_summary_anchors.py` | 생성된 summary.md | TOC+coverage+링크 앵커 존재 |
| AC-9 | `test_vad.py` | long_silence(PASS), real_gap(FAIL) | gap 게이트 정확 |
| AC-10/11 | 스킬 호출 + CLI 단독 실행 | — | 둘 다 동작 |
| AC-12 | 경로 확인 | — | transcript/summary/frames/coverage.json |
| AC-13 | 훅 실행 | real_gap run | exit 2; 정상 run exit 0 |

---

## 리스크 & 완화

| 리스크 | 완화 |
|--------|------|
| yt-dlp 포맷 깨짐(분기당 1회) | 버전 핀 + acquisition 출력 스모크 체크 + youtube-transcript-api 폴백 |
| CPU STT 장시간 지연 | medium 기본 + 과길이 경고/사용자 선택 + 모델 오버라이드 |
| PaddleOCR Windows 설치 무게 | `deps.py` preflight + Tesseract degraded 폴백 + `ocr_engine` 기록 |
| 한국어 OCR 정확도 | ko 픽스처 회귀 테스트, PP-OCRv5 ko |
| frame dedup 튜닝 | 명명 상수 기본값 + over/under dedup 단위 테스트 |
| VAD 정확도(신규 신뢰점) | 임계 핀 + quiet-speech 픽스처 + webrtcvad 교차검증(follow-up B) |

---

## 비목표 (v1 defer)
병렬 배치, 로컬 LLM 요약 폴백, 비개발자 UI, GPU 경로, diarization/번역, OCR 실패율 게이트.

---

## ADR

- **Decision**: Option A-prime — 결정론적 Python 코어가 raw 전사본 + baseline summary.md + coverage.json을 생성하고, 호스트 에이전트 enrichment는 선택. 완료는 Stop 훅이 강제.
- **Drivers**: 완전성 최우선, 토큰-0, CPU 노트북, 헤드리스 검증, 빠른 프로토타입.
- **Alternatives considered**: A(호스트 전용 요약 — 헤드리스 검증 불가로 폐기), B(로컬 LLM — defer/느림), C(영상 LLM 직접 — 토큰 위반).
- **Why chosen**: 5대 원칙을 모두 만족하는 유일안. 정직한 완료 게이트 확보.
- **Consequences**: 코어가 baseline 요약 품질을 책임 → 호스트 보강은 가산적. 산출물·검증이 결정론적이라 회귀 테스트 용이. enrichment/baseline 분기 관리 필요.
- **Follow-ups (비차단, 구현 시점)**:
  - A: Stop 훅이 마지막 run만 검증 → 세션 내 전 run 재검사 루프 추가(AC-2 부분통과 구멍).
  - B: VAD 임계 핀 + quiet-speech 픽스처 + webrtcvad 교차검증.
  - C: `synthesis_input.json`에 `schema_version: 1` 명시 + contract 문서화.
  - D: 훅 인터프리터 하드코딩 제거 → `sys.executable`/`py -3` 해석.
