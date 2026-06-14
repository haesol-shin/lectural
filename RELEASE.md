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

The release workflow checks the tag version against `.claude-plugin/plugin.json`, extracts the matching `## [X.Y.Z]` section from `CHANGELOG.md` as the GitHub Release body, and publishes the release. If the tag version and `plugin.json` disagree, or the `CHANGELOG.md` section is missing, the workflow fails — so the curated changelog entry is the release notes (write it before tagging; do not hand-author a separate release description).

Do not run a build, npm publish, or a separate QA readiness document for this project.

## Agent audit policy

Commit the durable audit trail that explains shipped work: `.gjc/ultragoal` and `.gjc/specs`. Do not commit `.gjc/state` or `.gjc/plans` (the shared ralplan run-id directory is not cleanly isolable, so it stays ignored until a per-run-id scheme is introduced).
