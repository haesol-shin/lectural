"""Pure notes.md contract checks shared by coverage and the Stop hook."""

from __future__ import annotations

import re

from .synthesis import (
    ANCHOR_ID_PATTERN,
    NOTES_CONCEPTS_ANCHOR,
    NOTES_COVERAGE_ANCHOR,
    NOTES_DETAIL_ANCHOR,
    NOTES_ENRICH_MARKER,
    NOTES_FLOW_ANCHOR,
    NOTES_QUESTIONS_ANCHOR,
    NOTES_INTRO_MARKER,
    NOTES_TAKEAWAY_ANCHOR,
    NOTES_TOC_ANCHOR,
    NOTES_UNENRICHED_MARKER,
)

NOTES_CONTRACT_VERSION = 1

SECTION_ANCHORS_IN_ORDER = [
    NOTES_TAKEAWAY_ANCHOR,
    NOTES_TOC_ANCHOR,
    NOTES_FLOW_ANCHOR,
    NOTES_CONCEPTS_ANCHOR,
    NOTES_DETAIL_ANCHOR,
    NOTES_QUESTIONS_ANCHOR,
    NOTES_COVERAGE_ANCHOR,
]

_TRANSCRIPT_ANCHOR_RE = re.compile(r'<a\s+id="(' + ANCHOR_ID_PATTERN + r')"></a>')
_YOUTUBE_TIME_RE = re.compile(r"https://youtu\.be/[^\s)]+\?t=(\d+)")
_SLIDE_IMAGE_LINK_RE = re.compile(
    r"(?:!\[[^\]]*\]\([^)]*frames/[^)]*\))|(?:<img[^>]*frames/[^>]*>)", re.IGNORECASE
)


def transcript_anchor_ids(transcript_text: str) -> set[str]:
    """Return all cue anchor ids emitted in transcript.md."""
    return set(_TRANSCRIPT_ANCHOR_RE.findall(transcript_text or ""))


def anchor_seconds(anchor_id: str) -> int:
    """Return whole seconds encoded by ``tHHMMSS[-n]``."""
    base = anchor_id.split("-", 1)[0]
    return int(base[1:3]) * 3600 + int(base[3:5]) * 60 + int(base[5:7])


def _section_block(notes_text: str, anchor: str) -> str:
    """Return the section text from ``anchor`` until the next contract section."""
    start = (notes_text or "").find(anchor)
    if start < 0:
        return ""
    try:
        anchor_index = SECTION_ANCHORS_IN_ORDER.index(anchor)
    except ValueError:
        return ""
    end = len(notes_text)
    for next_anchor in SECTION_ANCHORS_IN_ORDER[anchor_index + 1:]:
        next_pos = notes_text.find(next_anchor, start + len(anchor))
        if next_pos >= 0:
            end = next_pos
            break
    return notes_text[start:end]


def _bullet_lines(block: str) -> list[str]:
    return [line for line in (block or "").splitlines() if line.startswith("- ")]


def _citation_line_problems(line: str, cue_seconds: set[int], section_anchor: str) -> list[str]:
    problems: list[str] = []
    youtube_match = _YOUTUBE_TIME_RE.search(line)
    if not youtube_match:
        problems.append(f"{section_anchor}: 영상 딥링크(https://youtu.be/...?t=초)가 없습니다: {line.strip()}")
        return problems
    video_sec = int(youtube_match.group(1))
    if cue_seconds and min(abs(video_sec - s) for s in cue_seconds) > 1:
        problems.append(f"{section_anchor}: 영상 시각 {video_sec}s가 전사 발화 시점과 1초 넘게 다릅니다")
    return problems


def citation_problems(notes_text: str, transcript_text: str) -> list[str]:
    """Validate YouTube deeplinks on 핵심 개념·이론 bullets and 복습 질문 answers.

    Each cited link must point at a real transcript cue second (within ±1s).
    """
    problems: list[str] = []
    cue_seconds = {anchor_seconds(a) for a in transcript_anchor_ids(transcript_text)}

    for line in _bullet_lines(_section_block(notes_text, NOTES_CONCEPTS_ANCHOR)):
        if line.strip() == NOTES_UNENRICHED_MARKER:
            continue
        problems += _citation_line_problems(line, cue_seconds, NOTES_CONCEPTS_ANCHOR)

    questions_block = _section_block(notes_text, NOTES_QUESTIONS_ANCHOR)
    cited_question_lines = [line for line in questions_block.splitlines() if "youtu.be/" in line]
    for line in cited_question_lines:
        problems += _citation_line_problems(line, cue_seconds, NOTES_QUESTIONS_ANCHOR)
    if len(cited_question_lines) < 3:
        problems.append(f"복습 질문에 영상 딥링크가 3개 이상 필요합니다(현재 {len(cited_question_lines)}개)")
    return problems


def base_structure_problems(notes_text: str) -> list[str]:
    """Validate marker line and seven ordered section anchors only."""
    text = notes_text or ""
    problems: list[str] = []
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if first_line != NOTES_ENRICH_MARKER:
        problems.append("notes.md 첫 줄에 lectural notes 마커가 없습니다")

    last_pos = -1
    for anchor in SECTION_ANCHORS_IN_ORDER:
        pos = text.find(anchor)
        if pos < 0:
            problems.append(f"notes.md 필수 섹션이 없습니다: {anchor}")
            continue
        if pos < last_pos:
            problems.append(f"notes.md 섹션 순서가 올바르지 않습니다: {anchor}")
        last_pos = max(last_pos, pos)
    return problems


def slide_detail_problems(notes_text: str, *, has_frames: bool) -> list[str]:
    """Validate post-enrichment slide detail bullets and per-slide frame image links."""
    problems: list[str] = []
    block = _section_block(notes_text, NOTES_DETAIL_ANCHOR)
    lines = block.splitlines()
    heading_indexes = [i for i, line in enumerate(lines) if line.startswith("### ")]
    for pos, heading_index in enumerate(heading_indexes):
        heading = lines[heading_index]
        next_heading = heading_indexes[pos + 1] if pos + 1 < len(heading_indexes) else len(lines)
        body = lines[heading_index + 1:next_heading]
        is_intro = NOTES_INTRO_MARKER in "\n".join([heading, *body])
        if not any(line.startswith("- ") for line in body):
            problems.append(f"정리 노트 슬라이드에 설명 글머리표가 없습니다: {heading}")
        if has_frames and not is_intro and not any(_SLIDE_IMAGE_LINK_RE.search(line) for line in body):
            problems.append(f"정리 노트 슬라이드에 frames/ 이미지 링크가 없습니다: {heading}")
    return problems


def enrichment_problems(notes_text: str) -> list[str]:
    """Validate hook-only enrichment requirements."""
    problems: list[str] = []
    text = notes_text or ""
    if NOTES_UNENRICHED_MARKER in text:
        problems.append("notes.md에 미보강 마커가 남아 있습니다")

    takeaway_bullets = _bullet_lines(_section_block(text, NOTES_TAKEAWAY_ANCHOR))
    if len(takeaway_bullets) != 3:
        problems.append(f"3줄 요약은 글머리표 3개여야 합니다(현재 {len(takeaway_bullets)}개)")

    flow_count = len(_bullet_lines(_section_block(text, NOTES_FLOW_ANCHOR)))
    if flow_count < 2:
        problems.append(f"흐름은 글머리표가 2개 이상이어야 합니다(현재 {flow_count}개)")
    return problems


def coverage_contract_problems(notes_text: str, transcript_text: str) -> list[str]:
    """Layer 1 contract for CLI coverage: structure-only and skeleton-safe."""
    return base_structure_problems(notes_text)


def hook_contract_problems(notes_text: str, transcript_text: str, *, has_frames: bool) -> list[str]:
    """Layer 2 contract for the Claude Stop hook."""
    return (
        base_structure_problems(notes_text)
        + citation_problems(notes_text, transcript_text)
        + slide_detail_problems(notes_text, has_frames=has_frames)
        + enrichment_problems(notes_text)
    )
