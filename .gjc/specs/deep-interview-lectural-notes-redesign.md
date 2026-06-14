# Deep Interview Spec: LecturAL Notes 재설계 + 배포·설치 (notes.md 단일 산출물 · 인용 딥링크 · 보강 강제 · doctor 자동설치)

## Metadata
- Interview ID: di-notes-redesign
- Rounds: 7 (+ Round 0 topology)
- Final Ambiguity Score: 4.5%
- Type: brownfield
- Generated: 2026-06-14
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
| Goal Clarity | 0.96 | 0.35 | 0.336 |
| Constraint Clarity | 0.95 | 0.25 | 0.2375 |
| Success Criteria | 0.95 | 0.25 | 0.2375 |
| Context Clarity | 0.96 | 0.15 | 0.144 |
| **Total Clarity** | | | **0.955** |
| **Ambiguity** | | | **0.045** |

## Topology
| Component | Status | Description | Coverage / Deferral Note |
|-----------|--------|-------------|--------------------------|
| notes-output | active | notes.md 4섹션 불릿 문서 + 인용 딥링크, summary/outline 폐기 | AC-1..AC-6 |
| core-skeleton | active | LLM-0 골격+근거 생성, 기계식 산문 제거, transcript cue 앵커 | AC-7..AC-10 |
| prompt-enrich | active | summary_prompt.md 단일 소스 + 스킬 자동 보강 | AC-11..AC-14 |
| gate-update | active | coverage/completeness_hook을 notes.md 기준으로 갱신 | AC-15..AC-18 |
| verification | active | executor 루브릭 자동채점 + 실영상 before/after | AC-19..AC-21 |
| distribution-install | active | Claude 플러그인 + Codex AGENTS + uv/uvx 런타임 + lectural doctor + README | AC-22..AC-28 |

## Goal
LecturAL의 학습 산출물을 단일 파일 `notes.md`로 재설계하고, 에이전트 주도의 최소-상호작용 배포/설치 경로를 확립한다. `notes.md`는 `핵심 테이크어웨이 / 큰 흐름 / 개념 및 주요 이론 정리 / 세부 내용(슬라이드별)` 4섹션의 불릿 문서이며, 개념·세부 불릿은 모두 원본 근거(전사/영상)로 1클릭 이동하는 딥링크를 가진다. 결정론적 코어(LLM 0)는 기계식 산문 요약 대신 골격+근거만 생성하고, 산문은 단일 소스 프롬프트를 따르는 호스트 에이전트가 스킬 실행 시 보강한다. 설치는 Claude Code 플러그인 + Codex AGENTS.md + uv/uvx Python 런타임의 2부 구조이며, `lectural doctor`가 전체 컴포넌트 매니페스트를 검증·자동수리해 사용자 상호작용을 최소화한다. 2계층 완전성 게이트(CLI 1차, Stop 훅 추가·비래핑)는 notes.md 기준으로 갱신한다.

## Constraints
- 사용자용 prose는 한국어. 경로/명령/식별자/JSON 키/앵커 id는 영어.
- 토큰 0: 결정론적 코어는 외부 LLM API 미호출. 보강은 실행 중인 호스트 에이전트가 수행.
- 슬라이드 이미지 자체는 모델에 전송하지 않음(텍스트만, 입력=synthesis_input.json).
- 2계층 게이트 계약 유지: Layer1=CLI 종료코드(agent-neutral), Layer2=Stop 훅(Claude 전용, CLI 호출/래핑 금지).
- 산출물: notes.md(신설), transcript.md(verbatim+cue 앵커), synthesis_input.json(정리 입력), coverage.json, frames/. summary.md/outline.md 폐기.
- 딥링크 기본형 `transcript.md#t<HHMMSS>` + 괄호로 `https://youtu.be/<id>?t=<sec>` 병기.
- 프롬프트는 OpenAI/Anthropic 가이드 반영(역할, 근거자료 선배치, XML 섹션, 출력계약, few-shot, CoD, 그라운딩/'불명확', 인용 강제).
- 배포는 기존 자산(`.claude-plugin/`, `skills/lectural/`, `hooks/`, `AGENTS.md`) 확장. npm/bun 제품 배포 안 함.
- Python 런타임은 에이전트가 `uvx --from ".[run]" lectural`로 자동(별도 수동 install 불필요). ffmpeg/yt-dlp는 외부 바이너리.

## Non-Goals
- 외부 LLM API 호출.
- OCR CER 정량 게이트.
- 정리 산문의 정확문장 일치 테스트(구조/근거만 검사).
- 슬라이드 이미지 모델 전송.
- 플래시카드/퀴즈/예상문제(후속).
- 발화비례 분량 하드 수치 게이트(프롬프트 소프트 휴리스틱만).
- npm/bun 제품 배포, skills.sh `npx skills add` 크로스에이전트 배포(후속 옵션).
- ffmpeg 완전 0-설치 보장(시스템 바이너리, 베스트에포트).

## Acceptance Criteria
- [ ] AC-1: `notes.md` 신설, `summary.md`/`outline.md` 미생성.
- [ ] AC-2: notes.md 4섹션(`## 핵심 테이크어웨이`/`## 큰 흐름`/`## 개념 및 주요 이론 정리`/`## 세부 내용`).
- [ ] AC-3: 핵심 테이크어웨이 3~5줄 서술, 큰 흐름 서술 불릿(둘 다 인용 면제).
- [ ] AC-4: 개념 및 주요 이론 정리 불릿, 각 불릿 근거 딥링크 1개+.
- [ ] AC-5: 세부 내용 슬라이드별 `### [HH:MM:SS](딥링크) 제목` + `![](frames/...)` + 발화비례 불릿, 각 불릿 근거 딥링크.
- [ ] AC-6: 딥링크 = `transcript.md#t<HHMMSS>` + 괄호 `youtu.be/<id>?t=<sec>`.
- [ ] AC-7: 코어는 골격(헤딩+슬라이드 이미지/시간+verbatim 전사 불릿+`<!-- 미보강 -->`)만, 기계식 산문 미생성.
- [ ] AC-8: transcript.md 각 cue에 `<a id="t<HHMMSS>">` 앵커.
- [ ] AC-9: synthesis_input.json 정리 입력 유지(텍스트만).
- [ ] AC-10: 코어 import lazy 유지.
- [ ] AC-11: `skills/lectural/references/summary_prompt.md` 단일 소스(역할/근거선배치/XML/출력계약/few-shot/CoD/그라운딩·'불명확'/인용강제).
- [ ] AC-12: SKILL.md(루트·.claude parity)가 summary_prompt.md 참조 + 스킬 실행 시 자동 보강 지시.
- [ ] AC-13: 보강은 synthesis_input.json만 읽고 외부 LLM API 미호출.
- [ ] AC-14: 발화비례는 프롬프트 소프트 휴리스틱(하드 게이트 아님).
- [ ] AC-15: coverage.json 산출물 검사 notes.md 기준 갱신.
- [ ] AC-16: completeness_hook이 notes.md 4섹션 + 슬라이드마다 이미지+불릿 검사.
- [ ] AC-17: 인용 게이트(전수+유효성): 개념·세부 모든 불릿 `transcript.md#t` 링크 보유 + `#t` 앵커 실제 존재 검증, 위반 차단.
- [ ] AC-18: 보강 강제(안전망): Stop 훅은 `<!-- 미보강 -->` 잔존 시 exit 2, CLI 종료코드는 마커 미검사(bare CLI 골격 exit 0). 추가 플래그 없음.
- [ ] AC-19: executor 서브에이전트 스킬 생성 notes.md를 구조/슬라이드 커버리지/인용 그라운딩 루브릭 자동채점(정확문장 일치 없음).
- [ ] AC-20: 실영상 `19vYXnpDIyg` before/after 육안 비교(폴더=제목, 딥링크 동작, 4섹션, 발화비례).
- [ ] AC-21: 보강 완료 시 CLI exit 0 + Stop 훅 exit 0.
- [ ] AC-22: 배포 = Claude Code 플러그인(`/plugin marketplace add <repo>` + `/plugin install lectural@lectural`) 확장. npm/bun 미사용.
- [ ] AC-23: Python 런타임은 에이전트가 `uvx --from ".[run]" lectural`로 자동 실행(수동 install 단계 불필요).
- [ ] AC-24: 진입점 — Claude: SKILL 자동트리거(YouTube URL) + 명시 호출; Codex: AGENTS.md 지시(preflight→실행→보강).
- [ ] AC-25: `lectural doctor`가 전체 컴포넌트 매니페스트(Python 코어+[run] deps / ffmpeg·yt-dlp / 에이전트측 파일 SKILL·hooks·summary_prompt·AGENTS / 플러그인 등록) 검증 + 상태·OS 힌트 출력 + exit 코드 게이트.
- [ ] AC-26: `lectural doctor --fix`가 안전 자동수리(yt-dlp `uv tool install` 자동, ffmpeg OS 패키지매니저 자동 시도→실패 시 한 줄 안내)만 수행하고 idempotent 재검사 가능.
- [ ] AC-27: 에이전트(Claude 스킬/Codex AGENTS)가 첫 실행 전 `lectural doctor --fix`를 자동 호출하고 exit 0까지 반복; 사용자 필요한 항목(ffmpeg 실패/플러그인 미설치)만 한 줄로 surface.
- [ ] AC-28: README가 2부 설치(에이전트측 플러그인/AGENTS + uv/uvx 런타임 + ffmpeg 외부)와 doctor를 정직하게 설명, plugin-first 유지.

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| summary.md/outline.md 유지 | 단일 완성 노트가 UX 우위 | notes.md 단일 파일 통합, 둘 폐기 |
| 기계식 템플릿 산문도 요약 | 비문/OCR노이즈 재사용 품질 저하 | 코어는 골격+근거만, 산문은 에이전트 보강 |
| 인용은 편의 기능 | 신뢰축·충실성 메커니즘 | 개념·세부 불릿 인용 전수+앵커 유효성 강제 |
| 보강은 권장 | 누락 시 골격 출고 | Stop 훅이 미보강 마커 잔존 시 차단(안전망), CLI 미검사 |
| 모드 구분에 runstate 플래그 필요 | Stop 훅 존재=Claude/스킬 맥락 | 추가 플래그 없이 2계층 분리로 자연 구분 |
| uv 설치는 사용자 몫 | 상호작용 최소화 요구 | 에이전트가 uvx로 자동, 수동 install 제거 |
| 시스템 바이너리도 0-설치 | ffmpeg는 OS 의존 | 최대 자동 시도(베스트에포트)+실패 시 한 줄 안내 |
| 점검이 흩어짐 | 단일 진입점 필요 | `lectural doctor`(+`--fix`)로 매니페스트 검증·자동수리 통합 |
| 에이전트가 모든 설치 보장 | ffmpeg/플러그인은 한계 | doctor exit 0 계약 + idempotent 재검사, 불가항목만 surface |

## Technical Context
- 기존 모듈: `lectural/synthesis.py`, `lectural/coverage.py`, `lectural/cli.py`, `lectural/deps.py`(preflight), `scripts/completeness_hook.py`, `skills/lectural/SKILL.md`(+`.claude` parity), `hooks/hooks.json`, `.claude-plugin/{plugin,marketplace}.json`, `AGENTS.md`, `docs/synthesis_contract.md`.
- Track-2(WU-1..8) 완료 상태에서 summary/outline pair → notes.md 단일 구조로 대체.
- `lectural doctor`는 `deps.preflight()`를 매니페스트 검증으로 확장.
- 배포 생태계 참고: Claude Code plugin marketplace(`/plugin`), superpowers/oh-my-claudecode 셋업 커맨드 패턴, Codex AGENTS/skills, skills.sh(후속).
- 윈도우 비ASCII 경로 유의(cv2.imdecode 유니코드 수정 유지).

## Ontology (Key Entities)
| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| notes.md | core domain | sections, bullets, citations | derived-from transcript+synthesis_input+frames |
| transcript.md | core domain | cues, anchors(t<HHMMSS>) | linked-by notes citations |
| citation-link | core domain | target(transcript#t), youtube ?t= | belongs-to concept/detail bullet |
| synthesis_input.json | supporting | video, transcript_segments, slides, section_hints | input-to enrichment prompt |
| summary_prompt.md | supporting | role, refs-first, output-contract, few-shot, CoD, grounding, citation-rule | referenced-by SKILL.md |
| completeness_hook | supporting | section/image/citation/marker checks | validates notes.md |
| lectural doctor | supporting | manifest checks, --fix autofix, exit code | verifies all components |
| plugin/AGENTS | external | .claude-plugin, skills, hooks, AGENTS.md | distribution + entrypoint |
| uv/uvx runtime | external | [run] deps, ffmpeg, yt-dlp | executed by agent |

## Ontology Convergence
| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 1 | 9 | 9 | - | - | N/A |
| 2 | 9 | 0 | 0 | 9 | 100% |
| 3 | 8 | 0 | 1 | 7 | ~100% |
| 4-7 | 9 | 2(doctor, plugin/AGENTS, runtime) | 0 | 7 | ~95% |

## Interview Transcript
<details>
<summary>Full Q&A (Round 0 + 7 rounds)</summary>

### Round 0 — Topology
초기 5개(notes-output/core-skeleton/prompt-enrich/gate-update/verification) 확인 → 후에 distribution-install 6번째 추가.

### Round 1
인용 게이트 = 전수 + 앵커 유효성. 19%→11%.

### Round 2
보강 강제 = 안전망(필수 과정 누락 시에만). 품질은 모델+프롬프트(예시·OpenAI/Anthropic 가이드). 11%→8%.

### Round 3
미보강 차단은 Stop 훅(마커 잔존 시 exit 2), CLI 종료코드 미검사. 추가 플래그 없음. 8%→4.5%.

### Round 4 (distribution-install 추가)
배포 모델 = Claude 플러그인 + Codex AGENTS + uv/uvx 2부 설치, skills.sh 후속. ~22%.

### Round 5
시스템 바이너리 최대 자동: yt-dlp `uv tool install` 자동, ffmpeg OS 패키지매니저 자동 시도→실패 시 한 줄 안내. ~13%.

### Round 6
`lectural doctor`(상태 진단)+`--fix`(최대 자동설치)+종료코드 게이트, 에이전트 첫 실행 전 자동 호출. ~9%.

### Round 7
doctor가 전체 컴포넌트 매니페스트 검증 + 안전 자동수리 + idempotent 재검사 + 나머지 한 줄 안내(exit 코드 게이트). ~6%→4.5%.
</details>
