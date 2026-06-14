# Deep Interview Spec: LecturAL 파이프라인 품질 개선 (트랙 2)

## Metadata
- Interview ID: li-quality-2026-0614
- Rounds: 8
- Final Ambiguity Score: 4.7%
- Type: brownfield
- Generated: 2026-06-13T22:22:00Z
- Threshold: 0.05
- Threshold Source: default
- Status: PASSED
- Auto-Researched Rounds: []
- Auto-Answered Rounds: []
- Architect Failures: 0

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.97 | 0.35 | 0.3395 |
| Constraint Clarity | 0.95 | 0.25 | 0.2375 |
| Success Criteria | 0.94 | 0.25 | 0.2350 |
| Context Clarity | 0.94 | 0.15 | 0.1410 |
| **Total Clarity** | | | **0.953** |
| **Ambiguity** | | | **0.047** |

## Topology
| Component | Status | Description | Coverage |
|-----------|--------|-------------|----------|
| 메타데이터·폴더명 | active | title/duration 취득, 폴더=제목 | R7 |
| 타임스탬프/TOC | active | duration 복구로 섹션 타임스탬프 정상화 | R7 |
| summary 재설계 | active | 3-파일 분리 + 자동 보강 | R1,R5 |
| 슬라이드 중복제거 | active | perceptual hash + temporal | R2 |
| OCR 품질 | active | 전처리 + 2.x 핀 + bake-off, KO/EN | R4,R8 |
| 프레임 정리 | active | 슬라이드만 남김 + --keep-frames | R6 |

## Goal
LecturAL의 실제 생성물 품질을 경쟁 도구 parity 수준으로 끌어올린다. 확인된 6개 버그/품질 문제를 고친다: (1) 폴더명=영상 제목, (2) TOC 타임스탬프 실제 값, (3) summary.md=진짜 요약(목차는 outline.md 분리, 자동 보강), (4) 발표자 움직임에 강건한 중복제거, (5) KO/EN OCR 품질, (6) 원본 프레임 정리. 제품 USP는 **검증 가능한 완전성(no-omission) + 시각(슬라이드/OCR) 캡처 + verbatim 전사, KO/EN 둘 다 1급**으로 확정한다(경쟁 불만으로 검증: 대부분 오디오만·놀침·신뢰 부족). 플러그인/경량은 셀링포인트에서 제외.

## Constraints
- 제품 코어(lectural/) 변경 허용(트랙 1 동결 해제). 단 완전성 게이트의 2계층 계약(CLI exit 1차 + Claude Stop 훅)은 유지.
- 토큰 0 원칙 유지: summary 산문 보강은 외부 LLM API가 아니라 호스트 에이전트(Claude/Codex)가 수행.
- KO·EN 모두 1급: 자막/STT/OCR 모두 한·영 지원. 영어 강의도 제대로.
- CPU 우선(GPU 불요), 결정론 코어. dedup은 경량 이미지 기법(perceptual hash), CNN 슬라이드 분류기 같은 \ubฌ거운 모델 지양.
- 사용자-facing prose 한국어(README), 그 외 docs/skill/packaging 영어. code/paths/commands 영어. package management uv/uvx. work-unit 단위 commit.
- dedup/OCR는 검증된 기법 차용으로 parity 확보(신기술 발명 아님). 차별화는 게이트+시각캡처+verbatim+KO/EN.

## Non-Goals
- 텍스트 기반 dedup(OCR 개선 이후 future), CNN 슬라이드 분류기, VLM OCR(도입 보류), 수치 CER 게이트, 제품명 변경, 웹UI/MCP, 화자분리/번역/GPU/병렬, 외부 LLM 요약.

## Acceptance Criteria
- [ ] 폴더명이 영상 제목 slug(자막 전용 경로 포함). title 부재 시만 video_id 폴백.
- [ ] coverage.duration_sec가 실제 길이, summary/outline 섹션 타임스탬프가 실제 값(전부 0 아니어야 함).
- [ ] summary.md=요약(스켈레톤+매 실행 자동 보강), outline.md=목차/타임스탬프/슬라이드/전사불릿, transcript.md=verbatim. 게이트는 앵커만 검증.
- [ ] perceptual-hash + temporal dedup으로 발표자 움직임 중복이 대폭 감소(동일 슬라이드 중복 제거). 합성 프레임 단위테스트.
- [ ] OCR: 전처리(ROI 크롭+업스케일+이진화)+PaddleOCR 2.x 핀(ko/en); 실영상 before/after 육안으로 명확히 개선(사람이 읽을 수 있음). 전처리 순수함수 단위테스트. 수치 CER 게이트 없음.
- [ ] 중복제거 후 최종 슬라이드 이미지만 유지, 원본 프레임 삭제; --keep-frames로 보존 가능.
- [ ] 오프라인 단위테스트 전부 통과 + 실영상 1회 before/after 비교 기록.
- [ ] 완전성 게이트 2계층 계약 유지(구조 변경 없음).
- [ ] 언어 규약 유지, work-unit commit.

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|---|---|---|
| OCR 엔진이 문제 | 깨짐의 주원인은 occlusion+전처리 부재 | PaddleOCR 유지, 전처리 먼저 + 2.x 핀 + bake-off |
| 시각 dedup이 차별화 | 경쟁·연구가 더 정교 | dedup은 parity용, 차별화는 게이트+시각캡처+verbatim+KO/EN |
| 완전성 보증이 셀링포인트인가 | 경쟁 불만(놀침·fluff·신뢰·오디오만)이 그것 | 검증됨 — USP로 확정 |
| 한국어 우선 | 영어 강의·영어권 사용자도 가정 | KO/EN 둘 다 1급 |
| dedup이 텍스트 필요 | OCR 지금 나빠 | 이미지 perceptual-hash로 먼저(경험: dup<=10 vs distinct>=17), 텍스트 dedup은 future |

## Technical Context
- 근본 원인: 자막 경로에서 title/duration 미취득 → 폴더=video_id, duration=0 → TOC 0초. visual.dedupe_frames(hist+SSIM)가 발표자 움직임에 과분할. summary는 baseline만(보강 미실행). frames/ 원본 734장 잔존.
- 경험 증거: avg-hash(256) within-dup 1-10 vs distinct 17-53(top-60% crop 0-6 vs 14-51) → 임계 ~12로 분리.
- 경쟁: lecture2notes(60★, AGPL, CNN+요약모델, 연구용, 게이트 없음), vid2slides/tvdaal(발표자 프레임 필터·ROI·OCR텍스트·temporal), 상용 요약기(오디오 자막만, OCR/완전성 없음).
- yt-dlp는 visual 경로에서 이미 영상 다운로드로 title/duration 확보 가능; 자막 전용 시 --skip-download 메타데이터.

## Ontology (Key Entities)
| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| Completeness Gate | USP | no-omission, verifiable | core selling point |
| Visual capture | USP | slides/OCR, beyond audio-only | differentiator |
| Bilingual KO/EN | requirement | both first-class | OCR+STT+captions |
| Slide dedup | pipeline | perceptual hash + temporal | image-based, text later |
| summary.md | output | real summary, skeleton->auto enrich | host agent fills |
| outline.md | output | TOC+timestamps+slides+transcript bullets | split from summary |
| OCR | pipeline | preprocess+PaddleOCR 2.x, ko/en | slide image primary |

## Ontology Convergence
| Round | Entities | Stability |
|-------|----------|-----------|
| 1 | 3 | N/A |
| 2 | 3 | - |
| 3 | 5 | 60% |
| 4 | 3 | 80% |
| 5 | 3 | 70% |
| 6 | 1 | 80% |
| 7 | 1 | 85% |

## Interview Transcript
<details>
<summary>Full Q&A (8 rounds)</summary>

### Round 1 (summary/goal)
**A:** D 하이브리드 — 결정론 스켈레톤 + 호스트 에이전트 산문 보강(토큰0). | 38%

### Round 2 (dedup/goal)
**A:** 이미지 perceptual-hash(임계~12)+temporal; 경험 측정으로 분리 확인; 텍스트 dedup은 OCR 개선 후. | 31%

### Round 3 (moat/USP)
**A:** USP=검증 가능한 완전성+시각캡처+verbatim, KO/EN 1급. 플러그인/경량은 셀링포인트에서 제외. | 28%

### Round 4 (ocr/criteria, contrarian)
**A:** 전처리 먼저(ROI·업스케일·이진화)+PaddleOCR 2.x 핀 → bake-off; 목표=검색가능·충실, 이미지 1차. | 22%

### Round 5 (summary/criteria)
**A:** summary.md=진짜 요약(자동 보강), outline.md 분리, transcript.md verbatim; 게이트 앵커만. | 18%

### Round 6 (frames/constraints, simplifier)
**A:** 슬라이드 이미지만 남기고 원본 삭제, --keep-frames. | 12.5%

### Round 7 (verification/criteria)
**A:** 계층 검증: 오프라인 단위 + 실영상 1회 before/after. | 9%

### Round 8 (ocr acceptance/criteria)
**A:** 정성 기준(사람이 읽을 수 있고 baseline보다 명확히 개선)+전처리 단위테스트, CER 게이트 없음. | 4.7%

</details>
