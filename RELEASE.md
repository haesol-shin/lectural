# Release

LecturAL releases are lightweight GitHub Releases driven by the annotated version tag.

## Steps

1. Bump `.claude-plugin/plugin.json` to the next SemVer version.
2. Move `CHANGELOG.md` notes from `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` and update the compare links.
3. Ensure `main` is green:
   - `uv run --with pytest --with numpy pytest -q`
   - `lectural doctor --json` reports `overall_status: ready`
4. Review release notes against the compare range:

   ```bash
   git log PREV..NEXT
   ```

5. Push an annotated tag:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

The release workflow checks the tag version against `.claude-plugin/plugin.json` and creates the GitHub Release.

Do not run a build, npm publish, or a separate QA readiness document for this project.

## Agent audit policy

Commit durable audit artifacts that explain shipped work: `.gjc/ultragoal`, `.gjc/specs`, and scoped `.gjc/plans`. Do not commit `.gjc/state`.
