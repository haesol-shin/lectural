"""Deterministic synthesis (Option A-prime): build the study-note artifacts.

The core writes ALL artifacts with NO LLM (token-zero):
  - synthesis_input.json : compact, deduped handoff for OPTIONAL host-agent
                           enrichment (text only, no images).
  - transcript.md        : raw timestamped transcript (every utterance).
  - summary.md           : deterministic prose-first baseline summary with
                           required enrichment/coverage anchors.
  - outline.md           : deterministic TOC/section/slide/transcript outline.

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

def _renderable_section_hints(segments: list[dict], hints: list[dict]) -> tuple[list[dict], dict[int, list[dict]]]:
    """Pure: section list + transcript buckets used by summary and outline."""
    buckets = assign_segments_to_sections(segments, hints)

    def _renderable(h: dict) -> bool:
        if len(hints) == 1:
            return True
        return bool(h.get("frame")) or bool(buckets.get(h["index"]))

    return [h for h in hints if _renderable(h)], buckets


def render_outline_md(synthesis_input: dict) -> str:
    """Pure: deterministic outline with TOC, slides, and transcript bullets."""
    video = synthesis_input.get("video", {})
    segments = synthesis_input.get("transcript_segments", [])
    hints = synthesis_input.get("section_hints", [])
    title = video.get("title", "Untitled")

    shown, buckets = _renderable_section_hints(segments, hints)
    out: list[str] = [f"# {title} — 강의 개요", "", TOC_ANCHOR]
    for h in shown:
        out.append(
            f"- [{format_timestamp(h['t'])} · {_safe_title(h['title'])}](#sec-{h['index']})"
        )
    out.append("")

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


def _excerpt(items: list[str], max_items: int = 3, max_chars: int = 220) -> str:
    cleaned = [" ".join(item.split()) for item in items if item and item.strip()]
    text = " / ".join(cleaned[:max_items])
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text

def render_summary_md(synthesis_input: dict, coverage: dict) -> str:
    """Pure: deterministic prose-first baseline summary with required anchors."""
    video = synthesis_input.get("video", {})
    segments = synthesis_input.get("transcript_segments", [])
    hints = synthesis_input.get("section_hints", [])
    title = video.get("title", "Untitled")

    out: list[str] = [ENRICH_MARKER, f"# {title} — 학습 요약", ""]

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
        f"summary={'O' if arts.get('summary_nonempty') else 'X'}, "
        f"outline={'O' if arts.get('outline_nonempty') else 'X'}",
        "",
    ]

    shown, buckets = _renderable_section_hints(segments, hints)
    segment_excerpt = _excerpt([s.get("text", "") for s in segments])
    slide_excerpt = _excerpt([h.get("title", "") for h in shown])
    out += ["## 핵심 요약"]
    if segment_excerpt:
        if slide_excerpt:
            out.append(f"이 강의는 {slide_excerpt} 흐름을 따라가며, 전사에서는 {segment_excerpt} 내용을 중심으로 전개됩니다.")
        else:
            out.append(f"이 강의는 전사 발화 {segment_excerpt} 내용을 중심으로 전개됩니다.")
    else:
        out.append("이 강의는 사용 가능한 전사 발화가 없어 슬라이드와 커버리지 정보만 기준으로 요약되었습니다.")
    out.append("")

    out.append("## 구간별 요약")
    for h in shown:
        body = buckets.get(h["index"], [])
        section_excerpt = _excerpt([s.get("text", "") for s in body], max_items=2, max_chars=180)
        slide_title = _safe_title(h.get("title", ""))
        out.append(f"### 구간 {h['index'] + 1} · {slide_title}")
        if section_excerpt and h.get("frame"):
            out.append(f"{slide_title} 슬라이드를 기준으로 {section_excerpt} 내용을 설명합니다.")
        elif section_excerpt:
            out.append(f"이 구간에서는 {section_excerpt} 내용을 설명합니다.")
        elif h.get("frame"):
            out.append(f"{slide_title} 슬라이드가 제시되지만 이 구간에 배정된 전사 발화는 없습니다.")
        else:
            out.append("이 구간에 배정된 전사 발화와 슬라이드가 없습니다.")
        out.append("")

    out += [
        "## TO-ENRICH",
        "TO-ENRICH: host agent는 위 결정적 요약을 보강할 수 있지만 ENRICH_MARKER와 COVERAGE_ANCHOR는 유지해야 합니다.",
        "",
    ]

    return "\n".join(out).rstrip() + "\n"


def write_synthesis_input(synthesis_input: dict, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(synthesis_input, fh, ensure_ascii=False, indent=2)
    return path


def write_text(text: str, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path
