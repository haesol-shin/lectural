"""Active-run pointer so the completeness hook knows what to validate.

A single CLI invocation (one URL or a sequential batch) writes a fresh run
state file listing every output directory it produced this session. The Stop
hook reads this file and validates ALL listed runs (AC-2). When the file is
absent, the current agent turn was not a LecturAL run and the hook is a no-op.
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


def start_session(path: str | None = None) -> dict:
    """Begin a fresh batch session, replacing any previous run-state file."""
    path = path or runstate_path()
    state = {
        "session_id": uuid.uuid4().hex,
        "started_at": time.time(),
        "tool": "lectural",
        "runs": [],
    }
    _write(path, state)
    return state


def record_run(output_dir: str, coverage_path: str, summary_path: str, path: str | None = None) -> dict:
    """Append a completed run's artifact locations to the run-state file."""
    path = path or runstate_path()
    state = read_state(path) or start_session(path)
    state["runs"].append(
        {
            "output_dir": output_dir,
            "coverage_json": coverage_path,
            "summary_md": summary_path,
            "recorded_at": time.time(),
        }
    )
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
