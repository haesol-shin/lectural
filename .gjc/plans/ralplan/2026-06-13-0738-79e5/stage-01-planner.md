# LecturAL 구현 계획 (Planner / RALPLAN-DR)

> 출처: `.gjc/specs/deep-interview-lectural.md` (li-2026-0613, Ambiguity 4.8%, PASSED). 모든 태스크는 AC-1..AC-13에 매핑된다. 산문은 한국어, 식별자/경로/명령/JSON 키는 영어.

## 1. RALPLAN-DR 요약

### Principles
- **P1 결정론 우선, LLM 토큰 0**: raw 전사본·OCR·dedup·coverage는 전부 비-LLM 파이프라인으로 생성한다. LLM은 호스트 에이전트의 요약 1회에만 개입한다. (AC-7, AC-9, 토큰 최소화 제약)
- **P2 파이프라인/스킬 분리**: 핵심 로직은 `lectural` 파이썬 패키지(CLI 단독 실행 가능), 스킬은 얇은 래퍼. (AC-10, AC-11)
- **P3 CPU 우선·외부 바이너리 명시**: faster-whisper int8 CPU, ffmpeg/yt-dlp는 시작 시 탐지하고 없으면 명확히 실패. (CPU 제약)
- **P4 완전성은 자동 게이트로 강제**: 산출물 신뢰는 사람이 아니라 coverage.json + hook이 보증. (AC-13)
- **P5 캡션 우선·압축 입력**: 자막이 있으면 STT를 건너뛰고, 프레임 dedup·압축 텍스트만 에이전트에 투입한다. (AC-3, 토큰 최소화)

### Decision Drivers (top 3)
1. **토큰/비용 최소화**: 외부 API 토큰 0, 에이전트 컨텍스트 입력 최소화가 설계 전반을 지배한다.
2. **CPU 노트북에서의 실행 가능성**: GPU 없는 Intel Core Ultra 5에서 합리적 시간 내 완주.
3. **완전성 보증(완료 차단 게이트)**: 시험기간 "다 정리했다" 확신 = 자동 검증이 핵심 가치.

### Viable Options (아키텍처)
**Option A — 결정론적 파이썬 코어 + 호스트 에이전트 요약 + Python 완료 훅 (채택)**
- 코어: `lectural` 패키지가 acquisition→speech→visual→ocr→coverage까지 결정론적으로 실행, `synthesis_input.json`(압축 합성 입력)을 산출. 호스트 에이전트가 그것을 읽어 `summary.md` 작성. Python hook이 coverage.json을 읽어 exit 2로 차단.
- Pros: 토큰 0(요약만 호스트), 코어 단독 테스트 용이, Windows에서 `python` 훅으로 셸 비의존, 스펙 기술스택과 정합.
- Cons: 요약 품질이 호스트 에이전트에 의존, 합성 입력 스키마를 안정적으로 설계해야 함.

**Option B — 코어가 로컬 LLM(Ollama)로 요약까지 완결**
- Pros: 스킬 외부에서도 요약 완결, 호스트 의존 없음.
- Cons: 로컬 LLM 설치/모델 무게, CPU 추론 느림, 스펙이 명시적으로 **defer**. → v1 무효.

**Option C — 영상을 멀티모달 LLM에 직접 투입해 전사+요약 일괄**
- Pros: 파이프라인 단순.
- Cons: 토큰 폭발(핵심 제약 정면 위반), 긴 강의 비현실적, 결정론적 완전성 보증 불가. → 무효.

### Invalidation Rationale
Option B/C는 "외부/대량 토큰 0" + "defer된 로컬 LLM" 제약과 충돌하여 v1에서 무효. **Option A 채택.**

---

## 2. 제안 리포지토리 레이아웃

```
LecturAL/
  pyproject.toml              # 패키지 메타+의존(빌드시스템) — AC-11
  requirements.txt            # 핀 고정 의존(yt-dlp 등) — AC-11, 리스크 완화
  README.md                   # 사용법/바이너리 사전조건
  lectural/                   # 재사용 코어 패키지 — AC-11
    __init__.py
    cli.py                    # argparse 엔트리(단일/순차배치) — AC-1, AC-2, AC-11
    config.py                 # 모델크기/임계값/경로 상수, override — AC-4
    binaries.py               # ffmpeg/yt-dlp 탐지·버전체크 — 제약(바이너리)
    acquisition.py            # yt-dlp 캡션우선 + audio 폴백 + 메타 — AC-1,AC-2,AC-3
    speech.py                 # faster-whisper medium int8 CPU STT — AC-3,AC-4,AC-9
    visual.py                 # ffmpeg I-frame/scene 추출 + dedup — AC-5
    ocr.py                    # PaddleOCR 1차 / Tesseract 폴백 — AC-6
    synthesis.py              # 트랙 정렬→transcript.md + synthesis_input.json — AC-7,AC-9
    coverage.py               # coverage.json 생성 + 게이트 로직 — AC-12,AC-13
    models.py                 # dataclass: Segment, Frame, CoverageReport 등
    utils.py                  # 타임스탬프 포맷, slug(video-title), io
  scripts/
    run_lectural.py           # 스킬이 호출하는 thin runner(cli 위임) — AC-10
    completeness_hook.py      # Stop/PostToolUse 훅(파이썬, exit 2) — AC-13
  .claude/
    skills/lectural/
      SKILL.md                # YAML frontmatter + body(<=2000단어) — AC-10
    settings.json             # 훅 wiring(권장 경로) — AC-13
  references/                 # 상세 문서(스킬 본문에서 분리) — AC-10
    pipeline.md               # 단계별 내부 동작
    synthesis_contract.md     # synthesis_input.json 스키마 + 요약 작성 규칙
    troubleshooting.md        # yt-dlp 깨짐/STT 길이/OCR 설치
  tests/
    test_dedup.py             # 히스토그램/SSIM dedup 단위 — AC-5
    test_coverage.py          # gap/scene/artifact 게이트 단위 — AC-9,AC-13
    test_synthesis_input.py   # 스키마/정렬 단위 — AC-7
    fixtures/                 # 합성 세그먼트/프레임 메타 픽스처
  output/                     # 런타임 산출물(.gitignore) — AC-12
    <video-title>/
      transcript.md
      summary.md
      coverage.json
      synthesis_input.json
      frames/*.png
```
AC 정당화 요지: `lectural/`(AC-11 단독 실행), `cli.py`(AC-1/2), 모듈별 트랙(AC-3~6), `synthesis.py`(AC-7), `coverage.py`+`completeness_hook.py`(AC-13), `.claude/skills/...`+`settings.json`(AC-10/13), `references/`(AC-10 본문 분리), `output/`(AC-12).

---

## 3. 단계별 태스크 (Phase 1..10)

**Phase 1 — Scaffold + 의존 + 바이너리 탐지** (AC-11, AC-1)
- T1.1 pyproject/requirements 작성, yt-dlp/faster-whisper/paddleocr/pytesseract/youtube-transcript-api/Pillow/opencv 핀. (AC-11)
- T1.2 `binaries.py`: `ffmpeg -version`/`yt-dlp --version` 탐지, 없으면 설치 안내 포함 명확 에러. (제약)
- T1.3 `config.py`/`models.py`/`utils.py`(slug, ts) 기본 골격. (AC-12)
- T1.4 `cli.py` argparse: `urls+`, `--model`, `--max-duration-warn`, `--output-dir`. (AC-1,AC-2,AC-4)

**Phase 2 — Acquisition (캡션 우선 + 오디오 폴백)** (AC-1,AC-2,AC-3)
- T2.1 메타 취득(title/duration/lang) + `output/<slug>/` 생성. (AC-1,AC-12)
- T2.2 yt-dlp `--write-subs --write-auto-subs --skip-download`(json3/vtt) 캡션 시도 → 파싱. (AC-3)
- T2.3 `youtube-transcript-api` 텍스트 폴백. (AC-3)
- T2.4 캡션 부재/부실 판정 시에만 오디오 다운로드. (AC-3)
- T2.5 다중 URL 순차 루프 + URL별 폴더/에러 격리. (AC-2)

**Phase 3 — Speech (faster-whisper CPU int8)** (AC-3,AC-4,AC-9)
- T3.1 medium int8 CPU 로드, ko/en 자동 감지. (AC-4)
- T3.2 타임스탬프 세그먼트 STT → `Segment[]`. (AC-4)
- T3.3 긴 영상 경고 + `--model` 오버라이드. (AC-4)
- T3.4 출력 정규화로 caption/STT 동일 `Segment` 형태 통합. (AC-3,AC-9)

**Phase 4 — Visual (키프레임 + dedup)** (AC-5)
- T4.1 ffmpeg I-frame+scene(2fps 다운샘플) 추출. (AC-5)
- T4.2 히스토그램/SSIM dedup → 슬라이드 후보. (AC-5)
- T4.3 슬라이드/장면 분류 + `frames/` 저장 + `Frame` 메타. (AC-5,AC-12)

**Phase 5 — OCR (PaddleOCR / Tesseract)** (AC-6)
- T5.1 PaddleOCR PP-OCRv5 ko/en 1차. (AC-6)
- T5.2 Tesseract 폴백(설치/언어팩 부재 시 graceful). (AC-6)
- T5.3 OCR 텍스트를 `Frame.ocrText`에 결합, 빈텍스트 허용(비슬라이드 정상). (AC-6,AC-13)

**Phase 6 — Synthesis 계약 (결정론적 raw + 합성 입력)** (AC-7,AC-9,AC-12)
- T6.1 두 트랙 시간축 정렬·병합. (AC-7)
- T6.2 `transcript.md`(raw, 타임스탬프) 결정론 생성. (AC-7,AC-9)
- T6.3 `synthesis_input.json`(압축 합성 입력) 생성 — 4절 스키마. (토큰 최소화)

**Phase 7 — Coverage 체커** (AC-9,AC-12,AC-13)
- T7.1 dialogue gap 분석(>60s 비무음 미전사 공백 탐지). (AC-9)
- T7.2 scene coverage(전 구간 키프레임 분포 + 슬라이드 프레임 OCR 존재). (AC-13)
- T7.3 artifact 존재·비어있음 검사 → `coverage.json` 작성. (AC-12,AC-13)

**Phase 8 — SKILL.md 패키징** (AC-10)
- T8.1 SKILL.md frontmatter(name/description/트리거) + body(<=2000단어): 코어 호출법 + 요약 작성 규칙 + 게이트 설명. (AC-10)
- T8.2 `references/synthesis_contract.md`로 상세 분리, 호스트가 `synthesis_input.json`→`summary.md`(목차+커버리지 헤더+타임스탬프/슬라이드 링크) 작성 지시. (AC-8,AC-10)

**Phase 9 — 완료 훅** (AC-13)
- T9.1 `scripts/completeness_hook.py`: stdin JSON 읽기, coverage.json 로드, 3검사, 실패 시 exit 2 + 차단 사유. (AC-13)
- T9.2 wiring: `settings.json` 훅(권장) — Windows에서 `python scripts/completeness_hook.py`로 셸 비의존. SKILL.md frontmatter는 보조 문서로만. (AC-13)

**Phase 10 — 검증** (AC-1..AC-13)
- T10.1 단위 테스트(dedup/coverage/synthesis_input).
- T10.2 캡션 보유 짧은 공개강의 1건 E2E.
- T10.3 캡션 없는 영상으로 STT 경로 강제 E2E.
- T10.4 순차 배치 2건 + 훅 차단/통과 확인.

---

## 4. Synthesis 핸드오프 계약

결정론 파이프라인이 호스트 에이전트에게 넘기는 유일 입력은 `synthesis_input.json`이며 **이미지 원본·전체 raw를 넣지 않는다**(토큰 최소화). 호스트는 이 JSON만으로 `summary.md`를 작성한다.

```json
{
  "video": { "title": "string", "url": "string", "duration_sec": 0, "language": "ko|en", "transcript_source": "caption|stt" },
  "outline": [ { "t": 0.0, "label": "string(섹션 힌트)" } ],
  "segments": [ { "t": 0.0, "end": 0.0, "text": "compact speech text" } ],
  "slides": [ { "t": 0.0, "frame": "frames/0001.png", "ocr": "deduped slide text" } ],
  "coverage": { "transcript_covered_ratio": 1.0, "max_gap_sec": 0, "slide_count": 0, "slides_with_text": 0 },
  "links": { "transcript_md": "transcript.md", "frames_dir": "frames/" }
}
```

**토큰 최소화 달성 방식**:
- caption-first: 자막 있으면 STT 생략, segments는 자막 그대로 압축.
- frame dedup: 1000장→~30장 슬라이드만 `slides[]`에 포함, 이미지 경로만 전달(픽셀 미투입).
- compact text only: segments는 짧은 청크로 병합, slides.ocr은 dedup된 텍스트만. 전체 raw는 `transcript.md` 파일로 두고 JSON에는 링크만.
- 호스트는 segments/slides/outline 기반으로 섹션 작성 + 각 섹션을 `transcript.md` 앵커 및 `frames/NNNN.png`로 링크, 상단에 TOC + coverage 헤더 삽입(AC-8).

---

## 5. 완료 훅 설계

- **읽는 것**: 훅은 stdin으로 받은 hook JSON에서 작업 디렉터리를 식별하고 `output/<slug>/coverage.json`을 로드한다. (호스트 대화는 신뢰하지 않고 산출물만 본다.)
- **3 검사 + 임계값**:
  1. dialogue gap: `max_gap_sec <= 60` AND `transcript_covered_ratio >= 0.98` (무음 제외 미전사 공백 없음). (AC-9)
  2. scene coverage: 전 구간을 N 구간으로 나눠 각 구간에 키프레임 1+ 존재(빈 구간 0) AND `slides_with_text >= 1`. (AC-13)
  3. artifact 존재: `transcript.md`·`summary.md` 둘 다 존재 + 비어있지 않음(min bytes). (AC-7,AC-12)
- **차단 동작**: 하나라도 실패 시 stderr에 실패 항목/사유 출력 후 **exit code 2** → 호스트의 "완료" 차단. 통과 시 exit 0.
- **Wiring(권장)**: `.claude/settings.json`의 Stop/PostToolUse 훅으로 `python scripts/completeness_hook.py` 호출. **Windows 셸 우려** 때문에 bash 스크립트 대신 `python`으로 직접 실행(크로스플랫폼). SKILL.md frontmatter 훅은 보조/문서 용도로만 명시하고 실제 강제는 settings.json에 둔다.

---

## 6. 단계별 검증

- Phase 1: `python -m lectural.cli --help` 동작, ffmpeg/yt-dlp 미존재 시 명확 에러(바이너리 임시 PATH 제거로 확인). (AC-11)
- Phase 2: 캡션 보유 URL→json3/vtt 파싱 성공, 캡션 없는 URL→오디오 다운로드 트리거. (AC-3) — **실영상 스모크 필요**.
- Phase 3: STT 경로에서 `Segment[]` 타임스탬프 단조 증가·전 구간 덮음. (AC-4,AC-9) — 스모크.
- Phase 4: `test_dedup.py`로 합성 프레임열의 dedup 비율/경계 **단위 결정론 검증**. (AC-5)
- Phase 5: 텍스트 슬라이드 픽스처에서 OCR 비공백, 빈 프레임 graceful. (AC-6) — 일부 스모크.
- Phase 6: `test_synthesis_input.py`로 정렬·스키마·링크 **단위 검증**. (AC-7)
- Phase 7: `test_coverage.py`로 gap/scene/artifact 게이트 경계값 **단위 검증**. (AC-9,AC-13)
- Phase 8/9: 훅에 통과/실패 coverage.json 주입해 exit 0 / exit 2 확인(파이썬 직접 호출). (AC-13)
- Phase 10: 캡션 1건 + 무자막 1건 + 배치 2건 E2E 스모크로 AC-1,2,3,7,8,12 종단 확인.
- **단위 결정론 vs 실영상 스모크 구분**: dedup/coverage/synthesis_input/hook = 단위 결정론. acquisition/speech/ocr 정확도 = 실영상 스모크(공개 짧은 강의).

---

## 7. 리스크 + 완화

- **yt-dlp 깨짐**: requirements 버전 핀 + `references/troubleshooting.md`에 업그레이드 절차, acquisition 실패 시 youtube-transcript-api 폴백 + 명확 에러. 분기당 1회 점검.
- **CPU STT 지연(긴 영상)**: medium int8 기본, `--max-duration-warn` 경고 + `--model` 다운그레이드(base/small) 오버라이드, 진행 로그.
- **PaddleOCR Windows 설치 무게**: PaddleOCR 임포트 실패 시 Tesseract 폴백 자동 전환, README에 설치/대안 명시, OCR 선택적 의존.
- **frame-dedup 튜닝**: 임계값 `config.py` 상수화 + `test_dedup.py` 회귀, 과/소 dedup 시 SSIM/히스토그램 가중 조정 포인트 문서화.
- **한국어 OCR 정확도**: PP-OCRv5 ko 우선, 저신뢰 프레임은 호스트 비전 보강(토큰 주의, 선택적), 게이트는 OCR 실패율 미사용(빈 프레임 정상).

---

## 8. 비목표 / Deferred (재확인)
- 병렬 배치(순차만), 로컬 LLM(Ollama) 요약 폴백, 비개발자 UI/웹/데스크톱, GPU 가속 경로, 화자 분리·자동 번역·퀴즈 생성, OCR 실패율을 완료 게이트로 사용. 모두 v1 제외(설계는 모듈 분리로 확장 여지만 유지).

---

## 9. Handoff
- **Architect**: synthesis_input.json 스키마 안정성, 훅 wiring(settings.json vs SKILL frontmatter), 모듈 경계(visual/ocr 결합도) 검토.
- **Critic**: coverage 임계값(0.98/60s/구간분할 N)·E2E 스모크 충분성 검증.
- **executor**: Phase 1→10 순차 구현, 단위 테스트 동반.
- **ultragoal/team**: 다회차 구현이면 Phase 단위 goal 분할 권장.
