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
- Body: include a `## Summary` section and a `## Verification` section; link issues with `Fixes #N` when applicable.
- Merge strategy:
  - **Rebase and merge** (default): use when the branch holds clean, individually meaningful Conventional Commits worth preserving in `main` history. Keeps history linear and compare-range release notes accurate.
  - **Squash and merge**: use when the branch has noisy WIP/fixup commits or is a single logical change. The squash commit message MUST be a Conventional Commit, because it becomes the `main` history entry.
  - Avoid merge commits; keep `main` linear.

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
