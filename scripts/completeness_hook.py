#!/usr/bin/env python3
"""LecturAL completeness gate — a Claude Code Stop hook.

Blocks "done" (exit 2) until every LecturAL run produced this session is
complete. For each run recorded in the run-state file it checks:
  (a) coverage.json overall_pass (speech-gap + scene coverage + artifacts)
  (b) summary.md carries summary-only anchors (baseline marker + coverage header)
  (c) outline.md carries navigation anchors (TOC, timestamps, transcript bullets, slide links)

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

# Anchors: import from the package, else fall back to literals. This MUST NOT
# affect run-state reading (a completeness gate must not fail open).
try:
    from lectural.synthesis import COVERAGE_ANCHOR, ENRICH_MARKER, TOC_ANCHOR
except Exception:  # noqa: BLE001
    ENRICH_MARKER = "<!-- lectural:baseline -->"
    COVERAGE_ANCHOR = "## 커버리지 요약"
    TOC_ANCHOR = "## 목차"

_DEFAULT_RUNSTATE_FILENAME = ".lectural_runstate.json"
_TIMESTAMP_RE = re.compile(r"\[\d{2}:\d{2}:\d{2}\]")
_TRANSCRIPT_BULLET_RE = re.compile(r"(?m)^\s*-\s+\[\d{2}:\d{2}:\d{2}\]\s+\S.*$")


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


def _validate_summary_anchors(summary_path: str) -> list[str]:
    problems: list[str] = []
    if not os.path.isfile(summary_path):
        return [f"summary.md 없음: {summary_path}"]
    text = open(summary_path, encoding="utf-8").read()
    if ENRICH_MARKER not in text:
        problems.append("summary.md: ENRICH_MARKER 누락")
    if COVERAGE_ANCHOR not in text:
        problems.append("summary.md: 커버리지 요약 헤더 누락")
    return problems


def _outline_candidates(run: dict, summary_path: str) -> list[str]:
    if run.get("outline_md"):
        return [run["outline_md"]]

    candidates: list[str] = []
    output_dir = run.get("output_dir")
    if output_dir:
        candidates.append(os.path.join(output_dir, "outline.md"))
    if summary_path:
        candidates.append(os.path.join(os.path.dirname(summary_path), "outline.md"))

    unique: list[str] = []
    for path in candidates:
        if path and path not in unique:
            unique.append(path)
    return unique


def _has_frame_png(run: dict, summary_path: str, outline_path: str) -> bool:
    roots: list[str] = []
    for root in (
        run.get("output_dir"),
        os.path.dirname(summary_path) if summary_path else "",
        os.path.dirname(outline_path) if outline_path else "",
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


def _validate_outline_anchors(run: dict, summary_path: str) -> list[str]:
    candidates = _outline_candidates(run, summary_path)
    outline_path = next((path for path in candidates if os.path.isfile(path)), "")

    if not outline_path:
        expected = " 또는 ".join(candidates) if candidates else "outline_md/output_dir 없음"
        return [f"outline.md 없음: {expected}"]

    text = open(outline_path, encoding="utf-8").read()
    problems: list[str] = []
    if TOC_ANCHOR not in text:
        problems.append("outline.md: 목차(TOC_ANCHOR) 누락")
    if not _TIMESTAMP_RE.search(text):
        problems.append("outline.md: [HH:MM:SS] 타임스탬프 누락")
    if not _TRANSCRIPT_BULLET_RE.search(text):
        problems.append("outline.md: [HH:MM:SS] transcript bullet 누락")
    if _has_frame_png(run, summary_path, outline_path) and "frames/" not in text:
        problems.append("outline.md: frames/ 슬라이드 링크 누락(frames png 존재)")
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
    summary_path = run.get("summary_md", "")
    problems += _validate_summary_anchors(summary_path)
    problems += _validate_outline_anchors(run, summary_path)
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
