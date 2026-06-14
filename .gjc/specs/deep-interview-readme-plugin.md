# Deep Interview Spec: LecturAL README 및 Claude Code 플러그인 패키징

## Metadata
- Interview ID: li-readme-2026-0613
- Rounds: 3
- Final Ambiguity Score: 4.75%
- Type: brownfield
- Generated: 2026-06-13T10:33:00Z
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
| Goal Clarity | 0.97 | 0.35 | 0.3395 |
| Constraint Clarity | 0.95 | 0.25 | 0.2375 |
| Success Criteria | 0.94 | 0.25 | 0.2350 |
| Context Clarity | 0.94 | 0.15 | 0.1410 |
| **Total Clarity** | | | **0.9525** |
| **Ambiguity** | | | **0.0475** |

## Topology
| Component | Status | Description | Coverage / Deferral Note |
|-----------|--------|-------------|--------------------------|
| README 재작성 | active | 인트로 담백화, 동작 방식 Mermaid, 기술 스택 삭제, plugin 설치 중심 문서화 | README.md에 모두 반영. README와 SKILL 모두 중립 톤 적용. |
| 플러그인 패키징 | active | Claude Code plugin 구조로 배포 가능하게 정리 | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `skills/lectural/SKILL.md`, `hooks/hooks.json` 구조를 만든다. |

## Goal
LecturAL의 README와 Claude Code plugin packaging을 실제 사용 흐름에 맞게 재작성/재구성한다. 사용자는 repo clone 중심 문서가 아니라 `/plugin marketplace add <GITHUB_REPO_URL>` 및 `/plugin install lectural@lectural` 중심으로 이해하고, plugin 설치 뒤 Claude/host agent가 안내를 읽어 `uv` 기반 Python dependency setup과 `ffmpeg` 확인을 수행하는 two-part install을 명확히 알 수 있어야 한다.

## Constraints
- 사용자-facing prose는 한국어로 작성한다. code identifiers, paths, commands는 English 그대로 둔다.
- README intro에서 “확신을 주는 목표”와 “시험 기간 / 강의가 유튜브에만 올라와 있을 때” 프레이밍을 제거한다.
- “기술 스택” 섹션은 README에서 삭제한다.
- “동작 방식”은 ASCII diagram이 아니라 Mermaid `flowchart`로 표현한다.
- 설치는 clone-first가 아니라 Claude Code plugin install-first로 설명한다.
- 실제 plugin packaging까지 포함한다. 단, Python package dependencies와 system binary `ffmpeg`는 plugin install만으로 자동 보장된다고 쓰지 않는다.
- plugin 이름은 `lectural`로 한다. README에는 repo URL을 `<GITHUB_REPO_URL>` placeholder로 둔다.
- local LLM / Ollama summary fallback은 README와 plugin docs에서 제외한다.
- README와 `skills/lectural/SKILL.md` 모두 “확신” 프레이밍을 제거하고 “완전성 검증”, “누락 방지”, “coverage gate” 같은 검증 가능한 표현으로 바꾼다.
- Python product logic change는 의도하지 않는다.

## Non-Goals
- LecturAL core Python pipeline logic 변경.
- local LLM fallback 추가 또는 문서화.
- non-developer GUI, GPU path, diarization, translation 추가.
- 실제 GitHub URL 확정. `<GITHUB_REPO_URL>` placeholder를 사용한다.

## Acceptance Criteria
- [ ] `README.md` 첫 소개가 담백하고, “확신” 및 시험기간/유튜브-only 프레이밍을 포함하지 않는다.
- [ ] `README.md`에 Mermaid `flowchart` 기반 “동작 방식” 섹션이 있다.
- [ ] `README.md`에서 “기술 스택” 섹션이 제거되어 있다.
- [ ] `README.md` 설치 섹션이 `/plugin marketplace add <GITHUB_REPO_URL>` 및 `/plugin install lectural@lectural` 중심이다.
- [ ] README가 plugin install 후 Claude/host agent가 dependency setup을 읽고 수행하는 흐름을 명확히 설명한다.
- [ ] README가 `uv` package management와 `ffmpeg` system binary requirement를 과장 없이 별도 준비/검사 대상으로 설명한다.
- [ ] `.claude-plugin/plugin.json`과 `.claude-plugin/marketplace.json`이 존재하고 plugin name/entry가 `lectural`이다.
- [ ] plugin-compatible `skills/lectural/SKILL.md`가 존재한다.
- [ ] plugin-scoped hook config `hooks/hooks.json`이 존재하고 `scripts/completeness_hook.py`를 Stop hook으로 연결한다.
- [ ] 기존 `.claude/skills/lectural/SKILL.md`의 사용자-facing wording도 중립화하거나 plugin source로 이동되어, 배포되는 skill에 “확신” 프레이밍이 남지 않는다.
- [ ] README에 local LLM/Ollama fallback이 언급되지 않는다.
- [ ] 문서/packaging 변경 후 관련 빠른 검증(README grep, plugin metadata JSON parse, hook path existence, 기존 offline tests 또는 packaging-relevant subset)이 통과한다.
- [ ] 작업 단위별 git commit을 만든다(사용자 지시: package management는 uv, 작업 단위별 commit).

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| Claude plugin install만으로 모든 runtime dependency가 설치된다 | Python deps와 ffmpeg는 plugin install만으로 보장하기 어렵다 | plugin install 후 Claude/host agent가 setup instructions를 읽어 `uv`와 `ffmpeg` 준비/검사를 수행하는 two-part install로 문서화 |
| README만 바꾸면 충분하다 | 사용자는 plugin 설치를 원했고, README가 말하는 설치가 실제 구조와 맞아야 한다 | README 재작성과 실제 plugin packaging을 함께 수행 |
| “확신” 표현은 README에만 문제다 | 기존 `.claude/skills/lectural/SKILL.md:15`에도 같은 framing이 있다 | README와 배포되는 `skills/lectural/SKILL.md` 모두 중립 톤으로 정리 |
| GitHub URL을 지금 확정해야 한다 | 실제 URL은 아직 주어지지 않았다 | current repo를 marketplace+plugin repo로 가정하고 `<GITHUB_REPO_URL>` placeholder 사용 |

## Technical Context
- Existing project files: `lectural/`, `scripts/completeness_hook.py`, `.claude/skills/lectural/SKILL.md`, `.claude/settings.json`, `docs/`, `tests/`, `README.md`.
- Current README has clone-based installation and an ASCII operation diagram.
- Current `.claude/skills/lectural/SKILL.md:15` contains the disliked confidence framing.
- Plugin research: `.claude-plugin/plugin.json` required; marketplace catalog at `.claude-plugin/marketplace.json`; plugin components live at plugin root (`skills/`, `hooks/`, etc.); install via `/plugin marketplace add <repo>` then `/plugin install <name>@<marketplace>`; local testing can use `--plugin-dir <path>`; plugin hook changes may require `/reload-plugins` or restart.

## Ontology (Key Entities)
| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| LecturAL Plugin | core deliverable | plugin name lectural, marketplace repo placeholder, plugin.json, marketplace.json, skills/lectural, hooks/hooks.json, neutral skill wording | bundles skill and hook with README-consistent tone |
| README | user-facing documentation | plain intro, Mermaid flowchart, plugin install instructions, no tech stack section, no confidence/exam framing | describes plugin installation and LLM-guided setup |
| LLM-guided setup | installation flow | uv setup, ffmpeg check, no local LLM fallback | runs after plugin install to prepare Python runtime |

## Ontology Convergence
| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 1 | 3 | 3 | - | - | - |
| 2 | 3 | 0 | 0 | 3 | 100% |
| 3 | 3 | 0 | 0 | 3 | 100% |

## Interview Transcript
<details>
<summary>Full Q&A (3 rounds)</summary>

### Round 0
**Q:** README 재작성과 실제 plugin packaging을 둘 다 포함할까요?
**A:** 둘 다 포함 — README 재작성 + 실제 플러그인 패키징까지.

### Round 1
**Q:** Claude Code plugin만으로 Python deps/ffmpeg까지 완전 자동 설치된다고 말하면 부정확합니다. README는 이 설치 한계를 어떻게 처리해야 하나요?
**A:** 플러그인 설치 후 LLM/host agent가 README 또는 skill instructions를 읽고 uv 기반 Python dependency setup 및 ffmpeg 안내/검사를 수행하게 한다. 로컬 LLM fallback은 제외한다.
**Ambiguity:** 21.55% (Goal: 0.88, Constraints: 0.78, Criteria: 0.74, Context: 0.76)

### Round 2
**Q:** 설치 문서와 플러그인 메타데이터의 이름/경로를 어떻게 잡을까요?
**A:** 현재 repo를 marketplace+plugin repo로 가정하고 `lectural` plugin 이름을 사용한다. README에는 `<GITHUB_REPO_URL>` placeholder만 둔다.
**Ambiguity:** 10.6% (Goal: 0.94, Constraints: 0.90, Criteria: 0.84, Context: 0.86)

### Round 3
**Q:** README만 담백하게 바꿀까요, 아니면 플러그인으로 배포되는 `skills/lectural/SKILL.md` 문구도 같은 기준으로 정리할까요?
**A:** README와 `skills/lectural/SKILL.md` 둘 다 중립적 톤으로 정리한다. “확신” 프레이밍은 제거하고, “완전성 검증/누락 방지”처럼 검증 가능한 표현을 쓴다.
**Ambiguity:** 4.75% (Goal: 0.97, Constraints: 0.95, Criteria: 0.94, Context: 0.94)

</details>
