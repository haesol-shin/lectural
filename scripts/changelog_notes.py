#!/usr/bin/env python3
"""Extract a single version's release notes from CHANGELOG.md.

Used by .github/workflows/release.yml to build the GitHub Release body from the
curated Keep a Changelog section, and unit-tested in tests/test_changelog_notes.py.

Usage:
    python scripts/changelog_notes.py <version> [changelog_path]

Prints the body of the `## [<version>] - <date>` section to stdout, excluding the
section heading itself, the next `## [` heading, and the trailing `[...]: <url>`
link-reference block. Leading and trailing blank lines are trimmed. If the
version has no section, nothing is printed (empty output) so a `test -s` guard in
CI fails safely.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_LINK_REF_RE = re.compile(r"^\[[^\]]+\]:\s")


def extract_notes(changelog_text: str, version: str) -> str:
    """Return the trimmed body for `## [<version>]`, or "" if absent."""
    header_prefix = f"## [{version}]"
    collected: list[str] = []
    in_section = False
    for line in changelog_text.splitlines():
        if not in_section:
            if line.startswith(header_prefix):
                in_section = True
            continue
        if line.startswith("## ["):
            break
        if _LINK_REF_RE.match(line):
            break
        collected.append(line)
    while collected and not collected[0].strip():
        collected.pop(0)
    while collected and not collected[-1].strip():
        collected.pop()
    return "\n".join(collected)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or not argv[1].strip():
        print("usage: changelog_notes.py <version> [changelog_path]", file=sys.stderr)
        return 2
    version = argv[1].strip()
    if len(argv) >= 3:
        changelog_path = Path(argv[2])
    else:
        changelog_path = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    text = changelog_path.read_text(encoding="utf-8")
    notes = extract_notes(text, version)
    if notes:
        sys.stdout.write(notes + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
