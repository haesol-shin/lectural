"""Black-box red-team checks for the LecturAL Claude plugin package."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
CANONICAL_SKILL = ROOT / "skills" / "lectural" / "SKILL.md"
CLAUDE_SKILL = ROOT / ".claude" / "skills" / "lectural" / "SKILL.md"
PIPELINE_REF = ROOT / "skills" / "lectural" / "references" / "pipeline.md"
SYNTHESIS = ROOT / "lectural" / "synthesis.py"

ENGLISH_ARTIFACTS = [
    PLUGIN_JSON,
    MARKETPLACE_JSON,
    HOOKS_JSON,
    CANONICAL_SKILL,
    CLAUDE_SKILL,
    PIPELINE_REF,
]
ANCHOR_SYMBOLS = {
    "NOTES_ENRICH_MARKER",
    "NOTES_UNENRICHED_MARKER",
    "NOTES_TAKEAWAY_ANCHOR",
    "NOTES_TOC_ANCHOR",
    "NOTES_FLOW_ANCHOR",
    "NOTES_CONCEPTS_ANCHOR",
    "NOTES_DETAIL_ANCHOR",
    "NOTES_QUESTIONS_ANCHOR",
    "NOTES_COVERAGE_ANCHOR",
}
HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
INTERPRETERS = {"python", "py"}


def _read_text(path: Path) -> str:
    assert path.is_file(), f"missing expected artifact: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def _load_json(path: Path) -> dict:
    raw = _read_text(path)
    data = json.loads(raw)
    assert isinstance(data, dict), f"{path.relative_to(ROOT)} must be a JSON object"
    return data


def _validate_marketplace(data: dict) -> None:
    assert data.get("name") == "lectural"
    plugins = data.get("plugins")
    assert isinstance(plugins, list) and plugins, "marketplace plugins must be a non-empty list"
    for index, plugin in enumerate(plugins):
        assert isinstance(plugin, dict), f"plugins[{index}] must be an object"
        assert plugin.get("name") == "lectural"
        assert plugin.get("source") == "./", "marketplace source must be exactly './'"


def _stop_command_from_hooks(data: dict) -> str:
    stop_entries = data.get("hooks", {}).get("Stop")
    assert isinstance(stop_entries, list) and stop_entries, "Stop hook must be configured"
    commands: list[str] = []
    for entry in stop_entries:
        for hook in entry.get("hooks", []):
            if hook.get("type") == "command":
                command = hook.get("command")
                assert isinstance(command, str) and command.strip(), "Stop command must be a non-empty string"
                commands.append(command)
    assert commands, "Stop hook must contain a command hook"
    return commands[0]


def _validate_stop_command(command: str, plugin_root: Path) -> list[str]:
    tokens = shlex.split(command, posix=True)
    assert tokens, "Stop command must tokenize"
    assert tokens[0] in INTERPRETERS, "first Stop command token must be python or py"

    normalized_command = command.replace("\\", "/")
    required_quoted_path = '"${CLAUDE_PLUGIN_ROOT}/scripts/completeness_hook.py"'
    assert required_quoted_path in normalized_command, (
        "Stop command must contain the quoted ${CLAUDE_PLUGIN_ROOT} hook path"
    )

    hook_token = next(
        (
            token
            for token in tokens[1:]
            if "${CLAUDE_PLUGIN_ROOT}" in token
            and "scripts/completeness_hook.py" in token.replace("\\", "/")
        ),
        None,
    )
    assert hook_token is not None, "Stop command must pass the completeness hook path as an argument"

    resolved = Path(hook_token.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_root))).resolve()
    assert resolved == (plugin_root / "scripts" / "completeness_hook.py").resolve()
    assert resolved.is_file(), "resolved completeness hook path must exist"
    return tokens


def _synthesis_anchor_values() -> dict[str, str]:
    module = ast.parse(_read_text(SYNTHESIS), filename=str(SYNTHESIS))
    values: dict[str, str] = {}
    for node in module.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ANCHOR_SYMBOLS:
                    assert isinstance(node.value.value, str), f"{target.id} must be a string constant"
                    values[target.id] = node.value.value
    assert values.keys() == ANCHOR_SYMBOLS
    return values


def _strip_frontmatter_bytes(data: bytes) -> bytes:
    lines = data.splitlines(keepends=True)
    if not lines or lines[0].strip() != b"---":
        return data
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == b"---":
            return b"".join(lines[index + 1 :])
    raise AssertionError("frontmatter opener exists without a closing delimiter")


def test_plugin_and_marketplace_json_are_strict_and_portable():
    plugin = _load_json(PLUGIN_JSON)
    marketplace = _load_json(MARKETPLACE_JSON)

    assert plugin.get("name") == "lectural"
    _validate_marketplace(marketplace)


def test_hooks_json_is_strict_and_stop_command_is_portable():
    hooks = _load_json(HOOKS_JSON)
    command = _stop_command_from_hooks(hooks)

    _validate_stop_command(command, ROOT)


def test_stop_hook_command_resolves_and_runs_from_plugin_root(tmp_path: Path):
    command = _stop_command_from_hooks(_load_json(HOOKS_JSON))
    tokens = _validate_stop_command(command, ROOT)
    resolved_tokens = [token.replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT)) for token in tokens]
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    env["LECTURAL_RUNSTATE"] = str(tmp_path / "missing-runstate.json")

    completed = subprocess.run(
        resolved_tokens,
        cwd=ROOT,
        input="{}",
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_adversarial_stop_command_without_interpreter_is_rejected():
    command = _stop_command_from_hooks(_load_json(HOOKS_JSON))
    tokens = shlex.split(command, posix=True)
    assert len(tokens) >= 2, "fixture command must have an interpreter and hook argument"
    mutated = command.split(maxsplit=1)[1]

    with pytest.raises(AssertionError, match="first Stop command token"):
        _validate_stop_command(mutated, ROOT)


def test_adversarial_marketplace_source_must_remain_exact_relative_root():
    marketplace = _load_json(MARKETPLACE_JSON)
    mutated = json.loads(json.dumps(marketplace))
    mutated["plugins"][0]["source"] = "."

    with pytest.raises(AssertionError, match="exactly"):
        _validate_marketplace(mutated)


def test_english_packaging_artifacts_have_zero_hangul_codepoints():
    for path in ENGLISH_ARTIFACTS:
        text = _read_text(path)
        match = HANGUL_RE.search(text)
        assert match is None, f"Hangul codepoint in {path.relative_to(ROOT)} at offset {match.start()}"


def test_skill_docs_reference_synthesis_anchors_symbolically_only():
    anchor_values = _synthesis_anchor_values()
    for skill_path in [CANONICAL_SKILL, CLAUDE_SKILL]:
        text = _read_text(skill_path)
        for symbol in ANCHOR_SYMBOLS:
            assert symbol in text, f"{skill_path.relative_to(ROOT)} must reference {symbol} symbolically"
        for symbol, literal in anchor_values.items():
            if HANGUL_RE.search(literal):
                assert literal not in text, (
                    f"{skill_path.relative_to(ROOT)} embeds literal value for {symbol}; use the symbol name"
                )


def test_skill_bodies_match_after_frontmatter_is_stripped():
    canonical_body = _strip_frontmatter_bytes(CANONICAL_SKILL.read_bytes())
    claude_body = _strip_frontmatter_bytes(CLAUDE_SKILL.read_bytes())

    assert hashlib.sha256(canonical_body).hexdigest() == hashlib.sha256(claude_body).hexdigest()
    assert canonical_body == claude_body


def test_hooks_json_rejects_comment_syntax_as_adversarial_mutation():
    raw = _read_text(HOOKS_JSON)

    with pytest.raises(json.JSONDecodeError):
        json.loads(raw + "\n// adversarial comment\n")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
