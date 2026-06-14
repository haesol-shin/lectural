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

# --- Stable anchors (the completeness hook checks for these) ----------------
TOC_ANCHOR = "## 목차"
COVERAGE_ANCHOR = "## 커버리지 요약"
SECTION_PREFIX = "## 섹션"
ENRICH_MARKER = "<!-- lectural:baseline -->"

NOTES_ENRICH_MARKER = "<!-- lectural:notes -->"
NOTES_UNENRICHED_MARKER = "<!-- 미보강 -->"
NOTES_TAKEAWAY_ANCHOR = "## 한눈에 요약"
NOTES_TOC_ANCHOR = "## 목차"
NOTES_FLOW_ANCHOR = "## 강의 흐름"
NOTES_CONCEPTS_ANCHOR = "## 핵심 개념·이론"
NOTES_DETAIL_ANCHOR = "## 상세 노트"
NOTES_QUESTIONS_ANCHOR = "## 복습 질문"
NOTES_COVERAGE_ANCHOR = "## 정리 커버리지"
ANCHOR_ID_PATTERN = r"t\d{6}(?:-\d+)?"


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


def _whole_seconds(sec: float) -> int:
    return max(int(round(sec)), 0)


def _video_id(video: dict) -> str | None:
    video_id = str(video.get("video_id") or "").strip()
    if video_id:
        return video_id
    url = str(video.get("url") or "").strip()
    if not url:
        return None
    from .acquisition import extract_video_id

    return extract_video_id(url)


def _citation_deeplink(video: dict, sec: float, anchor_id: str) -> str:
    stamp = format_timestamp(sec)
    citation = f"[{stamp}](transcript.md#{anchor_id})"
    video_id = _video_id(video)
    if video_id:
        citation += f" ([영상](https://youtu.be/{video_id}?t={_whole_seconds(sec)}))"
    return citation


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

    shown, buckets = _renderable_section_hints(segments, hints)
    anchor_ids = build_transcript_anchor_ids(segments)
    anchors_by_segment = {id(segment): anchor_id for segment, anchor_id in zip(segments, anchor_ids)}
    segment_rows = list(zip(segments, anchor_ids))

    out: list[str] = [NOTES_ENRICH_MARKER, f"# {title} — 학습 정리", ""]

    out += [
        NOTES_TAKEAWAY_ANCHOR,
        NOTES_UNENRICHED_MARKER,
        "- 미보강: 강의 전체의 핵심 메시지를 2~3문장으로 정리하세요.",
        "- 미보강: 학습자가 먼저 기억해야 할 흐름과 용어를 표시하세요.",
        "",
        NOTES_TOC_ANCHOR,
    ]
    for section_no, h in enumerate(shown, start=1):
        out.append(
            f"- [{format_timestamp(float(h.get('t', 0.0)))} · "
            f"{_safe_title(h.get('title', ''))}](#sec-{section_no})"
        )
    out += [
        "",
        NOTES_FLOW_ANCHOR,
        NOTES_UNENRICHED_MARKER,
        "- 미보강: 목차의 이동 링크를 따라 강의 전개를 서술하세요.",
        "- 미보강: 도입, 전개, 마무리의 논리적 연결을 보강하세요.",
        "",
        NOTES_CONCEPTS_ANCHOR,
        NOTES_UNENRICHED_MARKER,
    ]
    for s, anchor_id in segment_rows:
        sec = float(s.get("t", 0.0))
        out.append(f"- {s.get('text', '').strip()} {_citation_deeplink(video, sec, anchor_id)}")
    out += ["", NOTES_DETAIL_ANCHOR]

    for section_no, h in enumerate(shown, start=1):
        body = buckets.get(h["index"], [])
        heading_segment = body[0] if body else None
        heading_sec = float(heading_segment.get("t", h.get("t", 0.0))) if heading_segment else float(h.get("t", 0.0))
        out.append(f'<a id="sec-{section_no}"></a>')
        title_text = _safe_title(h.get('title', ''))
        if heading_segment:
            heading_anchor = anchors_by_segment[id(heading_segment)]
            out.append(f"### [{format_timestamp(heading_sec)}](transcript.md#{heading_anchor}) {title_text}")
        else:
            out.append(f"### [{format_timestamp(heading_sec)}] {title_text}")
        if h.get("frame"):
            out.append(f"![슬라이드 {section_no}]({h['frame']})")
        for s in body:
            sec = float(s.get("t", 0.0))
            anchor_id = anchors_by_segment[id(s)]
            out.append(f"- {s.get('text', '').strip()} {_citation_deeplink(video, sec, anchor_id)}")
        out.append("")

    out += [
        NOTES_QUESTIONS_ANCHOR,
        NOTES_UNENRICHED_MARKER,
    ]
    question_sources = segment_rows[:3]
    if question_sources:
        while len(question_sources) < 3:
            question_sources.append(question_sources[-1])
        for i, (s, anchor_id) in enumerate(question_sources[:3], start=1):
            sec = float(s.get("t", 0.0))
            out.append(f"- 미보강 질문 {i}: 이 대목에서 확인해야 할 핵심은 무엇인가요? {_citation_deeplink(video, sec, anchor_id)}")
    else:
        for i in range(1, 4):
            out.append(f"- 미보강 질문 {i}: 이 대목에서 확인해야 할 핵심은 무엇인가요?")

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
