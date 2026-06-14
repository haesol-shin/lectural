# Deep Interview Spec: LecturAL 차기 방향 (개발자 OSS 에이전트 툴)

## Metadata
- Interview ID: li-direction-2026-0613
- Rounds: 8
- Final Ambiguity Score: 4.7%
- Type: brownfield
- Generated: 2026-06-13T20:33:00Z
- Threshold: 0.05
- Threshold Source: default
- Initial Context Summarized: yes
- Status: PASSED
- Auto-Researched Rounds: []
- Auto-Answered Rounds: []
- Architect Failures: 0

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.96 | 0.35 | 0.336 |
| Constraint Clarity | 0.96 | 0.25 | 0.240 |
| Success Criteria | 0.95 | 0.25 | 0.2375 |
| Context Clarity | 0.93 | 0.15 | 0.1395 |
| **Total Clarity** | | | **0.953** |
| **Ambiguity** | | | **0.047** |

## Topology
| Component | Status | Description | Coverage / Deferral Note |
|-----------|--------|-------------|--------------------------|
| 런타임 전략 | active | Python 코어 유지 vs TS | R2: Python 코어 유지 + 에이전트별 markdown 매니페스트 + uvx; 전면 TS 재작성 제외 |
| 설치 자동화+멀티OS | active | Win/Linux/macOS 설치 | R4: host agent가 preflight 결과로 OS 판단·설치 명령 제안/실행 |
| 포지셔닝 | active | 학습 전용 vs 일반 | R3: 메인 '유튜브 영상→완전 노트', 강의/슬라이드 sweet spot |
| 멀티 에이전트 | active | Claude Code + Codex | R5: CLI-게이트를 주 강제로, Claude Stop 훅·Codex AGENTS.md는 CLI 랩핑 |
| 차별화 축 | active | 완전성 보증 해자 | R1/R6: 개발자 OSS, 완전성 게이트 해자; 다음 릴리스=최소 스콩+uvx |
| (future) Web UI / MCP server | deferred | TS 레이어 | 사용자 확인 defer — 나중 TS로 도입 |

## Goal
LecturAL을 **Claude Code·Codex 개발자가 플러그인/설정으로 설치해 쓰는 OSS 에이전트 도구**로 자리잡는다. 포지셔닝은 “유튜브 영상 → 완전 노트(모든 발화·화면텍스트·장면)”로 넓히되, 강의/슬라이드형을 sweet spot으로 명시한다. 핵심 해자는 **CLI로 강제되는 완전성 게이트**(누락 방지)로, 어떤 에이전트에서도 동일하게 작동한다. 런타임은 Python 코어를 유지하고(한국어 OCR/STT 품질·토큰 0 원칙), 배포 편의는 markdown 매니페스트와 uvx로 해결한다.

## Constraints
- 런타임: Python 코어 유지. 에이전트 통합은 markdown(`.claude-plugin`, `AGENTS.md`)로, 패키징 편의는 `uvx`로. TS는 MCP 서버/웹 UI를 정식 목표로 삼을 때만 도입.
- 완전성 게이트는 `lectural` CLI의 exit code로 강제(실패 시 non-zero). Claude Stop 훅과 Codex AGENTS.md는 이 CLI를 랩핑만 한다(에이전트 무관 강제).
- 설치: host agent가 `preflight` 결과를 보고 OS를 판단해 적절한 명령을 제안/실행. preflight는 OS별(Windows/Linux/macOS) 힌트 출력. 브리틀한 부트스트랩 스크립트는 지양.
- 사용자-facing prose는 한국어(README). 그 외 docs/skill/packaging artifact(AGENTS.md 포함)는 영어. code/paths/commands/anchor symbol은 항상 영어.
- package management는 `uv`/`uvx`. 작업 단위별 git commit.
- 제품 코어 로직(`lectural/`) 품질/동작은 이번 requirements 단계에서 변경하지 않는다(구현은 ralplan 이후).
- ffmpeg는 시스템 바이너리라 uvx로 번들 불가 — “완전 제로인스톨”은 불가능함을 정직하게 표기.

## Non-Goals (이번 릴리스 제외)
- 제품명 변경(LecturAL 유지).
- 웹 UI / 비개발자 GUI (나중 TS).
- MCP 서버 (나중 TS).
- 로컬 LLM/클라우드 요약 폴백 (토큰 0 유지).
- 화자 분리/번역, GPU 경로, 병렬 배치.
- 경쟁 벤치마크/비교표.
- ffmpeg 자동 번들/완전 제로인스톨(preflight 안내로 대체).
- 전면 TS 재작성.

## Acceptance Criteria
- [ ] `lectural` CLI가 커버리지 실패 시 non-zero exit함을 테스트로 증명(에이전트 무관 강제가 도구 레벨에 존재).
- [ ] `AGENTS.md`(repo 루트, 영어)가 존재하고 Codex 사용자가 동일 파이프라인을 쓰도록 안내하며, CLI 완전성 게이트 랩핑을 명시.
- [ ] README가 Windows/Linux/macOS 설치와 `uvx` 실행 경로를 모두 안내.
- [ ] `preflight`가 OS별(Windows/Linux/macOS) 설치 힌트를 출력.
- [ ] README 포지셔닝 문구가 “유튜브 영상→완전 노트(강의 sweet spot)”로 갱신.
- [ ] 실영상 1개로 `uvx` 경로 end-to-end 성공 + 기존 오프라인 테스트 유지(회귀 없음).
- [ ] 사용자-facing prose 한국어 / 그 외 artifact 영어 규칙 유지(AGENTS.md 포함).
- [ ] 작업 단위별 git commit(uv/uvx).

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| TS로 가야 확장된다 | JS 의존은 배포/통합·MCP·웹UI 때문이지 연산 때문이 아니다 | Python 코어 유지 + markdown 매니페스트 + uvx; TS는 MCP/웹UI defer |
| 설치 자동화=부트스트랩 스크립트 | 블랙박스 스크립트는 권한/패키지매니저 충돌·그좌립 | host agent가 preflight로 OS 판단 후 명령 제안/실행 |
| 완전성 게이트는 Claude Stop 훅 | Codex에는 Stop 훅이 없음 | 게이트를 CLI exit code로 내려 에이전트 무관 강제 |
| 학습 전용 툴 | 기술은 이미 일반 영상에 동작 | 메인 일반화 + 강의 sweet spot 명시 |
| 차별화=슬라이드 OCR | 경쟁(steipete)도 슬라이드 OCR 함 | 해자를 “완전성 보증(CLI 강제)”으로 좁힘 |

## Technical Context
- 기존: `lectural/` Python(faster-whisper/PaddleOCR/OpenCV/yt-dlp/webrtcvad), `.claude-plugin/`(plugin.json+marketplace.json), `skills/lectural/SKILL.md`(영어), `hooks/hooks.json`(Stop), `scripts/completeness_hook.py`, README(한국어), 136 오프라인 테스트.
- `lectural.cli.main`은 이미 실패 시 `return 2` — CLI-게이트 주 강제는 저위험 격상.
- 실영상 스모크(6분 강의): dedupe ~153s + OCR ~72s가 비용 대부분, 총 ~232s, exit 0.
- 경쟁: steipete/summarize(슬라이드 OCR 있음, transcript-first+whisper.cpp/cloud), NoteGPT/Notta/Eightify/Glasp(요약 중심, OCR/완전성 게이트 없음).
- Codex는 `AGENTS.md` 관례를 읽음(plugin marketplace 아님). uvx는 Python만 제로인스톨, ffmpeg는 별도.

## Ontology (Key Entities)
| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| LecturAL | core deliverable | dev OSS, YouTube→complete notes, name kept | installed by devs via Claude Code/Codex |
| Developer | primary user | uses Claude Code or Codex | installs/runs LecturAL |
| Completeness Gate | differentiator | CLI non-zero exit, agent-agnostic | hooks/AGENTS.md wrap CLI; the moat |
| Preflight | install mechanism | OS-aware hints, agent-driven | host agent installs from preflight |
| uvx | distribution | Python-only zero-install | ffmpeg still external |
| Future TS layer | deferred | MCP server, Web UI | introduced later |

## Ontology Convergence
| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 1 | 3 | 3 | - | - | N/A |
| 2 | 4 | 1 | 0 | 3 | 100% |
| 3 | 4 | 0 | 0 | 4 | 100% |
| 4 | 4 | 1 | 0 | 3 | 75% |
| 5 | 4 | 1 | 1 | 3 | 100% |
| 6 | 4 | 0 | 0 | 4 | 100% |
| 7 | 4 | 1 | 0 | 3 | 75% |

## Interview Transcript
<details>
<summary>Full Q&A (8 rounds)</summary>

### Round 1 (moat/goal)
**Q:** 진짜 목표/대상 사용자?
**A:** B. 개발자 커뮤니티 OSS 공개툴(Claude Code/Codex plugin). | Ambiguity 40.5%

### Round 2 (runtime/constraints)
**Q:** 런타임 전략? (JS 의존 이유 설명 후)
**A:** B. Python 코어+markdown 매니페스트+uvx; MCP서버/웹UI는 TS로 defer. | Ambiguity 30.3%

### Round 3 (positioning/criteria)
**Q:** 포지셔닝?
**A:** A. 메인 '유튜브 영상→완전 노트', 강의/슬라이드 sweet spot. | Ambiguity 24%

### Round 4 (install/criteria, contrarian)
**Q:** 설치 자동화 수용 기준?
**A:** D. host agent가 preflight로 OS 판단해 명령 제안/실행. | Ambiguity 18%

### Round 5 (agents/criteria)
**Q:** Codex엔 Stop 훅이 없는데 완전성 게이트를 어떻게 강제?
**A:** A. 게이트를 CLI로 내림(non-zero exit), 훅은 CLI 랩핑. | Ambiguity 12.9%

### Round 6 (moat/criteria, simplifier)
**Q:** 가장 간단한 가치 있는 다음 릴리스 범위?
**A:** B. 최소 스콩(CLI-gate/Codex/멀티OS/포지셔닝) + uvx 제로인스톨. | Ambiguity 9%

### Round 7 (positioning/constraints)
**Q:** 비목표 확정?
**A:** 전부 제외(제품명 유지, 웹UI, MCP, LLM 폴백, 화자분리/번역/GPU/병렬, 벤치마크, ffmpeg 번들). | Ambiguity 5.5%

### Round 8 (criteria)
**Q:** “완료” 검증 기준?
**A:** A. 객관적 검증 세트(CLI exit 테스트, AGENTS.md, 멀티OS+uvx README, preflight OS 힌트, 포지셔닝 갱신, 실영상 uvx e2e + 오프라인 테스트 유지). | Ambiguity 4.7%

</details>
