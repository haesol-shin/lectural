"""Offline source-aware citation contract tests."""

from __future__ import annotations

from lectural.notes_contract import citation_problems, coverage_contract_problems, hook_contract_problems


def _local_notes(concepts: str, answers: list[str]) -> str:
    answer_block = "\n\n".join(answers)
    return f'''<!-- lectural:notes -->
## 3줄 요약
- 요약 1
- 요약 2
- 요약 3
## 목차
- [전체](#sec-1)
## 흐름
- 흐름 1
- 흐름 2
## 핵심 개념·이론
{concepts}
## 정리 노트
<a id="sec-1"></a>
### 전체
- 설명
## 복습 질문
{answer_block}
## 정리 커버리지
- coverage
'''


def _transcript() -> str:
    return '<a id="t000001"></a> [00:00:01] one\n<a id="t000001-2"></a> [00:00:01] two\n<a id="t000005"></a> [00:00:05] five\n'


def test_local_exact_anchor_citations_accept_duplicate_second_suffix():
    notes = _local_notes(
        "- **개념**: 정의. ([전사 0:01](transcript.md#t000001-2))",
        [
            "답 하나. ([전사 0:01](transcript.md#t000001))",
            "답 둘. ([전사 0:01](transcript.md#t000001-2))",
            "답 셋. ([전사 0:05](transcript.md#t000005))",
        ],
    )
    assert citation_problems(notes, _transcript(), {"kind": "transcript"}) == []


def test_local_contract_rejects_dangling_anchor_and_youtube_link():
    notes = _local_notes(
        "- **개념**: 정의. ([전사 9:59](transcript.md#t999999))\n"
        "- **다른 개념**: 정의. ([영상 0:01](https://youtu.be/dQw4w9WgXcQ?t=1))",
        [
            "답 하나. ([전사 0:01](transcript.md#t000001))",
            "답 둘. ([전사 0:01](transcript.md#t000001-2))",
        ],
    )
    problems = citation_problems(notes, _transcript(), {"kind": "transcript"})
    assert any("존재하지 않습니다" in problem for problem in problems)
    assert any("youtu.be" in problem for problem in problems)
    assert any("3개 이상" in problem for problem in problems)


def test_local_contract_rejects_non_relative_transcript_hrefs():
    notes = _local_notes(
        "- **개념**: 정의. ([전사 0:01](https://example.com/transcript.md#t000001))",
        [
            "답 하나. ([전사 0:01](other-transcript.md#t000001))",
            "답 둘. ([전사 0:01](https://example.com/transcript.md#t000001))",
            "답 셋. ([전사 0:05](docs/transcript.md#t000005))",
        ],
    )
    problems = citation_problems(notes, _transcript(), {"kind": "transcript"})
    assert any("전사 앵커가 없습니다" in problem for problem in problems)
    assert any("3개 이상" in problem for problem in problems)


def test_youtube_contract_preserves_link_and_timing_rule():
    notes = _local_notes(
        "- **개념**: 정의. ([영상 0:01](https://youtu.be/dQw4w9WgXcQ?t=1))",
        [
            "답 하나. ([영상 0:01](https://youtu.be/dQw4w9WgXcQ?t=1))",
            "답 둘. ([영상 0:01](https://youtu.be/dQw4w9WgXcQ?t=1))",
            "답 셋. ([영상 0:05](https://youtu.be/dQw4w9WgXcQ?t=5))",
        ],
    )
    assert citation_problems(notes, _transcript(), {"kind": "youtube", "video_id": "dQw4w9WgXcQ"}) == []
    bad = notes.replace("?t=1", "?t=20", 1)
    assert any("1초 넘게 다릅니다" in problem for problem in citation_problems(bad, _transcript(), {"kind": "youtube", "video_id": "dQw4w9WgXcQ"}))


def test_layer1_remains_structure_only_for_local_citations():
    notes = _local_notes("- **개념**: no citation", [])
    assert coverage_contract_problems(notes, _transcript()) == []
