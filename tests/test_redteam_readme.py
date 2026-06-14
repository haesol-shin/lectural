"""Red-team contract tests for README.md (ultragoal story G002).

Black-box checks over the user-facing README documentation surface. README prose
is now English, while the Korean forbidden-framing detector words remain as
guards against regressions in removed claims.
"""
from __future__ import annotations

import pathlib
import re

README = pathlib.Path(__file__).resolve().parent.parent / "README.md"
TEXT = README.read_text(encoding="utf-8")

FORBIDDEN = ["확신", "시험 기간", "시험기간", "유튜브에만", "Ollama", "local LLM"]


def test_readme_exists_and_is_korean_prose() -> None:
    assert README.is_file()
    assert re.search(r"[\uac00-\ud7a3]", TEXT), "README must contain Korean prose"


def test_no_forbidden_framing() -> None:
    hits = [w for w in FORBIDDEN if re.search(re.escape(w), TEXT, re.IGNORECASE)]
    assert not hits, f"forbidden framing present: {hits}"


def test_tech_stack_section_removed() -> None:
    assert not re.search(r"^##\s*기술 스택", TEXT, re.MULTILINE)


def test_mermaid_flowchart_present() -> None:
    assert "```mermaid" in TEXT
    assert "flowchart" in TEXT


def test_plugin_install_first_commands() -> None:
    assert "/plugin marketplace add" in TEXT
    assert "/plugin install lectural@lectural" in TEXT


def test_two_part_install_is_honest() -> None:
    # plugin install does not auto-provide deps; runtime is a separate step
    assert "/lectural:setup" in TEXT
    assert 'uv pip install -e ".[run]"' in TEXT
    assert "ffmpeg" in TEXT


def test_adversarial_forbidden_detector_actually_fires() -> None:
    # Prove the forbidden-framing detector is real: a mutated copy must be caught.
    mutated = TEXT + "\n이 강의 다 정리했다는 확신을 줍니다.\n"
    hits = [w for w in FORBIDDEN if re.search(re.escape(w), mutated)]
    assert "확신" in hits
