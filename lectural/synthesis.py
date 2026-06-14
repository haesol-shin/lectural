"""Deterministic synthesis (Option A-prime): build the study-note artifacts.

The core writes ALL artifacts with NO LLM (token-zero):
  - synthesis_input.json : compact, deduped handoff for OPTIONAL host-agent
                           enrichment (text only, no images).
  - transcript.md        : raw timestamped transcript (every utterance).
  - notes.md             : deterministic 7-section skeleton with grounding.

The renderers are pure and unit-tested for anchor presence (AC-7, AC-8, AC-12).
"""

from __future__ import annotations

import json

from .config import SCHEMA_VERSION

NOTES_ENRICH_MARKER = "<!-- lectural:notes -->"
NOTES_UNENRICHED_MARKER = "<!-- 미보강 -->"
NOTES_INTRO_TITLE = "도입"
NOTES_INTRO_MARKER = "<!-- lectural:intro -->"
NOTES_TAKEAWAY_ANCHOR = "## 3줄 요약"
NOTES_TOC_ANCHOR = "## 목차"
NOTES_FLOW_ANCHOR = "## 흐름"
NOTES_CONCEPTS_ANCHOR = "## 핵심 개념·이론"
NOTES_DETAIL_ANCHOR = "## 정리 노트"
NOTES_QUESTIONS_ANCHOR = "## 복습 질문"
NOTES_COVERAGE_ANCHOR = "## 정리 커버리지"
ANCHOR_ID_PATTERN = r"t\d{6}(?:-\d+)?"
NOTES_SLIDE_IMG_WIDTH = 480


def format_timestamp(sec: float) -> str:
    """Pure: seconds -> HH:MM:SS."""
    sec = max(int(round(sec)), 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_transcript_anchor_ids(segments: list[dict]) -> list[str]:
    """Pure: ordered transcript cues -> unique ``tHHMMSS`` anchor ids."""
    seen: dict[str, int] = {}
    ids: list[str] = []
    for s in segments:
        base = f"t{format_timestamp(float(s.get('t', 0.0))).replace(':', '')}"
        seen[base] = seen.get(base, 0) + 1
        ids.append(base if seen[base] == 1 else f"{base}-{seen[base]}")
    return ids




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
    # before the first slide is never dropped from the notes (capture-ALL).
    if float(ordered[0].get("t", 0.0)) > 0.0:
        hints.append({"index": 0, "t": 0.0, "win_start": 0.0,
                      "t_end": float(ordered[0].get("t", 0.0)),
                      "title": NOTES_INTRO_TITLE, "frame": None})
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
    union of all buckets equals the input, so notes.md drops nothing.
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
    for s, anchor_id in zip(segments, build_transcript_anchor_ids(segments)):
        lines.append(
            f'<a id="{anchor_id}"></a> '
            f"[{format_timestamp(float(s.get('t', 0.0)))}] {s.get('text', '').strip()}"
        )
    return "\n".join(lines).rstrip() + "\n"

def _renderable_section_hints(segments: list[dict], hints: list[dict]) -> tuple[list[dict], dict[int, list[dict]]]:
    """Pure: section list + transcript buckets used by the notes renderer."""
    buckets = assign_segments_to_sections(segments, hints)

    def _renderable(h: dict) -> bool:
        if len(hints) == 1:
            return True
        return bool(h.get("frame")) or bool(buckets.get(h["index"]))

    return [h for h in hints if _renderable(h)], buckets





def _coverage_footer_lines(coverage: dict) -> list[str]:
    gap = coverage.get("gap_check", {})
    scene = coverage.get("scene_coverage", {})
    arts = coverage.get("artifacts", {})
    return [
        f"- 전체 길이: {format_timestamp(float(coverage.get('duration_sec', 0.0)))}",
        f"- 대사 공백: 최대 {gap.get('max_untranscribed_speech_gap_sec', 0)}s "
        f"(임계 {gap.get('threshold_sec', 0)}s) → {'통과' if gap.get('pass') else '미달'}",
        f"- 장면 커버리지: 발화 구간 {len(scene.get('speech_bins', []))}개 중 "
        f"미커버 {len(scene.get('uncovered_speech_bins', []))}개 → {'통과' if scene.get('pass') else '미달'}",
        f"- 슬라이드: {scene.get('slide_frames_with_text', 0)}/{scene.get('slide_frames_total', 0)} (OCR 텍스트 보유)",
        f"- OCR 엔진: {coverage.get('ocr_engine', 'none')}",
        f"- 산출물: transcript={'O' if arts.get('transcript_nonempty') else 'X'}, "
        f"notes={'O' if arts.get('notes_nonempty') else 'X'}",
    ]


def render_notes_md(synthesis_input: dict, coverage: dict) -> str:
    """Pure: deterministic 7-section notes skeleton for host-agent enrichment."""
    video = synthesis_input.get("video", {})
    segments = synthesis_input.get("transcript_segments", [])
    hints = synthesis_input.get("section_hints", [])
    title = video.get("title", "Untitled")

    shown, _buckets = _renderable_section_hints(segments, hints)

    out: list[str] = [NOTES_ENRICH_MARKER, f"# {title} — 학습 정리", ""]

    out += [
        NOTES_TAKEAWAY_ANCHOR,
        NOTES_UNENRICHED_MARKER,
        "- 미보강: 핵심 메시지 한 줄.",
        "- 미보강: 핵심 메시지 한 줄.",
        "- 미보강: 핵심 메시지 한 줄.",
        "",
        NOTES_TOC_ANCHOR,
    ]
    for section_no, h in enumerate(shown, start=1):
        out.append(f"- [{_safe_title(h.get('title', ''))}](#sec-{section_no})")
    out += [
        "",
        NOTES_FLOW_ANCHOR,
        NOTES_UNENRICHED_MARKER,
        "- 미보강: 도입→전개→마무리 흐름을 짧게 정리하세요.",
        "- 미보강: 핵심 전개를 한 줄씩 정리하세요.",
        "",
        NOTES_CONCEPTS_ANCHOR,
        NOTES_UNENRICHED_MARKER,
        "- 미보강: 핵심 용어 → 정의를 영상 딥링크와 함께 정리하세요.",
        "",
        NOTES_DETAIL_ANCHOR,
        NOTES_UNENRICHED_MARKER,
    ]

    for section_no, h in enumerate(shown, start=1):
        out.append(f'<a id="sec-{section_no}"></a>')
        out.append(f"### {_safe_title(h.get('title', ''))}")
        if h.get("frame"):
            out.append("")
            out.append(
                f'<img src="{h["frame"]}" alt="슬라이드 {section_no}" width="{NOTES_SLIDE_IMG_WIDTH}">'
            )
            out.append("")
        elif h.get("title") == NOTES_INTRO_TITLE:
            out.append(NOTES_INTRO_MARKER)
        out.append("- 미보강: 이 슬라이드 핵심을 요약 글머리표로 정리하세요.")
        out.append("")

    out += [
        NOTES_QUESTIONS_ANCHOR,
        NOTES_UNENRICHED_MARKER,
        "- 미보강 질문: 핵심 확인 질문과 답을 작성하세요.",
    ]

    out += ["", NOTES_COVERAGE_ANCHOR, *_coverage_footer_lines(coverage), ""]
    return "\n".join(out).rstrip() + "\n"

def write_synthesis_input(synthesis_input: dict, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(synthesis_input, fh, ensure_ascii=False, indent=2)
    return path


def write_text(text: str, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path
