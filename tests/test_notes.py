"""Unit tests for deterministic notes.md skeleton rendering."""

import re

from lectural.synthesis import (
    ANCHOR_ID_PATTERN,
    NOTES_CONCEPTS_ANCHOR,
    NOTES_COVERAGE_ANCHOR,
    NOTES_DETAIL_ANCHOR,
    NOTES_ENRICH_MARKER,
    NOTES_FLOW_ANCHOR,
    NOTES_QUESTIONS_ANCHOR,
    NOTES_TAKEAWAY_ANCHOR,
    NOTES_TOC_ANCHOR,
    NOTES_UNENRICHED_MARKER,
    build_synthesis_input,
    build_transcript_anchor_ids,
    format_timestamp,
    render_notes_md,
    render_transcript_md,
)

VIDEO_ID = "ABCDEFGHIJK"


def _fixture():
    video = {
        "title": "알고리즘 1강",
        "url": f"https://youtu.be/{VIDEO_ID}",
        "duration_sec": 240.0,
        "source": "caption",
    }
    segments = [
        {"t": 0.0, "text": "도입 설명"},
        {"t": 65.0, "text": "탐욕 알고리즘 정의"},
        {"t": 65.0, "text": "탐욕 선택 속성"},
        {"t": 130.0, "text": "동적 계획법 비교"},
    ]
    slides = [
        {"t": 0.0, "frame": "frames/00001.png", "ocr_text": "탐욕 알고리즘", "is_slide": True},
        {"t": 120.0, "frame": "frames/00002.png", "ocr_text": "동적 계획법", "is_slide": True},
    ]
    coverage = {
        "duration_sec": 240.0,
        "ocr_engine": "paddleocr",
        "gap_check": {"max_untranscribed_speech_gap_sec": 10, "threshold_sec": 60, "pass": True},
        "scene_coverage": {
            "speech_bins": [0, 1, 2],
            "uncovered_speech_bins": [],
            "slide_frames_total": 2,
            "slide_frames_with_text": 2,
            "pass": True,
        },
        "artifacts": {"transcript_nonempty": True, "notes_nonempty": True},
    }
    return video, segments, slides, coverage


def _notes_md():
    video, segments, slides, coverage = _fixture()
    return render_notes_md(build_synthesis_input(video, segments, slides), coverage)


def _block(md: str, start: str, end: str | None = None) -> str:
    start_index = md.index(start)
    end_index = md.index(end, start_index + len(start)) if end else len(md)
    return md[start_index:end_index]


def _bullet_lines(block: str) -> list[str]:
    return [line for line in block.splitlines() if line.startswith("- ")]


def test_anchor_ids_are_unique_for_duplicate_timestamps_and_match_pattern():
    ids = build_transcript_anchor_ids(
        [
            {"t": 65.0, "text": "a"},
            {"t": 65.0, "text": "b"},
            {"t": 65.0, "text": "c"},
        ]
    )
    assert ids == ["t000105", "t000105-2", "t000105-3"]
    assert all(re.fullmatch(ANCHOR_ID_PATTERN, anchor_id) for anchor_id in ids)


def test_render_transcript_md_emits_anchor_per_cue():
    video, segments, _, _ = _fixture()
    md = render_transcript_md(video, segments)
    ids = build_transcript_anchor_ids(segments)

    for segment, anchor_id in zip(segments, ids):
        assert f'<a id="{anchor_id}"></a> ' in md
        assert f"[{format_timestamp(float(segment['t']))}]" in md
        assert segment["text"] in md
    assert md.count('<a id="t') == len(segments)


def test_notes_sections_are_in_required_order_and_marker_is_line_one():
    md = _notes_md()
    anchors = [
        NOTES_TAKEAWAY_ANCHOR,
        NOTES_TOC_ANCHOR,
        NOTES_FLOW_ANCHOR,
        NOTES_CONCEPTS_ANCHOR,
        NOTES_DETAIL_ANCHOR,
        NOTES_QUESTIONS_ANCHOR,
        NOTES_COVERAGE_ANCHOR,
    ]

    assert md.splitlines()[0] == NOTES_ENRICH_MARKER
    positions = [md.index(anchor) for anchor in anchors]
    assert positions == sorted(positions)


def test_notes_toc_links_map_to_detail_section_anchors():
    md = _notes_md()
    toc = _block(md, NOTES_TOC_ANCHOR, NOTES_FLOW_ANCHOR)
    toc_lines = _bullet_lines(toc)

    assert toc_lines
    section_ids = []
    for line in toc_lines:
        match = re.fullmatch(r"- \[[^\]]+\]\(#sec-(\d+)\)", line)
        assert match, line
        section_ids.append(match.group(1))

    detail = _block(md, NOTES_DETAIL_ANCHOR, NOTES_QUESTIONS_ANCHOR)
    for section_id in section_ids:
        assert f'<a id="sec-{section_id}"></a>' in detail


def test_required_notes_bullets_have_transcript_and_video_citations():
    md = _notes_md()
    expected = {
        "도입 설명": ("t000000", 0),
        "탐욕 알고리즘 정의": ("t000105", 65),
        "탐욕 선택 속성": ("t000105-2", 65),
        "동적 계획법 비교": ("t000210", 130),
    }

    concept = _block(md, NOTES_CONCEPTS_ANCHOR, NOTES_DETAIL_ANCHOR)
    detail = _block(md, NOTES_DETAIL_ANCHOR, NOTES_QUESTIONS_ANCHOR)
    questions = _block(md, NOTES_QUESTIONS_ANCHOR, NOTES_COVERAGE_ANCHOR)

    for block in (concept, detail):
        for text, (anchor_id, seconds) in expected.items():
            line = next(line for line in _bullet_lines(block) if text in line)
            assert f"transcript.md#{anchor_id}" in line
            assert f"youtu.be/{VIDEO_ID}?t={seconds}" in line

    question_lines = _bullet_lines(questions)
    assert len(question_lines) == 3
    for line, (anchor_id, seconds) in zip(question_lines, [("t000000", 0), ("t000105", 65), ("t000105-2", 65)]):
        assert f"transcript.md#{anchor_id}" in line
        assert f"youtu.be/{VIDEO_ID}?t={seconds}" in line


def test_takeaway_toc_and_flow_are_citation_exempt():
    md = _notes_md()
    exempt_blocks = [
        _block(md, NOTES_TAKEAWAY_ANCHOR, NOTES_TOC_ANCHOR),
        _block(md, NOTES_TOC_ANCHOR, NOTES_FLOW_ANCHOR),
        _block(md, NOTES_FLOW_ANCHOR, NOTES_CONCEPTS_ANCHOR),
    ]

    for block in exempt_blocks:
        assert "transcript.md#" not in block
        assert "youtu.be/" not in block


def test_unenriched_marker_is_present_in_required_skeleton_sections():
    md = _notes_md()
    required = [
        _block(md, NOTES_TAKEAWAY_ANCHOR, NOTES_TOC_ANCHOR),
        _block(md, NOTES_FLOW_ANCHOR, NOTES_CONCEPTS_ANCHOR),
        _block(md, NOTES_CONCEPTS_ANCHOR, NOTES_DETAIL_ANCHOR),
        _block(md, NOTES_QUESTIONS_ANCHOR, NOTES_COVERAGE_ANCHOR),
    ]
    assert all(NOTES_UNENRICHED_MARKER in block for block in required)


def test_empty_slide_section_detail_heading_uses_plain_timestamp_without_transcript_link():
    video, segments, _, coverage = _fixture()
    slides = [
        {"t": 0.0, "frame": "frames/00001.png", "ocr_text": "탐욕 알고리즘", "is_slide": True},
        {"t": 90.0, "frame": "frames/00002.png", "ocr_text": "빈 슬라이드", "is_slide": True},
        {"t": 120.0, "frame": "frames/00003.png", "ocr_text": "동적 계획법", "is_slide": True},
    ]

    md = render_notes_md(build_synthesis_input(video, segments, slides), coverage)
    detail = _block(md, NOTES_DETAIL_ANCHOR, NOTES_QUESTIONS_ANCHOR)

    assert "### [00:01:30] 빈 슬라이드" in detail
    assert "### [00:01:30](transcript.md#" not in detail


def test_notes_transcript_links_are_subset_of_rendered_transcript_anchors():
    video, segments, _, coverage = _fixture()
    slides = [
        {"t": 0.0, "frame": "frames/00001.png", "ocr_text": "탐욕 알고리즘", "is_slide": True},
        {"t": 90.0, "frame": "frames/00002.png", "ocr_text": "빈 슬라이드", "is_slide": True},
        {"t": 120.0, "frame": "frames/00003.png", "ocr_text": "동적 계획법", "is_slide": True},
    ]

    notes_md = render_notes_md(build_synthesis_input(video, segments, slides), coverage)
    transcript_md = render_transcript_md(video, segments)

    referenced_ids = set(re.findall(r"transcript\.md#(t\d{6}(?:-\d+)?)", notes_md))
    transcript_ids = set(re.findall(r'<a id="(t\d{6}(?:-\d+)?)"></a>', transcript_md))
    assert referenced_ids <= transcript_ids


def test_zero_segment_review_questions_have_no_transcript_citation_and_do_not_crash():
    video, _, _, coverage = _fixture()

    md = render_notes_md(build_synthesis_input(video, [], []), coverage)
    questions = _block(md, NOTES_QUESTIONS_ANCHOR, NOTES_COVERAGE_ANCHOR)
    question_lines = _bullet_lines(questions)

    assert len(question_lines) == 3
    assert all("transcript.md#" not in line for line in question_lines)
    assert all("youtu.be/" not in line for line in question_lines)


def test_narrative_sections_are_skeleton_only_with_no_fabricated_prose():
    md = _notes_md()
    # 한눈에 요약 and 강의 흐름 are narrative+citation-exempt: they must contain ONLY
    # the unenriched marker + `- 미보강` placeholder bullets, never deterministic prose.
    for start, end in (
        (NOTES_TAKEAWAY_ANCHOR, NOTES_TOC_ANCHOR),
        (NOTES_FLOW_ANCHOR, NOTES_CONCEPTS_ANCHOR),
    ):
        block = _block(md, start, end)
        assert NOTES_UNENRICHED_MARKER in block
        for line in _bullet_lines(block):
            assert line.startswith("- 미보강"), line
    # No legacy mechanical-summary headings/markers leak into notes.md.
    for legacy in ("<!-- lectural:baseline -->", "## 핵심 요약", "## 구간별 요약", "## TO-ENRICH", "## 커버리지 요약"):
        assert legacy not in md
