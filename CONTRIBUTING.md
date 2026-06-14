# Contributing

Thanks for helping improve LecturAL. Keep changes small, reviewable, and aligned with the single plugin tree in this repository.

## Development setup

Install the runtime extras in editable mode:

```bash
uv pip install -e ".[run]"
```

For local Claude Code plugin development, load this checkout directly and reload after edits:

```bash
claude --plugin-dir .
/reload-plugins
```

Run the doctor before exercising runtime paths:

```bash
lectural doctor
```

## Project layout

- `lectural/`: Python package and CLI/runtime implementation.
- `skills/lectural/`: Claude Code skill and references.
- `commands/`: plugin slash-command markdown.
- `hooks/`: plugin hook configuration.
- `docs/`: contracts and verification evidence.
- `tests/`: offline unit and contract tests.
- `.claude-plugin/`: plugin metadata.

This repository uses one plugin tree. Do not add or maintain a `.claude/` mirror.

## Branch model

- Use `feat/*` branches for feature and documentation work.
- Open a pull request into `main`; `main` is the release branch.
- A long-lived `dev` branch starts at v0.1.0 only when external contributor volume or release cadence justifies it.

## Commit style

Use Conventional Commits with these common types:

- `feat:` user-visible capability
- `fix:` bug fix
- `docs:` documentation-only change
- `chore:` maintenance without behavior change
- `refactor:` behavior-preserving code change

## Pull requests

- Title: short imperative summary (about 50-72 characters), no Conventional Commit prefix. Example: `Set up repo operations & distribution model`.
- Body: follow `.github/PULL_REQUEST_TEMPLATE.md` exactly — `## Summary`, `## Changes`, `## Validation`, `## Checklist`, `## Related`. Link issues under **Related** with `Closes #N`.
- The web UI pre-fills the template automatically. When opening a PR non-interactively (`gh pr create --body-file`, or the API), the template is NOT injected — scaffold the body from `.github/PULL_REQUEST_TEMPLATE.md` and fill every section. The non-blocking `PR Check` workflow warns when a required section is missing.
- Merge only with maintainer approval.
- Merge strategy:
  - **Rebase and merge** (default): use when the branch holds clean, individually meaningful Conventional Commits worth preserving in `main` history. Keeps history linear and compare-range release notes accurate.
  - **Squash and merge**: use when the branch has noisy WIP/fixup commits or is a single logical change. The squash commit message MUST be a Conventional Commit, because it becomes the `main` history entry.
  - Avoid merge commits; keep `main` linear.

## Dependency policy

Runtime dependencies are pinned with intentional upper-bound caps (`opencv-python`,
`paddleocr`, `paddlepaddle`, `setuptools`). These caps are compatibility boundaries,
not arbitrary: for example `opencv-python` is held at `<=4.6.0.66` because cv2 4.11+
breaks the runtime. The offline CI does not exercise these heavy deps (they are
lazily imported and smoke-skipped), so a green CI does not validate a major bump.

Because of this, Dependabot is scoped to GitHub Actions plus security updates only;
it does not open scheduled version-bump PRs for the Python caps. To raise a heavy
dependency major, do it deliberately:

1. Raise the cap in `pyproject.toml`.
2. Regenerate the lockfile: `uv lock`.
3. Run the real smoke/OCR end-to-end path and confirm it passes.
4. Commit the cap change and the updated `uv.lock` together.

## Testing

Run the full offline suite without extra environment variables:

```bash
uv run --with pytest --with numpy pytest -q
```

Check runtime readiness separately:

```bash
lectural doctor
```

## Pull request checklist

- [ ] Scope is focused and reversible.
- [ ] User-facing behavior, docs, and changelog are updated together when needed.
- [ ] `uv run --with pytest --with numpy pytest -q` passes or the PR explains why it was not run.
- [ ] `lectural doctor` reports the runtime status or the PR explains unavailable runtime dependencies.
- [ ] No `.claude/` mirror or duplicate plugin tree was introduced.

## Agent audit policy

Release-time agent audit material is governed by [RELEASE.md](RELEASE.md).
