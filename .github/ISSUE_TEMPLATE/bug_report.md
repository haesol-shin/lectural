---
name: Bug report
about: Report a problem with LecturAL
title: "[bug] "
labels: bug
---

## Summary

A clear, one-line description of the bug.

## Steps to reproduce

1. Command run (for example, `/lectural:notes <url>` or `lectural "<url>"`)
2. Input URL or fixture type:
3. What happened next:

## Expected behavior

What should have happened?

## Actual behavior

What happened instead? Include the exit code when available.

## Environment

- OS:
- Python / uv version:
- `lectural doctor` result:
- ffmpeg / yt-dlp on PATH? (yes/no)

## Validation

- [ ] I ran `uv run --with pytest --with numpy pytest -q` when the bug affects offline behavior.
- [ ] I ran `lectural doctor` or included why runtime checks are unavailable.

## Logs / output

Paste the relevant CLI output, exit code, hook message, or traceback.
