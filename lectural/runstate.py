"""Active-run pointer so the completeness hook knows what to validate.

A single CLI invocation (one URL or a sequential batch) opens a fresh session
and PRE-REGISTERS every requested URL as a `pending` run. As each video is
processed the entry is updated to `complete` (with artifact paths) or `failed`.

The Stop hook validates EVERY entry, so a failed or never-produced video stays
visible and blocks "done" (it cannot be hidden by aborting early). When the
run-state file is absent, the turn was not a LecturAL run and the hook no-ops.
"""

from __future__ import annotations

import json
import os
import time
import uuid

DEFAULT_RUNSTATE_FILENAME = ".lectural_runstate.json"


def runstate_path() -> str:
    """Resolve the run-state file path (env override -> cwd default)."""
    return os.environ.get("LECTURAL_RUNSTATE") or os.path.join(
        os.getcwd(), DEFAULT_RUNSTATE_FILENAME
    )


def start_session(urls: list[str] | None = None, path: str | None = None) -> dict:
    """Begin a fresh batch session, pre-registering each URL as `pending`."""
    path = path or runstate_path()
    state = {
        "session_id": uuid.uuid4().hex,
        "started_at": time.time(),
        "tool": "lectural",
        "runs": [
            {
                "index": i,
                "url": url,
                "status": "pending",
                "output_dir": None,
                "coverage_json": None,
                "notes_md": None,
            }
            for i, url in enumerate(urls or [])
        ],
    }
    _write(path, state)
    return state


def update_run(
    index: int,
    *,
    status: str,
    output_dir: str | None = None,
    coverage_json: str | None = None,
    notes_md: str | None = None,
    error: str | None = None,
    path: str | None = None,
) -> dict:
    """Update a pre-registered run by index (or append if out of range)."""
    path = path or runstate_path()
    state = read_state(path) or start_session([], path)
    entry = {
        "index": index,
        "status": status,
        "output_dir": output_dir,
        "coverage_json": coverage_json,
        "notes_md": notes_md,
        "error": error,
        "updated_at": time.time(),
    }
    runs = state.setdefault("runs", [])
    for r in runs:
        if r.get("index") == index:
            r.update({k: v for k, v in entry.items() if v is not None or k == "status"})
            break
    else:
        runs.append(entry)
    _write(path, state)
    return state


def read_state(path: str | None = None) -> dict | None:
    path = path or runstate_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _write(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
