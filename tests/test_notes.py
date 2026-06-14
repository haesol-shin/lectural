"""Unit tests for deterministic notes.md skeleton rendering."""

import re

from lectural.synthesis import (
    ANCHOR_ID_PATTERN,
    NOTES_CONCEPTS_ANCHOR,
    NOTES_COVERAGE_ANCHOR,
    NOTES_DETAIL_ANCHOR,
    NOTES_ENRICH_MARKER,
    NOTES_FLOW_ANCHOR,
    NOTES_INTRO_MARKER,
    NOTES_QUESTIONS_ANCHOR,
    NOTES_SLIDE_IMG_WIDTH,
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


def test_notes_toc_links_map_to_detail_section_anchors_without_timestamp_prefixes():
    md = _notes_md()
    toc = _block(md, NOTES_TOC_ANCHOR, NOTES_FLOW_ANCHOR)
    toc_lines = _bullet_lines(toc)

    assert toc_lines == ["- [탐욕 알고리즘](#sec-1)", "- [동적 계획법](#sec-2)"]
    assert all(not re.match(r"- \[\d\d:\d\d:\d\d", line) for line in toc_lines)
    detail = _block(md, NOTES_DETAIL_ANCHOR, NOTES_QUESTIONS_ANCHOR)
    for section_id in (1, 2):
        assert f'<a id="sec-{section_id}"></a>' in detail


def test_notes_skeleton_uses_new_placeholder_shape_and_no_transcript_dump():
    md = _notes_md()

    takeaway = _block(md, NOTES_TAKEAWAY_ANCHOR, NOTES_TOC_ANCHOR)
    assert NOTES_UNENRICHED_MARKER in takeaway
    assert _bullet_lines(takeaway) == [
        "- 미보강: 핵심 메시지 한 줄.",
        "- 미보강: 핵심 메시지 한 줄.",
        "- 미보강: 핵심 메시지 한 줄.",
    ]

    flow = _block(md, NOTES_FLOW_ANCHOR, NOTES_CONCEPTS_ANCHOR)
    assert NOTES_UNENRICHED_MARKER in flow
    assert _bullet_lines(flow) == [
        "- 미보강: 도입→전개→마무리 흐름을 짧게 정리하세요.",
        "- 미보강: 핵심 전개를 한 줄씩 정리하세요.",
    ]

    concepts = _block(md, NOTES_CONCEPTS_ANCHOR, NOTES_DETAIL_ANCHOR)
    assert NOTES_UNENRICHED_MARKER in concepts
    assert _bullet_lines(concepts) == ["- 미보강: 핵심 용어 → 정의를 영상 딥링크와 함께 정리하세요."]
    for transcript_text in ("도입 설명", "탐욕 알고리즘 정의", "탐욕 선택 속성", "동적 계획법 비교"):
        assert transcript_text not in concepts


def test_detail_sections_have_clean_headings_slide_images_and_placeholder_bullets():
    md = _notes_md()
    detail = _block(md, NOTES_DETAIL_ANCHOR, NOTES_QUESTIONS_ANCHOR)

    assert "### 탐욕 알고리즘" in detail
    assert "### 동적 계획법" in detail
    assert "### [00:" not in detail
    assert "transcript.md#" not in detail
    assert "youtu.be/" not in detail
    assert f'<img src="frames/00001.png" alt="슬라이드 1" width="{NOTES_SLIDE_IMG_WIDTH}">' in detail
    assert f'<img src="frames/00002.png" alt="슬라이드 2" width="{NOTES_SLIDE_IMG_WIDTH}">' in detail
    assert detail.count("- 미보강: 이 슬라이드 핵심을 요약 글머리표로 정리하세요.") == 2


def test_intro_section_without_frame_uses_intro_marker():
    video, segments, _, coverage = _fixture()
    slides = [
        {"t": 60.0, "frame": "frames/00001.png", "ocr_text": "첫 슬라이드", "is_slide": True},
    ]

    md = render_notes_md(build_synthesis_input(video, segments, slides), coverage)
    detail = _block(md, NOTES_DETAIL_ANCHOR, NOTES_QUESTIONS_ANCHOR)

    assert '<a id="sec-1"></a>' in detail
    assert "### 도입" in detail
    assert NOTES_INTRO_MARKER in detail
    assert '<img src="frames/00001.png" alt="슬라이드 2" width="480">' in detail


def test_empty_slide_section_detail_heading_is_clean_title_without_transcript_link():
    video, segments, _, coverage = _fixture()
    slides = [
        {"t": 0.0, "frame": "frames/00001.png", "ocr_text": "탐욕 알고리즘", "is_slide": True},
        {"t": 90.0, "frame": "frames/00002.png", "ocr_text": "빈 슬라이드", "is_slide": True},
        {"t": 120.0, "frame": "frames/00003.png", "ocr_text": "동적 계획법", "is_slide": True},
    ]

    md = render_notes_md(build_synthesis_input(video, segments, slides), coverage)
    detail = _block(md, NOTES_DETAIL_ANCHOR, NOTES_QUESTIONS_ANCHOR)

    assert "### 빈 슬라이드" in detail
    assert "### [00:01:30]" not in detail
    assert "transcript.md#" not in detail


def test_zero_segment_review_questions_have_single_placeholder_and_do_not_crash():
    video, _, _, coverage = _fixture()

    md = render_notes_md(build_synthesis_input(video, [], []), coverage)
    questions = _block(md, NOTES_QUESTIONS_ANCHOR, NOTES_COVERAGE_ANCHOR)
    question_lines = _bullet_lines(questions)

    assert question_lines == ["- 미보강 질문: 핵심 확인 질문과 답을 작성하세요."]
    assert "transcript.md#" not in questions
    assert "youtu.be/" not in questions


def test_narrative_sections_are_skeleton_only_with_no_fabricated_prose_or_legacy_markers():
    md = _notes_md()
    for start, end in (
        (NOTES_TAKEAWAY_ANCHOR, NOTES_TOC_ANCHOR),
        (NOTES_FLOW_ANCHOR, NOTES_CONCEPTS_ANCHOR),
    ):
        block = _block(md, start, end)
        assert NOTES_UNENRICHED_MARKER in block
        for line in _bullet_lines(block):
            assert line.startswith("- 미보강"), line

    for legacy in ("<!-- lectural:baseline -->", "## 핵심 요약", "## 구간별 요약", "## TO-ENRICH", "## 커버리지 요약"):
        assert legacy not in md
