# Deep Interview Spec: LecturAL repository operations & distribution model

## Metadata
- Rounds: 6
- Final Ambiguity Score: ~4%
- Type: brownfield
- Threshold: 5% (source: default)
- Status: PASSED

## Clarity Breakdown
All five confirmed components reached goal/constraint/criteria clarity; final ambiguity ~4% (≤ 5% threshold).

## Topology
| Component | Status | Decision summary |
|-----------|--------|------------------|
| Branch & PR model | active | lean now; dev later |
| Release & versioning | active | medium-depth tag→Release |
| Automation forms | active | standard OMX set |
| Agent-ops audit + AGENTS.md | active | commit audit subset |
| Language policy | active | English meta, Korean product |

## Established Facts
- GitHub slug: `haesol-shin/lectural`
- Copyright holder: `Haesol Shin`
- License: MIT
- Branch work happens on `feat/*` via PR to `main`
- Reference model: `Yeachan-Heo/oh-my-codex` (adapt, not copy)
- Product output `notes.md` stays Korean
- Marketplace distribution = git repo + tags (no npm/PyPI/native build)

## Goal
Operate LecturAL at `haesol-shin/lectural` (MIT) with: lean `main + feat/* → PR → main` now (dev later); semver tag → GitHub Release with a version-sync gate (tag == plugin.json) plus a lightweight RELEASE.md and CHANGELOG; OMX-shaped PR/issue templates, a size-label workflow, dependabot (pip + actions), and CI; committed agent audit state (`.gjc/ultragoal` + `plans` + `specs`) while ignoring `.gjc/state`; an AGENTS.md Operations section that links to CONTRIBUTING/RELEASE; and English repo/contributor docs while product `notes.md` output and the `summary_prompt` Korean instruction/few-shot/section names stay Korean.

## Decisions (per component)
1. **Branch & PR** — Now: `main` + `feat/*` → PR → `main`; conventional commits (`feat/fix/docs/chore/refactor`). Introduce a `dev` integration branch when v0.1.0 ships OR external contributors / a regular release cadence appears; add the base-branch-guidance workflow together with `dev`.
2. **Release & versioning (medium)** — semver tags `vX.Y.Z`; tag→GitHub Release workflow; version-sync gate (tag == `plugin.json` version); `CHANGELOG.md` (Keep a Changelog) with compare links; a lightweight `RELEASE.md` tagging/notes checklist. NO `docs/qa/release-readiness-<ver>.md` and NO separate compare-range evidence file (RELEASE.md may list compare-range as a manual step).
3. **Automation forms (standard)** — OMX-shaped `PULL_REQUEST_TEMPLATE.md` + issue templates (bug/feature/config) + `dependabot.yml` (pip + github-actions, weekly) + existing CI (with `PYTHONUTF8=1`) + a PR size-label workflow. base-branch-guidance deferred until `dev`. NO document-refresh warning, NO coverage gate.
4. **Agent-ops audit + AGENTS.md** — COMMIT `.gjc/ultragoal` (goals.json, ledger.jsonl, quality-gate-*.json), `.gjc/plans`, `.gjc/specs` as an in-repo audit trail; IGNORE `.gjc/state` runtime. This reverses the prior gitignore-all choice: update `.gitignore` to ignore only `.gjc/state/` (and `.tmp/`), and re-track the audit subset. AGENTS.md gains an "Operations" section that LINKS to `CONTRIBUTING.md`/`RELEASE.md` (single source) and states the agent audit policy + gate-run expectations; no duplication of branch/release detail.
5. **Language (standard)** — Convert to English: `README.md` (done), `CONTRIBUTING.md`, `RELEASE.md`, `CHANGELOG.md`, issue/PR templates, `AGENTS.md`, `docs/ac_verification.md`, `docs/synthesis_contract.md`, mermaid labels. Keep Korean: product `notes.md` output; `summary_prompt.md` "write Korean" instruction + Korean few-shot + Korean notes section names (한눈 요약 / 목차 / 흐름 / 핵심 개념·이론 / 정리 노트 / 복습 질문 / 정리 커버리지); Korean detector words in `tests/test_redteam_readme.py` forbidden-framing list.

## Constraints
- Identity fixed (slug/copyright/MIT) as in Established Facts.
- Distribution is marketplace-only (git repo + tags); no build/publish pipeline.
- Keep the two-layer completeness gate and token-0 deterministic core unchanged.
- All execution lands on `feat/*` with PR to `main`; conventional commits.

## Non-Goals
- npm/PyPI publishing, cargo/native build (OMX-specific).
- document-refresh warning system, coverage gate.
- Introducing `dev` now.
- Changing product output language to English / translating Korean study notes.

## Acceptance Criteria
- [ ] `plugin.json`, `marketplace.json`, `LICENSE`, `README.md` use `haesol-shin/lectural`, `Haesol Shin`, MIT (no placeholders).
- [ ] `LICENSE` (MIT) present; `plugin.json` `license: MIT`.
- [ ] `CHANGELOG.md` (Keep a Changelog) and `RELEASE.md` checklist present, in English.
- [ ] `.github/`: PR template + issue templates (bug/feature/config) + `dependabot.yml` (pip + actions) + size-label workflow + release workflow (tag `v*` → GitHub Release with version-sync) + CI with UTF-8.
- [ ] `.gitignore` ignores only `.gjc/state/` and `.tmp/`; `.gjc/ultragoal`, `.gjc/plans`, `.gjc/specs` are tracked and committed.
- [ ] `AGENTS.md` has an Operations section linking CONTRIBUTING/RELEASE + audit policy.
- [ ] English conversion done for the listed repo/contributor docs; Korean preserved for the listed product surfaces.
- [ ] Offline test suite green; `lectural doctor` ready; `tests/test_redteam_readme.py` updated for the English README.
- [ ] All work on `feat/*` via PR to `main`; conventional commit messages.

## Deferrals
- `dev` branch + base-branch-guidance workflow (trigger: v0.1.0 ship / external contributors / cadence).
- document-refresh warning, coverage gate.
- Convergence pacing: bidirectional scoring is the pacing mechanism (no min-round floor).

## Technical Context
- Plugin tree is the single source (no `.claude/` mirror); dev via `claude --plugin-dir .`.
- Existing CI at `.github/workflows/ci.yml` (matrix win/ubuntu/macos) already updated with UTF-8 env.
- Prior commits already: README rewrite (English), LICENSE (MIT), plugin.json MIT, CHANGELOG/templates scaffolded (uncommitted working tree) — execution reconciles these to the decisions above and lands them on `feat/*`.

## Interview Transcript (summary)
- R0 Topology: 5 components confirmed.
- R1 Agent-ops: commit `.gjc/ultragoal`+plans+specs audit, ignore `.gjc/state`.
- R2 Release: medium depth (revised from full) — RELEASE.md + version-sync + CHANGELOG, no QA readiness doc.
- R3 Automation: standard set (templates + dependabot + CI + size-label; base-guidance deferred).
- R4 Language: standard (all meta/docs English incl ac_verification; product Korean).
- R5 Branch: lean now, dev on v0.1.0/external/cadence.
- R6 AGENTS.md: Operations section linking CONTRIBUTING/RELEASE.
