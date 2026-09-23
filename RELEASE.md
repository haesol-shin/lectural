# Release

LecturAL releases are lightweight GitHub Releases driven by the annotated version tag.

## Steps

1. Bump the version to the next SemVer in all three sources — `.claude-plugin/plugin.json`, `pyproject.toml`, and `lectural/__init__.py` (`__version__`) — then run `uv lock` so `uv.lock` records the new `lectural` version. `lectural doctor` reports incompatible when the module and installed distribution versions disagree.
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

The release workflow checks the tag version against all three version sources, extracts the matching `## [X.Y.Z]` section from `CHANGELOG.md` as the GitHub Release body, and publishes the release. If the tag version disagrees with any source, or the `CHANGELOG.md` section is missing, the workflow fails — so the curated changelog entry is the release notes (write it before tagging; do not hand-author a separate release description). Include `Compatibility`, `Known limitations`, and `Rollback` subsections alongside the Keep a Changelog categories.

The release workflow builds the source distribution and wheel, attaches them to the GitHub Release, and publishes the package to PyPI through Trusted Publishing. One-time prerequisites are a PyPI publisher registered for owner `haesol-shin`, repository `lectural`, workflow `release.yml`, and environment `pypi`, plus a GitHub environment named `pypi`.
