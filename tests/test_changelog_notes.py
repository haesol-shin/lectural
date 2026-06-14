"""Unit tests for the release-notes extractor (scripts/changelog_notes.py)."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import changelog_notes  # noqa: E402

SAMPLE = """\
# Changelog

## [Unreleased]

## [0.2.0] - 2026-07-01

### Added
- Second release feature.

## [0.1.0] - 2026-06-14

### Added
- First release pipeline.
- Second bullet.

[Unreleased]: https://github.com/haesol-shin/lectural/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/haesol-shin/lectural/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/haesol-shin/lectural/releases/tag/v0.1.0
"""


def test_existing_middle_version_excludes_next_header_and_links():
    notes = changelog_notes.extract_notes(SAMPLE, "0.2.0")
    assert notes == "### Added\n- Second release feature."
    assert "## [0.1.0]" not in notes
    assert "## [" not in notes
    assert "compare/" not in notes
    assert not notes.startswith("\n")


def test_last_version_excludes_trailing_link_reference_block():
    notes = changelog_notes.extract_notes(SAMPLE, "0.1.0")
    assert notes == "### Added\n- First release pipeline.\n- Second bullet."
    # The trailing [Unreleased]:/[0.1.0]: link block must not leak in.
    assert "compare/" not in notes
    assert "releases/tag" not in notes
    assert "]:" not in notes


def test_missing_version_returns_empty():
    assert changelog_notes.extract_notes(SAMPLE, "9.9.9") == ""


def test_leading_blank_lines_after_heading_are_trimmed():
    text = "## [1.0.0] - 2026-01-01\n\n\n### Added\n- Body.\n"
    notes = changelog_notes.extract_notes(text, "1.0.0")
    assert notes == "### Added\n- Body."
    assert not notes.startswith("\n")


def test_cli_writes_nothing_for_missing_version(tmp_path, capsys):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(SAMPLE, encoding="utf-8")
    rc = changelog_notes.main(["changelog_notes.py", "9.9.9", str(changelog)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""


def test_cli_emits_section_for_existing_version(tmp_path, capsys):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(SAMPLE, encoding="utf-8")
    rc = changelog_notes.main(["changelog_notes.py", "0.1.0", str(changelog)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == "### Added\n- First release pipeline.\n- Second bullet.\n"
