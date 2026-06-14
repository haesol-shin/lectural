"""Version-surface + CHANGELOG consistency guard (offline).

Fails the suite if the three version surfaces drift, or if the released version
lacks exactly one dated CHANGELOG heading and exactly one link reference. This
catches a version bump that forgot its changelog entry before tagging.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "lectural" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"

_PYPROJECT_VERSION_RE = re.compile(r'(?m)^version\s*=\s*"([^"]+)"')
_INIT_VERSION_RE = re.compile(r'(?m)^__version__\s*=\s*"([^"]+)"')


def _plugin_version() -> str:
    return json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"]


def _pyproject_version() -> str:
    match = _PYPROJECT_VERSION_RE.search(PYPROJECT.read_text(encoding="utf-8"))
    assert match, "pyproject.toml has no `version = \"...\"` line"
    return match.group(1)


def _init_version() -> str:
    match = _INIT_VERSION_RE.search(INIT.read_text(encoding="utf-8"))
    assert match, "lectural/__init__.py has no `__version__ = \"...\"` line"
    return match.group(1)


def _heading_count(changelog_text: str, version: str) -> int:
    pattern = re.compile(
        r"(?m)^## \[" + re.escape(version) + r"\] - \d{4}-\d{2}-\d{2}$"
    )
    return len(pattern.findall(changelog_text))


def _link_count(changelog_text: str, version: str) -> int:
    esc = re.escape(version)
    pattern = re.compile(
        r"(?m)^\[" + esc + r"\]: https://github\.com/haesol-shin/lectural/"
        r"(?:compare/v\d+\.\d+\.\d+\.\.\.v" + esc + r"|releases/tag/v" + esc + r")$"
    )
    return len(pattern.findall(changelog_text))


def test_all_three_version_surfaces_agree():
    plugin = _plugin_version()
    assert _pyproject_version() == plugin, "pyproject.toml version != plugin.json"
    assert _init_version() == plugin, "lectural/__init__.py __version__ != plugin.json"


def test_changelog_has_exactly_one_dated_heading_for_current_version():
    version = _plugin_version()
    text = CHANGELOG.read_text(encoding="utf-8")
    assert _heading_count(text, version) == 1, (
        f"CHANGELOG.md must have exactly one '## [{version}] - YYYY-MM-DD' heading"
    )


def test_changelog_has_exactly_one_link_reference_for_current_version():
    version = _plugin_version()
    text = CHANGELOG.read_text(encoding="utf-8")
    assert _link_count(text, version) == 1, (
        f"CHANGELOG.md must have exactly one '[{version}]: <compare-or-tag-url>' link"
    )


def test_negative_missing_section_is_detected():
    version = _plugin_version()
    text = CHANGELOG.read_text(encoding="utf-8")
    # Removing the dated heading must make the guard fail (count drops to 0).
    mutated = re.sub(
        r"(?m)^## \[" + re.escape(version) + r"\] - \d{4}-\d{2}-\d{2}$",
        "## [REMOVED]",
        text,
    )
    assert _heading_count(mutated, version) == 0
