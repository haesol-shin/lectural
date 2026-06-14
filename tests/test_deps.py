"""Tests for dependency install hints and Python preflight checks."""

import re
from pathlib import Path
from types import SimpleNamespace

from lectural import deps


_BINARY_NAMES = ("ffmpeg", "yt-dlp", "tesseract")
_OS_LABELS = ("win:", "linux:", "macos:")


def _fake_importer(monkeypatch, modules):
    imported: list[str] = []

    def fake_import_module(name):
        imported.append(name)
        value = modules.get(name, ImportError(f"No module named {name}"))
        if isinstance(value, BaseException):
            raise value
        return SimpleNamespace(__version__=value)

    monkeypatch.setattr(deps.importlib, "import_module", fake_import_module)
    return imported


def _fake_package_metadata(monkeypatch, versions, providers=None):
    def fake_version(name):
        if name not in versions:
            raise deps.importlib_metadata.PackageNotFoundError(name)
        return versions[name]

    monkeypatch.setattr(deps.importlib_metadata, "version", fake_version)
    monkeypatch.setattr(deps.importlib_metadata, "packages_distributions", lambda: providers or {})


def test_missing_binary_status_details_include_per_os_install_labels(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)

    for name in _BINARY_NAMES:
        status = deps.binary_status(name)

        assert status.available is False
        assert all(label in status.detail for label in _OS_LABELS)


def test_python_status_imports_module_and_accepts_compatible_version(monkeypatch):
    imported = _fake_importer(monkeypatch, {"paddleocr": "2.7.1"})

    status = deps.python_status("paddleocr")

    assert imported == ["paddleocr"]
    assert status == deps.DepStatus(name="paddleocr", kind="python", available=True)


def test_python_status_failed_import_is_unavailable(monkeypatch):
    _fake_importer(monkeypatch, {"paddleocr": ImportError("missing native dependency")})

    status = deps.python_status("paddleocr")

    assert status.available is False
    assert "lectural[run]" in status.detail
    assert "Import failed: ImportError: missing native dependency" in status.detail


def test_python_status_incompatible_version_is_unavailable(monkeypatch):
    _fake_package_metadata(
        monkeypatch,
        {"opencv-python": "4.8.0.76"},
        {"cv2": ["opencv-python"]},
    )
    _fake_importer(monkeypatch, {"cv2": "4.8.0"})

    status = deps.python_status("cv2")

    assert status.available is False
    assert "4.8.0" in status.detail
    assert "opencv-python>=4.5,<=4.6.0.66" in status.detail


def test_preflight_imports_and_version_checks_ocr_runtime_dependencies(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: f"/fake/bin/{name}")
    imported = _fake_importer(
        monkeypatch,
        {
            "youtube_transcript_api": "0.6.2",
            "faster_whisper": "1.0.0",
            "numpy": "1.26.4",
            "paddleocr": "2.7.3",
            "paddle": "3.0.0",
            "cv2": "4.6.0",
            "webrtcvad": "2.0.10",
        },
    )
    _fake_package_metadata(
        monkeypatch,
        {"opencv-python": "4.6.0.66"},
        {"cv2": ["opencv-python"]},
    )

    statuses = {status.name: status for status in deps.preflight(require_ocr=True)}

    assert {"numpy", "paddleocr", "paddle", "cv2"}.issubset(imported)
    assert statuses["numpy"].available is True
    assert statuses["paddleocr"].available is True
    assert statuses["cv2"].available is True
    assert statuses["paddle"].available is False
    assert "paddlepaddle>=2.6,<3" in statuses["paddle"].detail


def test_python_status_cv2_requires_expected_distribution_provider(monkeypatch):
    _fake_importer(monkeypatch, {"cv2": "4.6.0"})
    _fake_package_metadata(
        monkeypatch,
        {},
        {"cv2": ["opencv-python-headless"]},
    )

    status = deps.python_status("cv2")

    assert status.available is False
    assert "provider check failed" in status.detail
    assert "opencv-python-headless" in status.detail
    assert "expected distribution `opencv-python`" in status.detail


def test_python_status_cv2_requires_provider_metadata_even_when_version_matches(monkeypatch):
    _fake_importer(monkeypatch, {"cv2": "4.6.0"})
    _fake_package_metadata(
        monkeypatch,
        {"opencv-python": "4.6.0.66"},
        {},
    )

    status = deps.python_status("cv2")

    assert status.available is False
    assert "provider check failed" in status.detail
    assert "provider metadata did not list any distribution" in status.detail
    assert "expected distribution `opencv-python`" in status.detail


def test_python_status_cv2_requires_mapped_distribution_metadata(monkeypatch):
    _fake_importer(monkeypatch, {"cv2": "4.6.0"})
    _fake_package_metadata(
        monkeypatch,
        {},
        {"cv2": ["opencv-python"]},
    )

    status = deps.python_status("cv2")

    assert status.available is False
    assert "`cv2` imported but version could not be determined" in status.detail
    assert "opencv-python" in status.detail


def test_python_status_cv2_rejects_active_provider_version_mismatch(monkeypatch):
    _fake_importer(monkeypatch, {"cv2": "4.11.0"})
    _fake_package_metadata(
        monkeypatch,
        {"opencv-python": "4.6.0.66"},
        {"cv2": ["opencv-python"]},
    )

    status = deps.python_status("cv2")

    assert status.available is False
    assert "provider check failed" in status.detail
    assert "`cv2` imported as version 4.11.0" in status.detail
    assert "`opencv-python` distribution is 4.6.0.66" in status.detail
    assert "another provider may be active" in status.detail


def test_python_status_cv2_accepts_multiple_constrained_providers_when_expected_provider_is_present(monkeypatch):
    _fake_importer(monkeypatch, {"cv2": "4.6.0"})
    _fake_package_metadata(
        monkeypatch,
        {"opencv-python": "4.6.0.66"},
        {"cv2": ["opencv-contrib-python", "opencv-python", "opencv-python-headless"]},
    )

    status = deps.python_status("cv2")

    assert status == deps.DepStatus(name="cv2", kind="python", available=True)


def test_runtime_lock_keeps_cv2_and_onnxruntime_constraints():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "opencv-contrib-python<=4.6.0.66" in pyproject
    assert "opencv-python-headless<=4.6.0.66" in pyproject
    assert "onnxruntime<1.24" in pyproject
    assert '"setuptools>=68,<81"' in pyproject

    lock = Path("uv.lock").read_text(encoding="utf-8")
    package_versions: dict[str, list[str]] = {}
    for name, version in re.findall(
        r'\[\[package\]\]\s+name = "([^"]+)"\s+version = "([^"]+)"',
        lock,
    ):
        package_versions.setdefault(name, []).append(version)

    assert package_versions["opencv-python"] == ["4.6.0.66"]
    for name in ("opencv-contrib-python", "opencv-python-headless"):
        assert all(
            deps._compare_versions(version, "4.6.0.66") <= 0 for version in package_versions.get(name, [])
        )
    assert all(deps._compare_versions(version, "1.24") < 0 for version in package_versions.get("onnxruntime", []))
    assert "onnxruntime-1.23.2-cp310-cp310-win_amd64.whl" in lock
    assert '{ name = "setuptools", marker = "extra == \'run\'", specifier = ">=68,<81" }' in lock
