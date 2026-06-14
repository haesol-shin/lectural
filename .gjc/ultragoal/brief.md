Execute the ralplan-approved v0.1.1 maintenance release for haesol-shin/lectural (approved consensus plan: .gjc/plans/ralplan/2026-06-13-0738-79e5/pending-approval.md; Architect CLEAR/APPROVE + Critic OKAY at pass 2). Repo root C:/Users/haesol/dev/LecturAL, branch main, public. Constraints: SemVer 0.1.1 PATCH (pre-1.0, no new feat; do NOT force 0.2.0); plugin.json version is one of three synchronized version surfaces; Conventional Commits; token-0 deterministic core, lazy heavy deps; offline gate must stay green. MAINTAINER RULE: never merge/tag without explicit maintainer approval. Test C is OUT OF SCOPE. git diff --check stays documentation-only (not a CI gate).

@goal: Assemble, verify, and open the v0.1.1 release PR (plan S0-S12)
Build the integrated `release/0.1.1` branch off fresh main and open ONE template-compliant PR that supersedes/closes PR #12. Do NOT merge or tag (plan S13 is maintainer-approval-gated and excluded from this story).

Steps (from the approved plan):
- S0 Create release/0.1.1 off updated main.
- S1 Integrate branch refactor/remove-plugin-skill (delete skills/lectural/SKILL.md, keep references/; doctor.py AGENT_FILES; test_doctor fixture; test_redteam_packaging; pipeline.md; AGENTS/README/plugin.json description; shorten both command descriptions + drop [lectural] prefix).
- S2 Integrate ci/pr-template-guidance (advisory non-blocking pr-check.yml + AGENTS/CONTRIBUTING PR-template rule).
- S3 Integrate ci/release-notes-from-changelog (release.yml CHANGELOG-section extraction + RELEASE.md).
- S4 Resolve the AGENTS.md conflict by hand: keep BOTH the Operations PR-template bullet and the de-skilled Pointers line; fix stale wording '## Skill-driven host-agent enrichment' and 'After a skill-driven lectural run' -> command-driven / slash-command-driven.
- S5 Stale-wording sweep beyond AGENTS.md: fix commands/setup.md step 1 ('plugin/skill/hook wiring'); tree grep gate finds no stray SKILL.md / skill-driven / standalone-skill refs in user/contributor surfaces (skills/lectural/references allowed).
- S6 Port release.yml awk extraction to scripts/changelog_notes.py invoked as `python scripts/changelog_notes.py <version> > release-notes.md` then `test -s release-notes.md`; helper excludes the next '## [' header and trailing '[...]:' link refs, handles the last section, trims leading blanks, empty for missing version.
- S7 Add tests/test_changelog_notes.py (4 cases: existing version non-empty excluding next header + link refs; last section excludes link refs; missing version empty; leading-blank trim).
- S8 Add Test A: offline pytest asserting plugin.json==pyproject.toml==lectural/__init__.py __version__, EXACTLY ONE anchored re.escape-d CHANGELOG heading `^## \[<ver>\] - \d{4}-\d{2}-\d{2}$` and EXACTLY ONE compare link `^\[<ver>\]: https://github.com/haesol-shin/lectural/compare/v<prev>...v<ver>$`, plus a NEGATIVE mutation case.
- S9 Synchronized bump to 0.1.1 in .claude-plugin/plugin.json (l3), pyproject.toml (l3), lectural/__init__.py __version__ (l24); add CHANGELOG '## [0.1.1] - 2026-06-14' (### Removed: plugin skill; ### Changed: command descriptions + corrected stale wording; ### Added: PR-template advisory check, release-notes automation, plugin-validate CI, the new tests) + compare links ([Unreleased]->v0.1.1...HEAD; [0.1.1]: v0.1.0...v0.1.1).
- S10 Add plugin-validate to EXISTING .github/workflows/ci.yml under push+pull_request (NOT pull_request_target): actions/setup-node + `npm install -g @anthropic-ai/claude-code@2.1.177` (PINNED) + `claude plugin validate .`; CONTRIBUTING Testing adds the validate command + a doc-only `git diff --check` note; add `claude plugin validate .` to PULL_REQUEST_TEMPLATE.md Checklist.
- S11 Full pre-merge verification on release/0.1.1.
- S12 Open ONE template-compliant PR release/0.1.1 -> main, body fully filled (Summary/Changes/Validation/Checklist/Related), explicitly superseding + `Closes #12`.

Acceptance criteria:
- release/0.1.1 contains all three branches' changes + Test A + Test B + plugin-validate CI + synchronized 0.1.1 bump + CHANGELOG [0.1.1]; AGENTS.md keeps both the Operations bullet and corrected Pointers line; no stale skill wording remains.
- `git diff --check` clean; `uv run --with pytest --with numpy pytest -q` green (>=246 + new Test A/B cases); `lectural doctor --json` ready with no version-mismatch; `claude plugin validate .` passes; `python scripts/changelog_notes.py 0.1.1` non-empty (no '## [' header, no '[...]:' links); three version surfaces all equal 0.1.1.
- ONE PR open release/0.1.1 -> main, template-compliant, supersedes/closes #12.
- NOT merged, NOT tagged (maintainer-approval-gated S13).

Verification commands: git diff --check; uv run --with pytest --with numpy pytest -q; lectural doctor --json; claude plugin validate .; python scripts/changelog_notes.py 0.1.1.
