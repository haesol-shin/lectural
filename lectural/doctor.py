"""LecturAL installation doctor.

Validates the Python runtime, external binaries, plugin manifests, agent files,
and agent files. The checker is intentionally deterministic
and side-effect free unless ``fix=True`` is requested.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib
from importlib import metadata as importlib_metadata
import json
import platform
from pathlib import Path
import shutil
import subprocess
import shlex
import sys
from typing import Callable, Iterable

from . import deps

STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_INCOMPATIBLE = "incompatible"
STATUS_UNFIXABLE = "unfixable"
STATUSES = {STATUS_OK, STATUS_MISSING, STATUS_INCOMPATIBLE, STATUS_UNFIXABLE}
SCHEMA_VERSION = 1

RUN_PYTHON_REQUIREMENTS: tuple[tuple[str, str | None, str | None], ...] = (
    ("yt_dlp", "yt-dlp", ">=2024.1.0"),
    ("youtube_transcript_api", "youtube-transcript-api", ">=0.6.2"),
    ("faster_whisper", "faster-whisper", ">=1.0.0"),
    ("numpy", None, None),
    ("paddleocr", None, None),
    ("paddle", None, None),
    ("cv2", None, None),
    ("pytesseract", "pytesseract", ">=0.3.10"),
    ("PIL", "Pillow", ">=10.0.0"),
    ("webrtcvad", "webrtcvad", ">=2.0.10"),
)

AGENT_FILES = (
    "AGENTS.md",
    "skills/lectural/SKILL.md",
    "skills/lectural/references/summary_prompt.md",
)


@dataclass(frozen=True)
class DoctorItem:
    name: str
    kind: str
    status: str
    detail: str
    hint: str

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"invalid doctor status: {self.status}")


@dataclass(frozen=True)
class FixAction:
    name: str
    command: list[str] | None
    outcome: str
    detail: str


def ok(name: str, kind: str, detail: str = "ready", hint: str = "") -> DoctorItem:
    return DoctorItem(name=name, kind=kind, status=STATUS_OK, detail=detail, hint=hint)


def missing(name: str, kind: str, detail: str, hint: str) -> DoctorItem:
    return DoctorItem(name=name, kind=kind, status=STATUS_MISSING, detail=detail, hint=hint)


def incompatible(name: str, kind: str, detail: str, hint: str) -> DoctorItem:
    return DoctorItem(name=name, kind=kind, status=STATUS_INCOMPATIBLE, detail=detail, hint=hint)


def unfixable(name: str, kind: str, detail: str, hint: str) -> DoctorItem:
    return DoctorItem(name=name, kind=kind, status=STATUS_UNFIXABLE, detail=detail, hint=hint)


def _root(root: str | Path | None) -> Path:
    return Path.cwd() if root is None else Path(root)


def _rel(root: Path, relative: str) -> Path:
    return root / relative


def _load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def _status_from_python_detail(detail: str) -> str:
    incompatible_markers = (
        "does not satisfy",
        "provider check failed",
        "version could not be checked",
        "version could not be determined",
    )
    return STATUS_INCOMPATIBLE if any(marker in detail for marker in incompatible_markers) else STATUS_MISSING


def _runtime_dep_hint() -> str:
    return "Install runtime extras with `uv pip install -e \".[run]\"` or use `uvx --from \".[run]\" lectural ...`."


def _doctor_python_status(module: str, package: str | None, specifier: str | None) -> deps.DepStatus:
    requirement = deps._PYTHON_REQUIREMENTS.get(module)
    package_name = package or (requirement.package if requirement else module)
    version_specifier = specifier if specifier is not None else (requirement.specifier if requirement else None)

    if module == "cv2":
        return deps.python_status(module, package=package_name, specifier=version_specifier)

    try:
        importlib.import_module(module)
    except Exception as exc:  # noqa: BLE001 - report dependency import failure, do not crash doctor
        return deps.DepStatus(
            name=module,
            kind="python",
            available=False,
            detail=f"{_runtime_dep_hint()} Import failed: {exc.__class__.__name__}: {exc}",
        )

    if version_specifier is None:
        return deps.DepStatus(name=module, kind="python", available=True)

    try:
        version = importlib_metadata.version(package_name)
    except importlib_metadata.PackageNotFoundError:
        return deps.DepStatus(
            name=module,
            kind="python",
            available=False,
            detail=f"`{module}` imported but distribution `{package_name}` version could not be determined. {_runtime_dep_hint()}",
        )
    except Exception as exc:  # noqa: BLE001 - metadata backends vary by environment
        return deps.DepStatus(
            name=module,
            kind="python",
            available=False,
            detail=f"`{module}` imported but version could not be checked: {exc.__class__.__name__}: {exc}. {_runtime_dep_hint()}",
        )

    if not deps._satisfies_version(version, version_specifier):
        return deps.DepStatus(
            name=module,
            kind="python",
            available=False,
            detail=f"`{module}` version {version} does not satisfy {package_name}{version_specifier}. {_runtime_dep_hint()}",
        )

    return deps.DepStatus(name=module, kind="python", available=True)


def _python_core_item() -> DoctorItem:
    try:
        module = importlib.import_module("lectural")
    except Exception as exc:  # noqa: BLE001 - report import failure, do not crash doctor
        return missing(
            "lectural",
            "python",
            f"import failed: {type(exc).__name__}: {exc}",
            "Install the package in this environment, for example `uv pip install -e .`.",
        )

    module_version = getattr(module, "__version__", None)
    try:
        distribution_version = importlib_metadata.version("lectural")
    except importlib_metadata.PackageNotFoundError:
        distribution_version = None
    except Exception as exc:  # noqa: BLE001
        return incompatible(
            "lectural",
            "python",
            f"could not read package metadata: {type(exc).__name__}: {exc}",
            "Reinstall LecturAL in a clean uv/uvx environment.",
        )

    if not module_version and not distribution_version:
        return incompatible(
            "lectural",
            "python",
            "import succeeded but no __version__ or installed distribution version was found",
            "Reinstall LecturAL from a packaged build or editable checkout.",
        )
    if module_version and distribution_version and str(module_version) != str(distribution_version):
        return incompatible(
            "lectural",
            "python",
            f"module version {module_version} differs from installed distribution {distribution_version}",
            "Remove shadowing checkouts and reinstall LecturAL in the active environment.",
        )
    version = module_version or distribution_version
    return ok("lectural", "python", f"version {version}")


def _python_dep_item(module: str, package: str | None, specifier: str | None) -> DoctorItem:
    status = _doctor_python_status(module, package=package, specifier=specifier)
    display = module if package is None or package == module else f"{module} ({package})"
    if status.available:
        return ok(display, "python", "import/version check passed")
    item_status = _status_from_python_detail(status.detail)
    ctor = incompatible if item_status == STATUS_INCOMPATIBLE else missing
    return ctor(display, "python", status.detail, _runtime_dep_hint())


def _binary_item(name: str) -> DoctorItem:
    status = deps.binary_status(name)
    if status.available:
        return ok(name, "binary", "found on PATH")
    return missing(name, "binary", "not found on PATH", status.detail)


def _file_item(root: Path, relative: str) -> DoctorItem:
    path = _rel(root, relative)
    if path.is_file():
        return ok(relative, "file", "present")
    return missing(relative, "file", f"missing {relative}", f"Restore `{relative}` from the LecturAL distribution.")



def _hook_command_item(root: Path, relative: str = "hooks/hooks.json") -> DoctorItem:
    path = _rel(root, relative)
    if not path.is_file():
        return missing(relative, "file", f"missing {relative}", f"Restore `{relative}` from the LecturAL distribution.")

    try:
        data = _load_json(path)
    except (json.JSONDecodeError, ValueError) as exc:
        return incompatible(relative, "file", f"invalid hooks JSON manifest: {type(exc).__name__}: {exc}", "Fix hooks/hooks.json to be a JSON object with hooks.Stop command wiring.")
    except Exception as exc:  # noqa: BLE001
        return unfixable(relative, "file", f"could not read hooks manifest: {type(exc).__name__}: {exc}", "Check filesystem permissions and file encoding.")

    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return incompatible(relative, "file", "hooks must be a JSON object", "Configure hooks.Stop with the completeness command hook.")
    stop_entries = hooks.get("Stop")
    if not isinstance(stop_entries, list) or not stop_entries:
        return incompatible(relative, "file", "hooks.Stop must be a non-empty list", "Configure a Stop command hook for scripts/completeness_hook.py.")

    commands: list[str] = []
    for entry_index, entry in enumerate(stop_entries):
        if not isinstance(entry, dict):
            return incompatible(relative, "file", f"hooks.Stop[{entry_index}] must be an object", "Use object entries in hooks.Stop.")
        entry_hooks = entry.get("hooks")
        if not isinstance(entry_hooks, list):
            continue
        for hook_index, hook in enumerate(entry_hooks):
            if not isinstance(hook, dict):
                return incompatible(relative, "file", f"hooks.Stop[{entry_index}].hooks[{hook_index}] must be an object", "Use object command hooks in hooks.Stop[].hooks[].")
            if hook.get("type") != "command":
                continue
            command = hook.get("command")
            if not isinstance(command, str) or not command.strip():
                return incompatible(relative, "file", "Stop command hook command must be a non-empty string", "Set the command to run scripts/completeness_hook.py through python.")
            commands.append(command)

    if not commands:
        return incompatible(relative, "file", "hooks.Stop must contain a command hook", "Add a command hook for scripts/completeness_hook.py.")

    expected_script = (root / "scripts" / "completeness_hook.py").resolve()
    if not expected_script.is_file():
        return missing("scripts/completeness_hook.py", "file", "missing scripts/completeness_hook.py", "Restore the Stop hook script from the LecturAL distribution.")

    for command in commands:
        normalized_command = command.replace("\\", "/")
        required_quoted_path = '"${CLAUDE_PLUGIN_ROOT}/scripts/completeness_hook.py"'
        if required_quoted_path not in normalized_command:
            continue
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            continue
        if not tokens or tokens[0] not in {"python", "py"}:
            continue
        hook_token = next(
            (
                token
                for token in tokens[1:]
                if "${CLAUDE_PLUGIN_ROOT}" in token
                and "scripts/completeness_hook.py" in token.replace("\\", "/")
            ),
            None,
        )
        if hook_token is None:
            continue
        resolved = Path(hook_token.replace("${CLAUDE_PLUGIN_ROOT}", str(root))).resolve()
        if resolved == expected_script:
            return ok(relative, "file", "Stop command hook targets scripts/completeness_hook.py")

    return incompatible(
        relative,
        "file",
        "Stop command must run python/py with quoted ${CLAUDE_PLUGIN_ROOT}/scripts/completeness_hook.py",
        "Use `python \"${CLAUDE_PLUGIN_ROOT}/scripts/completeness_hook.py\"`.",
    )

def _plugin_item(root: Path) -> DoctorItem:
    path = _rel(root, ".claude-plugin/plugin.json")
    if not path.is_file():
        return missing(str(path.relative_to(root)), "plugin", "plugin manifest is missing", "Restore `.claude-plugin/plugin.json`.")
    try:
        data = _load_json(path)
    except Exception as exc:  # noqa: BLE001
        return incompatible(".claude-plugin/plugin.json", "plugin", f"invalid JSON manifest: {type(exc).__name__}: {exc}", "Fix plugin.json to be valid JSON.")
    if data.get("name") != "lectural":
        return incompatible(".claude-plugin/plugin.json", "plugin", "plugin name is not `lectural`", "Set plugin.json name to `lectural`.")
    hooks = data.get("hooks")
    if not isinstance(hooks, str) or not hooks.strip():
        return incompatible(".claude-plugin/plugin.json", "plugin", "plugin hooks path is missing", "Set hooks to `./hooks/hooks.json`.")
    hooks_path = (root / hooks).resolve()
    try:
        hooks_path.relative_to(root.resolve())
    except ValueError:
        return incompatible(".claude-plugin/plugin.json", "plugin", f"hooks path escapes repository root: {hooks}", "Use a relative hooks path inside the plugin root.")
    if not hooks_path.is_file():
        return missing("hooks/hooks.json", "plugin", f"plugin hooks path does not exist: {hooks}", "Restore the hooks file referenced by plugin.json.")
    return ok(".claude-plugin/plugin.json", "plugin", f"name lectural; hooks {hooks}")


def _marketplace_item(root: Path) -> DoctorItem:
    path = _rel(root, ".claude-plugin/marketplace.json")
    if not path.is_file():
        return missing(str(path.relative_to(root)), "plugin", "marketplace manifest is missing", "Restore `.claude-plugin/marketplace.json`.")
    try:
        data = _load_json(path)
    except Exception as exc:  # noqa: BLE001
        return incompatible(".claude-plugin/marketplace.json", "plugin", f"invalid JSON manifest: {type(exc).__name__}: {exc}", "Fix marketplace.json to be valid JSON.")
    if data.get("name") != "lectural":
        return incompatible(".claude-plugin/marketplace.json", "plugin", "marketplace name is not `lectural`", "Set marketplace.json name to `lectural`.")
    plugins = data.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        return incompatible(".claude-plugin/marketplace.json", "plugin", "plugins must be a non-empty list", "Add a plugins[] entry for LecturAL.")
    for index, plugin in enumerate(plugins):
        if not isinstance(plugin, dict):
            return incompatible(".claude-plugin/marketplace.json", "plugin", f"plugins[{index}] is not an object", "Use object entries in plugins[].")
        if plugin.get("name") != "lectural":
            return incompatible(".claude-plugin/marketplace.json", "plugin", f"plugins[{index}].name is not `lectural`", "Set every plugin entry name to `lectural`.")
        if plugin.get("source") != "./":
            return incompatible(".claude-plugin/marketplace.json", "plugin", f"plugins[{index}].source is {plugin.get('source')!r}, expected './'", "Set every plugin entry source exactly to `./`.")
    return ok(".claude-plugin/marketplace.json", "plugin", "marketplace entry points at ./")


def _items(root: Path) -> list[DoctorItem]:
    items = [_python_core_item()]
    items.extend(_python_dep_item(module, package, specifier) for module, package, specifier in RUN_PYTHON_REQUIREMENTS)
    items.extend(_binary_item(name) for name in ("ffmpeg", "yt-dlp"))
    items.extend(_file_item(root, relative) for relative in AGENT_FILES)
    items.append(_hook_command_item(root))
    items.append(_plugin_item(root))
    items.append(_marketplace_item(root))
    return items


def exit_code_for(items: Iterable[DoctorItem]) -> int:
    statuses = {item.status for item in items}
    if STATUS_UNFIXABLE in statuses:
        return 1
    if statuses - {STATUS_OK}:
        return 2
    return 0


def overall_status_for(exit_code: int) -> str:
    if exit_code == 0:
        return "ready"
    if exit_code == 2:
        return "user-action"
    return "internal-unfixable"


def build_report(root: str | Path | None = None, actions: list[FixAction] | None = None) -> dict:
    try:
        items = _items(_root(root))
    except Exception as exc:  # noqa: BLE001 - doctor runtime failure must become exit 1
        items = [unfixable("doctor", "internal", f"doctor runtime failure: {type(exc).__name__}: {exc}", "Report this LecturAL doctor bug with the traceback context.")]
    exit_code = exit_code_for(items)
    report = {
        "schema_version": SCHEMA_VERSION,
        "items": [asdict(item) for item in items],
        "overall_status": overall_status_for(exit_code),
        "exit_code": exit_code,
    }
    if actions:
        report["actions"] = [asdict(action) for action in actions]
    return report


def _item_status(report: dict, name: str, kind: str) -> str | None:
    for item in report["items"]:
        if item["name"] == name and item["kind"] == kind:
            return item["status"]
    return None


def _run_command(command: list[str]) -> FixAction:
    try:
        completed = subprocess.run(command, check=False, text=True, capture_output=True, timeout=300)
    except FileNotFoundError as exc:
        return FixAction(name=command[0], command=command, outcome="failed", detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        return FixAction(name=command[0], command=command, outcome="failed", detail=f"{type(exc).__name__}: {exc}")
    output = " ".join(part.strip() for part in (completed.stdout, completed.stderr) if part and part.strip())
    detail = f"exit {completed.returncode}" + (f": {output[:500]}" if output else "")
    return FixAction(name=command[0], command=command, outcome="ok" if completed.returncode == 0 else "failed", detail=detail)


def _attempt_yt_dlp() -> FixAction:
    return _run_command(["uv", "tool", "install", "yt-dlp"])


def _attempt_ffmpeg() -> FixAction:
    system = platform.system().lower()
    if system == "windows" and shutil.which("winget"):
        return _run_command([
            "winget",
            "install",
            "--id",
            "Gyan.FFmpeg",
            "-e",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ])
    if system == "darwin" and shutil.which("brew"):
        return _run_command(["brew", "install", "ffmpeg"])
    if system == "linux" and shutil.which("apt-get"):
        return FixAction(
            name="ffmpeg",
            command=None,
            outcome="hint",
            detail="apt-get is present, but doctor will not start an admin install; run `sudo apt-get install ffmpeg` if appropriate.",
        )
    return FixAction(
        name="ffmpeg",
        command=None,
        outcome="hint",
        detail="Install ffmpeg with your OS package manager and ensure it is on PATH.",
    )


def run(fix: bool = False, root: str | Path | None = None, max_passes: int = 2) -> dict:
    actions: list[FixAction] = []
    attempted: set[str] = set()
    if fix:
        for _ in range(max_passes):
            report = build_report(root, actions)
            if report["exit_code"] in (0, 1):
                break
            if _item_status(report, "yt-dlp", "binary") == STATUS_MISSING and "yt-dlp" not in attempted:
                actions.append(_attempt_yt_dlp())
                attempted.add("yt-dlp")
                continue
            if _item_status(report, "ffmpeg", "binary") == STATUS_MISSING and "ffmpeg" not in attempted:
                actions.append(_attempt_ffmpeg())
                attempted.add("ffmpeg")
                continue
            break
    return build_report(root, actions)


def print_report(report: dict, *, json_output: bool = False, stream=None) -> None:
    stream = stream or sys.stdout
    if json_output:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        print(file=stream)
        return

    print(f"LecturAL doctor: {report['overall_status']} (exit {report['exit_code']})", file=stream)
    for item in report["items"]:
        if item["status"] == STATUS_OK:
            print(f"[ok] {item['kind']} {item['name']}: {item['detail']}", file=stream)
        else:
            print(f"[{item['status']}] {item['kind']} {item['name']}: {item['detail']}", file=stream)
            if item.get("hint"):
                print(f"  hint: {item['hint']}", file=stream)
    for action in report.get("actions", []):
        command = " ".join(action["command"]) if action.get("command") else "manual"
        print(f"[fix:{action['outcome']}] {command}: {action['detail']}", file=stream)


__all__ = [
    "DoctorItem",
    "FixAction",
    "STATUS_OK",
    "STATUS_MISSING",
    "STATUS_INCOMPATIBLE",
    "STATUS_UNFIXABLE",
    "build_report",
    "exit_code_for",
    "overall_status_for",
    "print_report",
    "run",
]
