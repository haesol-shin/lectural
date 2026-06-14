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


def _header_re(version: str) -> re.Pattern[str]:
    # Exact heading identity: `## [<version>]` followed by whitespace/EOL so a
    # request for 0.1.1 never matches 0.1.10.
    return re.compile(r"^## \[" + re.escape(version) + r"\](?:\s|$)")


def extract_notes(changelog_text: str, version: str) -> str:
    """Return the trimmed body for `## [<version>]`, or "" if absent."""
    header_re = _header_re(version)
    collected: list[str] = []
    in_section = False
    for line in changelog_text.splitlines():
        if not in_section:
            if header_re.match(line):
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


def extract_link(changelog_text: str, version: str) -> str:
    """Return the `[version]: <url>` link-reference URL, or "" if absent."""
    match = re.search(r"(?m)^\[" + re.escape(version) + r"\]: (\S+)$", changelog_text)
    return match.group(1) if match else ""


def main(argv: list[str]) -> int:
    want_link = "--link" in argv[1:]
    args = [a for a in argv[1:] if a != "--link"]
    if not args or not args[0].strip():
        print("usage: changelog_notes.py <version> [changelog_path] [--link]", file=sys.stderr)
        return 2
    version = args[0].strip()
    if len(args) >= 2:
        changelog_path = Path(args[1])
    else:
        changelog_path = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    text = changelog_path.read_text(encoding="utf-8")
    if want_link:
        link = extract_link(text, version)
        if link:
            sys.stdout.write(link + "\n")
        return 0
    notes = extract_notes(text, version)
    if notes:
        sys.stdout.write(notes + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
