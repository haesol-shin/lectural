# Deep Interview Spec: LecturAL — YouTube 강의 완전 정리 SKILL

## Metadata
- Interview ID: li-2026-0613
- Rounds: 8
- Final Ambiguity Score: 4.8%
- Type: greenfield
- Generated: 2026-06-13
- Threshold: 0.05
- Threshold Source: default
- Initial Context Summarized: no
- Status: PASSED
- Auto-Researched Rounds: []
- Auto-Answered Rounds: []
- Architect Failures: 0

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.95 | 0.40 | 0.380 |
| Constraint Clarity | 0.95 | 0.30 | 0.285 |
| Success Criteria | 0.95 | 0.30 | 0.285 |
| Context Clarity | N/A (greenfield) | - | - |
| **Total Clarity** | | | **0.950** |
| **Ambiguity** | | | **0.050** |

## Topology
| Component | Status | Description | Coverage / Deferral Note |
|-----------|--------|-------------|--------------------------|
| 입력·수집 (acquisition) | active | YouTube URL → 자막/오디오/영상 확보 (yt-dlp). 단일 + 순차 배치(다중 URL). | AC-1, AC-2 |
| 음성 트랙 (speech-track) | active | 자막 우선, 없거나 부실하면 faster-whisper(medium int8, CPU) STT. ko/en 자동. | AC-3, AC-4, AC-9 |
| 시각 트랙 (visual-track) | active | ffmpeg 키프레임/장면전환 추출 → 중복 제거 → OCR로 슬라이드/화면 텍스트. | AC-5, AC-6 |
| 합성·정리 (synthesis) | active | 두 트랙 시간축 정렬·병합 → raw 전사본 + 구조화 요약본. 요약은 호스트 에이전트가 직접. | AC-7, AC-8, AC-12 |
| 배포·사용성 (distribution-ux) | active | v1 = 개발자용 Claude Code/Codex 스킬. 핵심은 재사용 CLI/모듈로 분리. | AC-10, AC-11 |
| 완전성 강제 (completeness) | active | 커버리지 게이트 훅: 대사 공백 + 장면 커버리지 + 산출물 존재. | AC-12, AC-13 |

## Goal
YouTube 강의 영상 URL을 입력받아, 그 영상의 **모든 발화·모든 화면 텍스트·모든 장면(슬라이드)** 을 빠짐없이 캡처해 **완전 전사본(raw)** 과 **구조화 요약본** 두 가지 markdown 산출물로 정리하는, Claude Code/Codex에서 호출 가능한 SKILL을 만든다. v1은 개발자(본인) 전용 스킬로 빠르게 프로토타이핑하되, 핵심 파이프라인은 재사용 가능한 CLI/파이썬 모듈로 분리해 추후 비개발자용 독립 프로그램으로 감쌀 수 있게 설계한다. 시험 기간 사용 맥락상 "이 강의를 다 정리했다"는 확신을 줄 수 있어야 하며, 완전성은 자동 검증 훅으로 강제한다.

## Constraints
- **CPU 우선, GPU 최소화**: 타깃은 대학생 노트북. faster-whisper는 CTranslate2 int8(CPU)로 구동, GPU 의존 금지.
- **언어**: 한국어·영어 자동 처리. 자막 있으면 사용, 없거나 부실하면 STT.
- **토큰 최소화 (핵심 제약)**:
  - raw 전사본·OCR은 **비-LLM 결정론적** 파이프라인(STT+OCR+dedup)으로 생성, LLM 토큰 0.
  - 구조화 요약만 **호스트 에이전트(Claude/Codex)** 가 직접 생성 → 외부 API 토큰 0.
  - 에이전트 컨텍스트에는 **압축·중복제거된 텍스트만** 투입(이미지 원본 미투입), 프레임 dedup으로 시각 입력 최소화.
  - 독립 실행 시 로컬 LLM(Ollama) 폴백은 **defer**.
- **STT 기본값**: medium(int8). 영상이 과도하게 길면 경고 후 사용자 선택, 모델 크기 오버라이드 가능.
- **배치**: v1은 다중 URL **순차** 처리. 병렬은 defer(단일 처리가 빠르면 순차로 충분).
- **플랫폼**: Windows 11, Intel Core Ultra 5. ffmpeg/yt-dlp 외부 바이너리 의존 명시.
- **빠른 프로토타이핑**: v1 범위를 MVP+순차배치로 고정, 그 외 전부 defer.

## Non-Goals (v1 제외)
- 병렬 배치 처리.
- 로컬 LLM(Ollama) 요약 폴백.
- 비개발자용 독립 프로그램/웹/데스크톱 UI (설계는 열어두되 구현 제외).
- GPU 가속 경로.
- OCR 실패율을 완료 게이트로 사용(텍스트 없는 프레임이 정상이므로 부적합).
- 화자 분리(diarization), 자동 번역, 퀴즈/문제 생성.

## Acceptance Criteria
- [ ] AC-1: 유효한 YouTube URL 1개를 받아 전체 파이프라인이 끝까지 실행되고 산출물 폴더가 생성된다.
- [ ] AC-2: 다중 URL을 받으면 순차로 각각 처리하고 URL별 폴더를 만든다.
- [ ] AC-3: 자막(수동/자동)이 있으면 받아서 사용하고, 없으면 자동으로 STT 경로로 폴백한다.
- [ ] AC-4: STT는 faster-whisper medium(int8) CPU로 동작하며, 타임스탬프 포함 전사본을 만든다.
- [ ] AC-5: ffmpeg I-frame/scene 추출 후 히스토그램/SSIM 기반 중복 제거로 슬라이드 후보 프레임을 추린다.
- [ ] AC-6: 추려진 슬라이드 프레임에 OCR(한/영)을 적용해 화면 텍스트를 추출한다.
- [ ] AC-7: `transcript.md`(raw, 타임스탬프 포함)와 `summary.md`(구조화 요약) 두 파일이 생성된다.
- [ ] AC-8: `summary.md` 상단에 목차 + 커버리지 요약이 있고, 각 섹션이 해당 타임스탬프·슬라이드로 링크된다.
- [ ] AC-9: 전사본은 영상 전체 구간을 덮으며, 임계값(예: 60초) 이상 무음이 아닌 미전사 공백 구간이 없다.
- [ ] AC-10: SKILL.md + scripts + references 구조로 Claude Code/Codex에서 호출 가능하다.
- [ ] AC-11: 핵심 파이프라인이 스킬과 분리된 CLI/모듈로 단독 실행 가능하다.
- [ ] AC-12: 산출물은 `./output/<video-title>/` 아래 `transcript.md` + `summary.md` + `frames/` + `coverage.json` 로 떨어진다.
- [ ] AC-13: 완료 게이트 훅이 (a) 대사 공백 검사, (b) 장면 커버리지(전 구간 키프레임 + 슬라이드 프레임 OCR 텍스트 존재), (c) 두 산출물 존재·비어있지 않음을 검증하며, 하나라도 실패하면 "완료" 선언을 차단한다.

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| "스킬"이면 누구나 쓸 수 있다 | 비개발자는 Claude Code/Codex가 없다 | v1은 개발자 전용 스킬, 핵심은 재사용 모듈로 분리해 비개발자 UI는 defer |
| 영상을 LLM에 넣어 처리한다 | 토큰 폭발 + 비용 | 비-LLM(STT+OCR+dedup)로 raw 생성, 요약만 호스트 에이전트가 → 외부 API 토큰 0 |
| 별도 요약 LLM이 필요하다 (contrarian) | 스킬은 이미 LLM(호스트 에이전트) 위에서 돈다 | 호스트 에이전트가 직접 요약, 로컬 LLM은 폴백으로 defer |
| 정확하려면 큰 STT 모델 필요 | CPU 노트북에서 large-v3는 느림 | medium(int8) 기본 + 길면 경고/선택 + 오버라이드 |
| OCR 실패율로 완전성 검증 | 텍스트 없는 프레임이 정상적으로 많음 | 게이트를 "슬라이드 프레임엔 텍스트 존재 + 대사 공백 없음 + 산출물 존재"로 좁힘 |
| 6개 다 만들어야 한다 (simplifier) | 빠른 프로토타입과 충돌 | v1 = MVP + 순차 배치, 나머지 defer |

## Technical Context
**검증된 기술 스택 (2025–2026 최신 조사 기반):**

- **수집**: `yt-dlp`(자막 `--write-subs`/`--write-auto-subs --skip-download`, 영상/오디오 추출) + `youtube-transcript-api`(자막 text-only 폴백). YouTube 포맷 변경으로 분기당 1회 깨질 수 있으니 버전 핀 + 출력 모니터링.
- **STT**: `faster-whisper`(CTranslate2 int8) — CPU에서 whisper 대비 4–8배, ko/en 99개 언어. medium 기본. (영어 전용 최고 정확도 대안: NVIDIA Canary-Qwen / IBM Granite Speech, 그러나 GPU 의존·다국어 약함 → v1 미채택.)
- **시각**: `ffmpeg`로 I-frame(`select=eq(pict_type,I)`) + scene change 추출, 2fps 다운샘플. 히스토그램/SSIM 비교로 중복 제거(1000장 → 슬라이드 ~30장 수준). 슬라이드/장면 분류.
- **OCR**: `PaddleOCR`(PP-OCRv5, 한/영·복잡 레이아웃 강함) 1차 권장. `Tesseract`는 깨끗한 인쇄체 폴백. 고난도 레이아웃은 호스트 비전 능력(에이전트)으로 보강 가능(토큰 주의).
- **합성**: 트랙 시간축 정렬 후 호스트 에이전트가 요약. 토큰 절감 이론 근거: STORM/FlashVID(토큰 병합·선택), MDP3(list-wise 프레임 선택) — "프레임 늘려도 한계효용 체감", 핵심 프레임만 선택.
- **패키징/강제**: SKILL.md(YAML frontmatter + body 1,500–2,000단어, 상세는 `references/`) + `scripts/`(파이썬 CLI) + hooks. 완료 강제는 Stop/PostToolUse 훅이 stdin JSON 읽고 exit code 2로 차단(또는 settings.json 훅).

**아키텍처 원칙**: 핵심 파이프라인 = 결정론적 파이썬 CLI 모듈(스킬과 독립 실행 가능). 스킬은 얇은 래퍼 + 합성 프롬프트 + 완료 게이트.

## Ontology (Key Entities)
| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| LectureVideo | core domain | url, duration, language | has Transcript, has Frames |
| Transcript | core domain | segments, timestamps, source(caption\|stt) | belongs to LectureVideo |
| Frame | core domain | timestamp, image, ocrText, isSlide | belongs to LectureVideo |
| RawTranscriptDoc | core domain | fullText, timestamps | output of synthesis |
| StructuredSummary | core domain | sections, links to raw/slides, coverageSummary | output of synthesis |
| BatchJob | supporting | urls, mode(sequential) | drives multiple LectureVideo |
| CoverageCheck | supporting | gapCheck, sceneCoverage, artifactExists | validates outputs |
| CorePipeline | supporting | cli, modules | produces outputs |
| Synthesizer | supporting | mode(host-agent\|local-llm) | generates StructuredSummary |
| Skill | supporting | SKILL.md, scripts, hooks | wraps CorePipeline |

## Ontology Convergence
| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 1 | 7 | 7 | - | - | N/A |
| 2 | 8 | 0 | 1 (StudyNote→Raw+Summary) | 6 | 85% |
| 3 | 9 | 1 (BatchJob) | 0 | 8 | 90% |
| 4 | 10 | 1 (Synthesizer) | 0 | 9 | 92% |
| 5 | 10 | 0 | 1 (CoverageCheck 필드) | 10 | 100% |
| 6 | 10 | 0 | 0 | 10 | 100% |
| 7 | 10 | 0 | 0 | 10 | 100% |
| 8 | 10 | 0 | 0 | 10 | 100% |

## Interview Transcript
<details>
<summary>Full Q&A (8 rounds)</summary>

### Round 0 — Topology
**Q:** 6개 최상위 구성요소가 맞나?
**A:** 1~4 맞음. 5번(패키징)은 "배포·사용성"으로 재구성 — 비개발자 사용성 + 빠른 프로토타이핑이 쟁점.

### Round 1 — 배포·사용성 / Goal
**Q:** v1 사용자/전달 형태?
**A:** v1=개발자 전용 Claude Code/Codex 스킬, 빠른 프로토타입. 핵심은 재사용 모듈로, 비개발자 독립프로그램 가능성 열어둠. **Ambiguity 51.5%**

### Round 2 — 완전성 / Criteria
**Q:** "다 정리했다"는 산출물 정의?
**A:** C: raw 완전 전사본 + 구조화 요약본 둘 다. 완전성=전 구간 커버. **Ambiguity 36.5%**

### Round 3 — Constraints
**Q:** 언어/자막?
**A:** ko·en 자동(자막 우선, 없으면 STT). + GPU 최소화·CPU 우선, 순차 배치 희망. **Ambiguity 27.3%**

### Round 4 — 합성 / Constraints (Contrarian)
**Q:** 요약 LLM은 누가?
**A:** A+B: 호스트 에이전트 직접(토큰 0), 로컬 LLM은 폴백 defer. raw는 결정론적. **Ambiguity 21%**

### Round 5 — 완전성 / Criteria
**Q:** 완료 차단 게이트 조건?
**A:** #2 대사 공백 없음 + #3 장면 커버리지 + #5 산출물 존재. OCR 실패율 제외. **Ambiguity 14.4%**

### Round 6 — Constraints (Simplifier)
**Q:** v1 MVP 범위?
**A:** MVP + 순차 배치(다중 URL). 나머지 defer. **Ambiguity 10.6%**

### Round 7 — 음성 / Constraints
**Q:** STT 속도/정확도 기본값?
**A:** medium(int8) 기본, 길면 경고+선택, 오버라이드 가능. **Ambiguity 7.7%**

### Round 8 — 합성 / Criteria
**Q:** 산출물 위치/포맷?
**A:** 폴더 구조 + summary.md 상단 목차/커버리지 + 섹션별 타임스탬프·슬라이드 링크. **Ambiguity 4.8%**

</details>
