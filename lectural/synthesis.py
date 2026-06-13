"""Deterministic synthesis (Option A-prime): build the study-note artifacts.

The core writes ALL artifacts with NO LLM (token-zero):
  - synthesis_input.json : compact, deduped handoff for OPTIONAL host-agent
                           enrichment (text only, no images).
  - transcript.md        : raw timestamped transcript (every utterance).
  - summary.md           : a deterministic BASELINE structured summary with the
                           required anchors (TOC, coverage header, per-section
                           timestamp + slide links). A host agent MAY later
                           enrich the prose but MUST preserve these anchors.

The renderers are pure and unit-tested for anchor presence (AC-7, AC-8, AC-12).
"""

from __future__ import annotations

import json

from .config import SCHEMA_VERSION

# --- Stable anchors (the completeness hook checks for these) ----------------
TOC_ANCHOR = "## 목차"
COVERAGE_ANCHOR = "## 커버리지 요약"
SECTION_PREFIX = "## 섹션"
ENRICH_MARKER = "<!-- lectural:baseline -->"


def format_timestamp(sec: float) -> str:
    """Pure: seconds -> HH:MM:SS."""
    sec = max(int(round(sec)), 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _first_line(text: str, fallback: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:80]
    return fallback

def _safe_title(text: str) -> str:
    """Pure: make a title safe inside markdown link text / headings.

    Strips newlines and neutralizes characters that would break a
    `[text](#anchor)` link or a heading (``[`` ``]`` ``|``).
    """
    t = " ".join((text or "").split())
    return t.replace("[", "(").replace("]", ")").replace("|", "/")


def build_section_hints(slides: list[dict], duration: float) -> list[dict]:
    """Pure: derive section windows from slide timestamps.

    Each slide opens a section running until the next slide (last -> duration).
    With no slides, a single whole-video section is produced.
    """
    if not slides:
        return [{"index": 0, "t": 0.0, "win_start": 0.0, "t_end": duration,
                 "title": "전체", "frame": None}]
    ordered = sorted(slides, key=lambda s: s.get("t", 0.0))
    hints: list[dict] = []
    # If the first slide starts after 0, prepend an intro section so speech
    # before the first slide is never dropped from the summary (capture-ALL).
    if float(ordered[0].get("t", 0.0)) > 0.0:
        hints.append({"index": 0, "t": 0.0, "win_start": 0.0,
                      "t_end": float(ordered[0].get("t", 0.0)),
                      "title": "도입", "frame": None})
    base = len(hints)
    for i, sl in enumerate(ordered):
        t = float(sl.get("t", 0.0))
        t_end = float(ordered[i + 1]["t"]) if i + 1 < len(ordered) else duration
        hints.append(
            {
                "index": base + i,
                "t": t,
                "win_start": t,
                "t_end": t_end,
                "title": _first_line(sl.get("ocr_text", ""), f"슬라이드 {i + 1}"),
                "frame": sl.get("frame"),
            }
        )
    return hints


def build_synthesis_input(
    video: dict,
    segments: list[dict],
    slides: list[dict],
) -> dict:
    """Pure: assemble the compact host-agent handoff JSON."""
    duration = float(video.get("duration_sec", 0.0))
    return {
        "schema_version": SCHEMA_VERSION,
        "video": video,
        "transcript_segments": segments,
        "slides": slides,
        "section_hints": build_section_hints(slides, duration),
    }


def assign_segments_to_sections(segments: list[dict], hints: list[dict]) -> dict[int, list[dict]]:
    """Pure: assign EVERY segment to exactly one section (no drops).

    Each segment is owned by the last section whose win_start <= t. Segments
    before the first section (t < 0) fall to the first section; segments past
    the last win_start (incl. t == duration) fall to the last section. The
    union of all buckets equals the input, so summary.md drops nothing.
    """
    if not hints:
        return {}
    ordered = sorted(hints, key=lambda h: h.get("win_start", h.get("t", 0.0)))
    buckets: dict[int, list[dict]] = {h["index"]: [] for h in hints}
    for s in segments:
        t = float(s.get("t", 0.0))
        owner = ordered[0]
        for h in ordered:
            if h.get("win_start", h.get("t", 0.0)) <= t:
                owner = h
            else:
                break
        buckets[owner["index"]].append(s)
    return buckets


def render_transcript_md(video: dict, segments: list[dict]) -> str:
    """Pure: raw timestamped transcript covering every utterance (AC-7)."""
    title = video.get("title", "Untitled")
    src = video.get("source", "unknown")
    lines = [f"# {title} — 전체 전사본 (raw)", "", f"- 소스: {src}", ""]
    for s in segments:
        lines.append(f"[{format_timestamp(float(s.get('t', 0.0)))}] {s.get('text', '').strip()}")
    return "\n".join(lines).rstrip() + "\n"


def render_summary_md(synthesis_input: dict, coverage: dict) -> str:
    """Pure: deterministic baseline summary with required anchors (AC-8)."""
    video = synthesis_input.get("video", {})
    segments = synthesis_input.get("transcript_segments", [])
    hints = synthesis_input.get("section_hints", [])
    title = video.get("title", "Untitled")

    out: list[str] = [ENRICH_MARKER, f"# {title} — 학습 정리", ""]

    # Coverage header (anchor)
    gap = coverage.get("gap_check", {})
    scene = coverage.get("scene_coverage", {})
    arts = coverage.get("artifacts", {})
    out += [
        COVERAGE_ANCHOR,
        f"- 전체 길이: {format_timestamp(float(coverage.get('duration_sec', 0.0)))}",
        f"- 대사 공백: 최대 {gap.get('max_untranscribed_speech_gap_sec', 0)}s "
        f"(임계 {gap.get('threshold_sec', 0)}s) → {'통과' if gap.get('pass') else '미달'}",
        f"- 장면 커버리지: 발화 구간 {len(scene.get('speech_bins', []))}개 중 "
        f"미커버 {len(scene.get('uncovered_speech_bins', []))}개 → {'통과' if scene.get('pass') else '미달'}",
        f"- 슬라이드: {scene.get('slide_frames_with_text', 0)}/{scene.get('slide_frames_total', 0)} (OCR 텍스트 보유)",
        f"- OCR 엔진: {coverage.get('ocr_engine', 'none')}",
        f"- 산출물: transcript={'O' if arts.get('transcript_nonempty') else 'X'}, "
        f"summary={'O' if arts.get('summary_nonempty') else 'X'}",
        "",
    ]

    # Determine which sections to render. Skip a synthetic intro section
    # (no frame) that ended up with no pre-slide speech, but never skip the
    # only section. Every segment is assigned to exactly one section (no drops).
    buckets = assign_segments_to_sections(segments, hints)

    def _renderable(h: dict) -> bool:
        if len(hints) == 1:
            return True
        return bool(h.get("frame")) or bool(buckets.get(h["index"]))

    shown = [h for h in hints if _renderable(h)]

    # Table of contents (anchor) with intra-doc links
    out += [TOC_ANCHOR]
    for h in shown:
        out.append(
            f"- [{format_timestamp(h['t'])} · {_safe_title(h['title'])}](#sec-{h['index']})"
        )
    out.append("")

    # Sections: each has a timestamp anchor + slide link (when present) + body.
    for h in shown:
        out.append(f'<a id="sec-{h["index"]}"></a>')
        out.append(f"{SECTION_PREFIX} {h['index'] + 1}. [{format_timestamp(h['t'])}] {_safe_title(h['title'])}")
        if h.get("frame"):
            out.append(f"![슬라이드 {h['index'] + 1}]({h['frame']})")
        body = buckets.get(h["index"], [])
        if body:
            out.append("")
            for s in body:
                out.append(f"- [{format_timestamp(float(s.get('t', 0.0)))}] {s.get('text', '').strip()}")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def write_synthesis_input(synthesis_input: dict, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(synthesis_input, fh, ensure_ascii=False, indent=2)
    return path


def write_text(text: str, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path
