#!/usr/bin/env python3
"""LecturAL completeness gate — a Claude Code Stop hook.

Blocks "done" (exit 2) until every LecturAL run produced this session is
complete. For each run recorded in the run-state file it checks:
  (a) coverage.json overall_pass (speech-gap + scene coverage + artifacts)
  (b) notes.md carries the notes marker and all required section anchors
  (c) notes.md links at least one slide image when frames/*.png exists

When no run-state file exists, the current turn was not a LecturAL run and the
hook is a NO-OP (exit 0). Cross-platform: invoked via `python`/`py -3`; the
script resolves the repo root itself so `import lectural` works.
"""

from __future__ import annotations

import json
import os
import re
import sys

# Make `import lectural` work regardless of where the hook is launched from.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Notes anchors: import from the package, else fall back to literals. This MUST
# NOT affect run-state reading (a completeness gate must not fail open).
try:
    from lectural.synthesis import (
        NOTES_CONCEPTS_ANCHOR,
        NOTES_COVERAGE_ANCHOR,
        NOTES_DETAIL_ANCHOR,
        NOTES_ENRICH_MARKER,
        NOTES_FLOW_ANCHOR,
        NOTES_QUESTIONS_ANCHOR,
        NOTES_TAKEAWAY_ANCHOR,
        NOTES_TOC_ANCHOR,
    )
except Exception:  # noqa: BLE001
    NOTES_ENRICH_MARKER = "<!-- lectural:notes -->"
    NOTES_TAKEAWAY_ANCHOR = "## 한눈에 요약"
    NOTES_TOC_ANCHOR = "## 목차"
    NOTES_FLOW_ANCHOR = "## 강의 흐름"
    NOTES_CONCEPTS_ANCHOR = "## 핵심 개념·이론"
    NOTES_DETAIL_ANCHOR = "## 상세 노트"
    NOTES_QUESTIONS_ANCHOR = "## 복습 질문"
    NOTES_COVERAGE_ANCHOR = "## 정리 커버리지"

_NOTES_SECTION_ANCHORS = [
    NOTES_TAKEAWAY_ANCHOR,
    NOTES_TOC_ANCHOR,
    NOTES_FLOW_ANCHOR,
    NOTES_CONCEPTS_ANCHOR,
    NOTES_DETAIL_ANCHOR,
    NOTES_QUESTIONS_ANCHOR,
    NOTES_COVERAGE_ANCHOR,
]
_SLIDE_IMAGE_LINK_RE = re.compile(r"!\[[^\]]*\]\([^)]*frames/[^)]*\.png[^)]*\)", re.IGNORECASE)
_DEFAULT_RUNSTATE_FILENAME = ".lectural_runstate.json"



def _read_runstate() -> dict | None:
    """Self-contained run-state reader (no lectural import -> fails closed).

    Returns the parsed run-state dict, or None when the file is absent (the
    turn was not a LecturAL run). A present-but-unreadable file is treated as a
    failure by returning a sentinel that the gate rejects.
    """
    path = os.environ.get("LECTURAL_RUNSTATE") or os.path.join(
        os.getcwd(), _DEFAULT_RUNSTATE_FILENAME
    )
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"runs": [{"status": "failed", "error": f"unreadable run-state: {path}",
                          "output_dir": path}]}


def _resolve_notes_path(run: dict, cov_path: str) -> str:
    if run.get("notes_md"):
        return run["notes_md"]
    output_dir = run.get("output_dir")
    if output_dir:
        return os.path.join(output_dir, "notes.md")
    if cov_path:
        return os.path.join(os.path.dirname(cov_path), "notes.md")
    return ""


def _has_frame_png(run: dict, notes_path: str) -> bool:
    roots: list[str] = []
    for root in (
        run.get("output_dir"),
        os.path.dirname(notes_path) if notes_path else "",
    ):
        if root and root not in roots:
            roots.append(root)

    for root in roots:
        frames_dir = os.path.join(root, "frames")
        try:
            if os.path.isdir(frames_dir) and any(
                name.lower().endswith(".png") for name in os.listdir(frames_dir)
            ):
                return True
        except OSError:
            continue
    return False


def _validate_notes(run: dict, cov_path: str) -> list[str]:
    notes_path = _resolve_notes_path(run, cov_path)
    if not os.path.isfile(notes_path):
        return [f"notes.md 없음: {notes_path or 'notes_md/output_dir/coverage sibling 없음'}"]

    try:
        text = open(notes_path, encoding="utf-8").read()
    except OSError as exc:
        return [f"notes.md 읽기 실패: {exc}"]

    problems: list[str] = []
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if first_line != NOTES_ENRICH_MARKER:
        problems.append("notes.md: NOTES_ENRICH_MARKER line1 누락")
    for anchor in _NOTES_SECTION_ANCHORS:
        if anchor not in text:
            problems.append(f"notes.md: 필수 섹션 앵커 누락: {anchor}")
    if _has_frame_png(run, notes_path) and not _SLIDE_IMAGE_LINK_RE.search(text):
        problems.append("notes.md: frames/ 슬라이드 이미지 링크 누락(frames png 존재)")
    return problems



def _validate_run(run: dict) -> list[str]:
    problems: list[str] = []
    status = run.get("status")
    if status == "failed":
        return [f"처리 실패한 영상: {run.get('error') or run.get('url') or run.get('output_dir')}"]
    if status == "pending":
        return [f"처리되지 않은 영상(pending): {run.get('url') or run.get('output_dir')}"]
    cov_path = run.get("coverage_json") or ""
    if not os.path.isfile(cov_path):
        return [f"coverage.json 없음: {cov_path}"]
    try:
        cov = json.loads(open(cov_path, encoding="utf-8").read())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"coverage.json 읽기 실패: {exc}"]
    if not cov.get("overall_pass"):
        gap = cov.get("gap_check", {})
        scene = cov.get("scene_coverage", {})
        arts = cov.get("artifacts", {})
        if not gap.get("pass"):
            problems.append(
                f"대사 공백 초과: {gap.get('max_untranscribed_speech_gap_sec')}s "
                f"> {gap.get('threshold_sec')}s"
            )
        if not scene.get("pass"):
            problems.append(
                f"장면 미커버 bin {scene.get('uncovered_speech_bins')} / "
                f"슬라이드 텍스트 {scene.get('slide_frames_with_text')}/{scene.get('slide_frames_total')}"
            )
        if not arts.get("pass"):
            problems.append("산출물 누락/빈 파일")
    problems += _validate_notes(run, cov_path)
    return problems


def main() -> int:
    # Drain stdin (Claude passes hook JSON); we don't need it.
    try:
        sys.stdin.read()
    except Exception:  # noqa: BLE001
        pass

    state = _read_runstate()
    if state is None or not state.get("runs"):
        # No run-state file (not a LecturAL run) or zero registered runs -> no-op.
        return 0

    all_problems: list[str] = []
    for run in state["runs"]:
        probs = _validate_run(run)
        if probs:
            label = run.get("output_dir") or run.get("url") or f"run #{run.get('index')}"
            all_problems.append(f"[{label}]")
            all_problems.extend(f"  - {p}" for p in probs)

    if all_problems:
        print("LecturAL 완전성 게이트 실패 — 아직 '완료'할 수 없습니다:", file=sys.stderr)
        print("\n".join(all_problems), file=sys.stderr)
        return 2
    print(f"LecturAL 완전성 게이트 통과: {len(state['runs'])}개 run 모두 완전.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
