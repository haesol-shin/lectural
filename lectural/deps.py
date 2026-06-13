"""External dependency preflight.

LecturAL relies on external binaries (ffmpeg, yt-dlp) and optional Python
packages (faster-whisper, paddleocr, opencv). None are imported at module
load time. These helpers detect what is available and raise clear, actionable
errors when a required dependency is missing, so failures point at the fix
instead of a deep ImportError/FileNotFoundError stack.
"""

from __future__ import annotations

import importlib
from importlib import metadata as importlib_metadata
import shutil
from dataclasses import dataclass


class DependencyError(RuntimeError):
    """Raised when a required external dependency is missing."""


class ProviderMismatchError(RuntimeError):
    """Raised when an imported module does not match its mapped distribution."""


@dataclass(frozen=True)
class DepStatus:
    name: str
    kind: str  # "binary" | "python"
    available: bool
    detail: str = ""


@dataclass(frozen=True)
class PythonRequirement:
    package: str
    specifier: str


# Human-facing install hints (kept English per project convention).
_BINARY_HINTS = {
    "ffmpeg": "Install ffmpeg and put it on PATH. win: winget install Gyan.FFmpeg | linux: apt install ffmpeg (or dnf install ffmpeg) | macos: brew install ffmpeg",
    "yt-dlp": "Install yt-dlp on PATH. win: winget install yt-dlp.yt-dlp (or uv tool install yt-dlp) | linux: uv tool install yt-dlp (or apt install yt-dlp) | macos: brew install yt-dlp",
    "tesseract": "Optional OCR fallback on PATH. win: winget install UB-Mannheim.TesseractOCR | linux: apt install tesseract-ocr (or dnf install tesseract) | macos: brew install tesseract",
}
_PYTHON_HINTS = {
    "faster_whisper": 'Install run extras: `uv pip install "lectural[run]"`.',
    "numpy": 'Install compatible NumPy: `uv pip install "numpy>=1.24,<2"` or install run extras: `uv pip install "lectural[run]"`.',
    "paddleocr": 'Install compatible PaddleOCR: `uv pip install "paddleocr>=2.7,<3"` or install run extras: `uv pip install "lectural[run]"`.',
    "paddle": 'Install compatible PaddlePaddle: `uv pip install "paddlepaddle>=2.6,<3"` or install run extras: `uv pip install "lectural[run]"`.',
    "cv2": 'Install compatible OpenCV: `uv pip install "opencv-python>=4.5,<=4.6.0.66"` or install run extras: `uv pip install "lectural[run]"`.',
    "youtube_transcript_api": 'Install run extras: `uv pip install "lectural[run]"`.',
    "webrtcvad": 'Optional VAD backend: `uv pip install webrtcvad`.',
}
_PYTHON_REQUIREMENTS = {
    "numpy": PythonRequirement("numpy", ">=1.24,<2"),
    "paddleocr": PythonRequirement("paddleocr", ">=2.7,<3"),
    "paddle": PythonRequirement("paddlepaddle", ">=2.6,<3"),
    "cv2": PythonRequirement("opencv-python", ">=4.5,<=4.6.0.66"),
}


def has_binary(name: str) -> bool:
    """True when an executable named `name` is resolvable on PATH."""
    return shutil.which(name) is not None


def _parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for raw_part in version.replace("-", ".").replace("+", ".").split("."):
        digits = ""
        for char in raw_part:
            if not char.isdigit():
                break
            digits += char
        if digits:
            parts.append(int(digits))
        elif parts:
            break
    return tuple(parts)


def _compare_versions(left: str, right: str) -> int:
    left_parts = _parse_version(left)
    right_parts = _parse_version(right)
    width = max(len(left_parts), len(right_parts))
    left_padded = left_parts + (0,) * (width - len(left_parts))
    right_padded = right_parts + (0,) * (width - len(right_parts))
    return (left_padded > right_padded) - (left_padded < right_padded)


def _satisfies_version(version: str, specifier: str) -> bool:
    for clause in specifier.split(","):
        clause = clause.strip()
        if not clause:
            continue
        op = next((candidate for candidate in (">=", "<=", "==", ">", "<") if clause.startswith(candidate)), None)
        if op is None:
            continue
        target = clause[len(op) :].strip()
        comparison = _compare_versions(version, target)
        if op == ">=" and comparison < 0:
            return False
        if op == "<=" and comparison > 0:
            return False
        if op == "==" and comparison != 0:
            return False
        if op == ">" and comparison <= 0:
            return False
        if op == "<" and comparison >= 0:
            return False
    return True

def _release_prefix_matches(module_version: str, distribution_version: str) -> bool:
    module_parts = _parse_version(module_version)
    distribution_parts = _parse_version(distribution_version)
    if not module_parts or not distribution_parts:
        return module_version == distribution_version
    width = min(len(module_parts), len(distribution_parts))
    return module_parts[:width] == distribution_parts[:width]


def _module_providers(module: str) -> tuple[str, ...]:
    try:
        return tuple(importlib_metadata.packages_distributions().get(module, ()))
    except Exception:
        return ()


def _module_version(module: str, package: str, imported: object) -> str | None:
    if package != module:
        providers = _module_providers(module)
        if not providers:
            raise ProviderMismatchError(
                f"`{module}` provider metadata did not list any distribution; expected distribution `{package}`"
            )
        if package not in providers:
            raise ProviderMismatchError(
                f"`{module}` is provided by {', '.join(sorted(providers))}, not expected distribution `{package}`"
            )

        package_version = importlib_metadata.version(package)
        module_version = getattr(imported, "__version__", None)
        if module_version is not None and not _release_prefix_matches(str(module_version), package_version):
            raise ProviderMismatchError(
                f"`{module}` imported as version {module_version}, but `{package}` distribution is {package_version}; "
                "another provider may be active"
            )
        return package_version

    version = getattr(imported, "__version__", None)
    if version is not None:
        return str(version)
    return importlib_metadata.version(package)

def has_python_module(module: str) -> bool:
    """True when a Python module can be imported successfully."""
    return python_status(module).available


def binary_status(name: str) -> DepStatus:
    ok = has_binary(name)
    return DepStatus(
        name=name,
        kind="binary",
        available=ok,
        detail="" if ok else _BINARY_HINTS.get(name, f"Install `{name}` and add it to PATH."),
    )


def python_status(
    module: str,
    *,
    package: str | None = None,
    specifier: str | None = None,
) -> DepStatus:
    requirement = _PYTHON_REQUIREMENTS.get(module)
    package_name = package or (requirement.package if requirement else module)
    version_specifier = specifier if specifier is not None else (requirement.specifier if requirement else None)
    hint = _PYTHON_HINTS.get(module, f"Install the `{package_name}` package.")

    try:
        imported = importlib.import_module(module)
    except Exception as exc:
        return DepStatus(
            name=module,
            kind="python",
            available=False,
            detail=f"{hint} Import failed: {exc.__class__.__name__}: {exc}",
        )

    if version_specifier:
        try:
            version = _module_version(module, package_name, imported)
        except importlib_metadata.PackageNotFoundError:
            return DepStatus(
                name=module,
                kind="python",
                available=False,
                detail=f"`{module}` imported but version could not be determined. {hint}",
            )
        except ProviderMismatchError as exc:
            return DepStatus(
                name=module,
                kind="python",
                available=False,
                detail=f"`{module}` imported but provider check failed: {exc}. {hint}",
            )
        except Exception as exc:
            return DepStatus(
                name=module,
                kind="python",
                available=False,
                detail=f"`{module}` imported but version could not be checked: {exc.__class__.__name__}: {exc}. {hint}",
            )
        if version is None:
            return DepStatus(
                name=module,
                kind="python",
                available=False,
                detail=f"`{module}` imported but version could not be determined. {hint}",
            )
        if not _satisfies_version(version, version_specifier):
            return DepStatus(
                name=module,
                kind="python",
                available=False,
                detail=f"`{module}` version {version} does not satisfy {package_name}{version_specifier}. {hint}",
            )

    return DepStatus(name=module, kind="python", available=True)


def require_binary(name: str) -> None:
    """Raise DependencyError with an install hint if `name` is not on PATH."""
    st = binary_status(name)
    if not st.available:
        raise DependencyError(f"Required binary `{name}` not found. {st.detail}")


def require_python_module(module: str) -> None:
    """Raise DependencyError with an install hint if `module` is unimportable."""
    st = python_status(module)
    if not st.available:
        raise DependencyError(f"Required Python module `{module}` not installed. {st.detail}")


def preflight(require_stt: bool = False, require_ocr: bool = False) -> list[DepStatus]:
    """Return the status of every dependency LecturAL may use.

    This never raises; the caller decides which missing pieces are fatal for
    the requested run (e.g. captions-only runs do not need faster-whisper).
    """
    statuses = [
        binary_status("ffmpeg"),
        binary_status("yt-dlp"),
        binary_status("tesseract"),
        python_status("youtube_transcript_api"),
        python_status("faster_whisper"),
        python_status("numpy"),
        python_status("paddleocr"),
        python_status("paddle"),
        python_status("cv2"),
        python_status("webrtcvad"),
    ]
    return statuses


def assert_acquisition_ready() -> None:
    """ffmpeg + yt-dlp are the hard requirement for fetching from YouTube."""
    require_binary("yt-dlp")
    require_binary("ffmpeg")
