import json
from pathlib import Path
from types import SimpleNamespace

from lectural import doctor


VALID_HOOKS = {
    "hooks": {
        "Stop": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": 'python "${CLAUDE_PLUGIN_ROOT}/scripts/completeness_hook.py"',
                    }
                ],
            }
        ]
    }
}


def _write_distribution(root: Path) -> None:
    (root / "skills/lectural/references").mkdir(parents=True)
    (root / ".claude/skills/lectural/references").mkdir(parents=True)
    (root / ".claude-plugin").mkdir()
    (root / "hooks").mkdir()
    (root / "scripts").mkdir()

    (root / "AGENTS.md").write_text("agents\n", encoding="utf-8")
    skill = "---\nname: lectural\n---\n# Skill\nBody\n"
    (root / "skills/lectural/SKILL.md").write_text(skill, encoding="utf-8")
    (root / ".claude/skills/lectural/SKILL.md").write_text(skill, encoding="utf-8")
    prompt = "prompt\n"
    pipeline = "pipeline\n"
    (root / "skills/lectural/references/summary_prompt.md").write_text(prompt, encoding="utf-8")
    (root / ".claude/skills/lectural/references/summary_prompt.md").write_text(prompt, encoding="utf-8")
    (root / "skills/lectural/references/pipeline.md").write_text(pipeline, encoding="utf-8")
    (root / ".claude/skills/lectural/references/pipeline.md").write_text(pipeline, encoding="utf-8")
    (root / "scripts/completeness_hook.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "hooks/hooks.json").write_text(json.dumps(VALID_HOOKS), encoding="utf-8")
    (root / ".claude-plugin/plugin.json").write_text(
        json.dumps({"name": "lectural", "hooks": "./hooks/hooks.json"}),
        encoding="utf-8",
    )
    (root / ".claude-plugin/marketplace.json").write_text(
        json.dumps({"name": "lectural", "plugins": [{"name": "lectural", "source": "./"}]}),
        encoding="utf-8",
    )


def _stub_runtime_ok(monkeypatch):
    monkeypatch.setattr(doctor, "RUN_PYTHON_REQUIREMENTS", ())
    monkeypatch.setattr(doctor, "_python_core_item", lambda: doctor.ok("lectural", "python", "version 0.1.0"))
    monkeypatch.setattr(doctor.deps, "binary_status", lambda name: SimpleNamespace(name=name, kind="binary", available=True, detail=""))


def _statuses(report):
    return {(item["kind"], item["name"]): item["status"] for item in report["items"]}


def _item(report, name, kind=None):
    return next(
        item
        for item in report["items"]
        if item["name"] == name and (kind is None or item["kind"] == kind)
    )


def test_exit_code_mapping_for_all_status_classes():
    assert doctor.exit_code_for([doctor.ok("x", "test")]) == 0
    assert doctor.exit_code_for([doctor.ok("x", "test"), doctor.missing("y", "test", "missing", "fix")]) == 2
    assert doctor.exit_code_for([doctor.incompatible("x", "test", "bad", "fix")]) == 2
    assert doctor.exit_code_for([doctor.unfixable("x", "test", "boom", "report")]) == 1
    assert doctor.overall_status_for(0) == "ready"
    assert doctor.overall_status_for(2) == "user-action"
    assert doctor.overall_status_for(1) == "internal-unfixable"


def test_report_all_ok(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)

    report = doctor.build_report(tmp_path)

    assert report["schema_version"] == doctor.SCHEMA_VERSION
    assert report["exit_code"] == 0
    assert report["overall_status"] == "ready"
    assert {item["status"] for item in report["items"]} == {"ok"}


def test_report_missing_binary_maps_to_user_action(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)

    def binary_status(name):
        return SimpleNamespace(name=name, kind="binary", available=name != "ffmpeg", detail="install ffmpeg")

    monkeypatch.setattr(doctor.deps, "binary_status", binary_status)

    report = doctor.build_report(tmp_path)

    assert report["exit_code"] == 2
    assert _statuses(report)[("binary", "ffmpeg")] == "missing"


def test_python_incompatible_maps_to_incompatible_and_exit_2(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    monkeypatch.setattr(doctor, "RUN_PYTHON_REQUIREMENTS", (("cv2", None, None),))
    monkeypatch.setattr(
        doctor.deps,
        "python_status",
        lambda *a, **k: SimpleNamespace(available=False, detail="`cv2` version 4.8 does not satisfy opencv-python<=4.6"),
    )

    report = doctor.build_report(tmp_path)

    assert report["exit_code"] == 2
    assert _statuses(report)[("python", "cv2")] == "incompatible"


def test_doctor_accepts_lowercase_pillow_provider_for_pil(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    monkeypatch.setattr(doctor, "RUN_PYTHON_REQUIREMENTS", (("PIL", "Pillow", ">=10.0.0"),))
    monkeypatch.setattr(doctor.importlib, "import_module", lambda name: SimpleNamespace(__version__="10.1.0"))
    monkeypatch.setattr(doctor.importlib_metadata, "version", lambda name: {"Pillow": "10.1.0"}[name])
    monkeypatch.setattr(doctor.importlib_metadata, "packages_distributions", lambda: {"PIL": ["pillow"]})

    report = doctor.build_report(tmp_path)

    item = _item(report, "PIL (Pillow)", "python")
    assert report["exit_code"] == 0
    assert item["status"] == "ok"


def test_doctor_accepts_distribution_version_when_provider_list_empty_for_non_cv2(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    monkeypatch.setattr(doctor, "RUN_PYTHON_REQUIREMENTS", (("yt_dlp", "yt-dlp", ">=2024.1.0"),))
    monkeypatch.setattr(doctor.importlib, "import_module", lambda name: SimpleNamespace(__version__="2024.1.0"))
    monkeypatch.setattr(doctor.importlib_metadata, "version", lambda name: {"yt-dlp": "2024.2.0"}[name])
    monkeypatch.setattr(doctor.importlib_metadata, "packages_distributions", lambda: {})

    report = doctor.build_report(tmp_path)

    item = _item(report, "yt_dlp (yt-dlp)", "python")
    assert report["exit_code"] == 0
    assert item["status"] == "ok"

def test_doctor_enforces_fallback_numpy_runtime_constraint(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    monkeypatch.setattr(doctor, "RUN_PYTHON_REQUIREMENTS", (("numpy", None, None),))
    monkeypatch.setattr(doctor.importlib, "import_module", lambda name: SimpleNamespace(__version__="2.0.0"))
    monkeypatch.setattr(doctor.importlib_metadata, "version", lambda name: {"numpy": "2.0.0"}[name])

    report = doctor.build_report(tmp_path)

    item = _item(report, "numpy", "python")
    assert report["exit_code"] == 2
    assert item["status"] == "incompatible"
    assert "numpy>=1.24,<2" in item["detail"]


def test_doctor_enforces_fallback_paddlepaddle_runtime_constraint(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    monkeypatch.setattr(doctor, "RUN_PYTHON_REQUIREMENTS", (("paddle", None, None),))
    monkeypatch.setattr(doctor.importlib, "import_module", lambda name: SimpleNamespace(__version__="3.0.0"))
    monkeypatch.setattr(doctor.importlib_metadata, "version", lambda name: {"paddlepaddle": "3.0.0"}[name])

    report = doctor.build_report(tmp_path)

    item = _item(report, "paddle", "python")
    assert report["exit_code"] == 2
    assert item["status"] == "incompatible"
    assert "paddlepaddle>=2.6,<3" in item["detail"]


def test_doctor_accepts_fallback_paddlepaddle_valid_version_with_empty_provider_metadata(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    monkeypatch.setattr(doctor, "RUN_PYTHON_REQUIREMENTS", (("paddle", None, None),))
    monkeypatch.setattr(doctor.importlib, "import_module", lambda name: SimpleNamespace(__version__="3.9.9"))
    monkeypatch.setattr(doctor.importlib_metadata, "version", lambda name: {"paddlepaddle": "2.6.2"}[name])
    monkeypatch.setattr(doctor.importlib_metadata, "packages_distributions", lambda: {})

    report = doctor.build_report(tmp_path)

    item = _item(report, "paddle", "python")
    assert report["exit_code"] == 0
    assert item["status"] == "ok"

def test_doctor_keeps_cv2_provider_mismatch_incompatible(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    monkeypatch.setattr(doctor, "RUN_PYTHON_REQUIREMENTS", (("cv2", None, None),))
    monkeypatch.setattr(doctor.importlib, "import_module", lambda name: SimpleNamespace(__version__="4.6.0"))
    monkeypatch.setattr(doctor.importlib_metadata, "version", lambda name: "4.6.0.66")
    monkeypatch.setattr(
        doctor.deps,
        "python_status",
        lambda *a, **k: SimpleNamespace(
            available=False,
            detail="`cv2` imported but provider check failed: expected distribution `opencv-python`",
        ),
    )

    report = doctor.build_report(tmp_path)

    item = _item(report, "cv2", "python")
    assert report["exit_code"] == 2
    assert item["status"] == "incompatible"
    assert "provider check failed" in item["detail"]


def test_doctor_runtime_failure_maps_to_unfixable(monkeypatch):
    monkeypatch.setattr(doctor, "_items", lambda root: (_ for _ in ()).throw(RuntimeError("boom")))

    report = doctor.build_report(Path("."))

    assert report["exit_code"] == 1
    assert report["items"][0]["status"] == "unfixable"


def test_plugin_manifest_validation_catches_marketplace_source(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    (tmp_path / ".claude-plugin/marketplace.json").write_text(
        json.dumps({"name": "lectural", "plugins": [{"name": "lectural", "source": "."}]}),
        encoding="utf-8",
    )

    report = doctor.build_report(tmp_path)

    assert report["exit_code"] == 2
    item = next(item for item in report["items"] if item["name"] == ".claude-plugin/marketplace.json")
    assert item["status"] == "incompatible"
    assert "expected './'" in item["detail"]


def test_hooks_manifest_empty_stop_is_incompatible(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    (tmp_path / "hooks/hooks.json").write_text(json.dumps({"hooks": {}}), encoding="utf-8")

    report = doctor.build_report(tmp_path)

    item = _item(report, "hooks/hooks.json", "file")
    assert report["exit_code"] == 2
    assert report["overall_status"] == "user-action"
    assert item["status"] == "incompatible"
    assert "hooks.Stop" in item["detail"]


def test_hooks_manifest_malformed_json_is_incompatible(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    (tmp_path / "hooks/hooks.json").write_text('{"hooks": ', encoding="utf-8")

    report = doctor.build_report(tmp_path)

    item = _item(report, "hooks/hooks.json", "file")
    assert report["exit_code"] == 2
    assert report["overall_status"] == "user-action"
    assert item["status"] == "incompatible"
    assert "invalid hooks JSON" in item["detail"]


def test_hooks_manifest_missing_command_hook_is_incompatible(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    (tmp_path / "hooks/hooks.json").write_text(
        json.dumps({"hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "prompt", "command": "ignored"}]}]}}),
        encoding="utf-8",
    )

    report = doctor.build_report(tmp_path)

    item = _item(report, "hooks/hooks.json", "file")
    assert report["exit_code"] == 2
    assert report["overall_status"] == "user-action"
    assert item["status"] == "incompatible"
    assert "command hook" in item["detail"]


def test_hooks_manifest_rejects_non_python_interpreter(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    mutated = json.loads(json.dumps(VALID_HOOKS))
    mutated["hooks"]["Stop"][0]["hooks"][0]["command"] = 'node "${CLAUDE_PLUGIN_ROOT}/scripts/completeness_hook.py"'
    (tmp_path / "hooks/hooks.json").write_text(json.dumps(mutated), encoding="utf-8")

    report = doctor.build_report(tmp_path)

    item = _item(report, "hooks/hooks.json", "file")
    assert report["exit_code"] == 2
    assert item["status"] == "incompatible"
    assert "python/py" in item["detail"]


def test_hooks_manifest_rejects_unquoted_plugin_root_script(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    mutated = json.loads(json.dumps(VALID_HOOKS))
    mutated["hooks"]["Stop"][0]["hooks"][0]["command"] = "python ${CLAUDE_PLUGIN_ROOT}/scripts/completeness_hook.py"
    (tmp_path / "hooks/hooks.json").write_text(json.dumps(mutated), encoding="utf-8")

    report = doctor.build_report(tmp_path)

    item = _item(report, "hooks/hooks.json", "file")
    assert report["exit_code"] == 2
    assert item["status"] == "incompatible"
    assert "quoted ${CLAUDE_PLUGIN_ROOT}" in item["detail"]


def test_hooks_manifest_rejects_missing_plugin_root_script_argument(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    mutated = json.loads(json.dumps(VALID_HOOKS))
    mutated["hooks"]["Stop"][0]["hooks"][0]["command"] = 'python "scripts/completeness_hook.py"'
    (tmp_path / "hooks/hooks.json").write_text(json.dumps(mutated), encoding="utf-8")

    report = doctor.build_report(tmp_path)

    item = _item(report, "hooks/hooks.json", "file")
    assert report["exit_code"] == 2
    assert item["status"] == "incompatible"
    assert "quoted ${CLAUDE_PLUGIN_ROOT}" in item["detail"]


def test_plugin_manifest_hooks_path_pointing_to_missing_file_is_missing(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    (tmp_path / ".claude-plugin/plugin.json").write_text(
        json.dumps({"name": "lectural", "hooks": "./hooks/missing.json"}),
        encoding="utf-8",
    )

    report = doctor.build_report(tmp_path)

    item = _item(report, "hooks/hooks.json", "plugin")
    assert report["exit_code"] == 2
    assert item["status"] == "missing"
    assert "does not exist" in item["detail"]


def test_skill_prompt_pipeline_parity_checks(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    (tmp_path / ".claude/skills/lectural/SKILL.md").write_text(
        "---\nname: other\n---\n# Skill\nBody\n",
        encoding="utf-8",
    )
    (tmp_path / ".claude/skills/lectural/references/summary_prompt.md").write_text("changed\n", encoding="utf-8")
    (tmp_path / ".claude/skills/lectural/references/pipeline.md").write_text("changed\n", encoding="utf-8")

    report = doctor.build_report(tmp_path)

    statuses = _statuses(report)
    # Different frontmatter is allowed; body must match after stripping.
    assert statuses[("mirror", "skill body mirror")] == "ok"
    assert statuses[("mirror", "summary prompt mirror")] == "incompatible"
    assert statuses[("mirror", "pipeline mirror")] == "incompatible"


def test_fix_missing_yt_dlp_attempts_once_then_rechecks(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)
    binary_calls = []
    installed = {"yt-dlp": False}

    def binary_status(name):
        binary_calls.append(name)
        available = True if name == "ffmpeg" else installed["yt-dlp"]
        return SimpleNamespace(name=name, kind="binary", available=available, detail=f"install {name}")

    def run(command, check, text, capture_output, timeout):
        assert command == ["uv", "tool", "install", "yt-dlp"]
        installed["yt-dlp"] = True
        return SimpleNamespace(returncode=0, stdout="installed", stderr="")

    monkeypatch.setattr(doctor.deps, "binary_status", binary_status)
    monkeypatch.setattr(doctor.subprocess, "run", run)

    report = doctor.run(fix=True, root=tmp_path)

    assert report["exit_code"] == 0
    assert [action["command"] for action in report["actions"]] == [["uv", "tool", "install", "yt-dlp"]]
    assert binary_calls.count("yt-dlp") >= 2
    assert report["actions"][0]["outcome"] == "ok"
    assert "status" not in report["actions"][0]


def test_fix_missing_ffmpeg_uses_safe_hint_without_infinite_loop(tmp_path, monkeypatch):
    _write_distribution(tmp_path)
    _stub_runtime_ok(monkeypatch)

    def binary_status(name):
        return SimpleNamespace(name=name, kind="binary", available=name != "ffmpeg", detail=f"install {name}")

    monkeypatch.setattr(doctor.deps, "binary_status", binary_status)
    monkeypatch.setattr(doctor.platform, "system", lambda: "Linux")
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/apt-get" if name == "apt-get" else None)

    report = doctor.run(fix=True, root=tmp_path)

    assert report["exit_code"] == 2
    assert len(report["actions"]) == 1
    assert report["actions"][0]["command"] is None
    assert "will not start an admin install" in report["actions"][0]["detail"]
    assert report["actions"][0]["outcome"] == "hint"
    assert "status" not in report["actions"][0]
