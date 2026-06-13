"""Tests for dependency install hints."""

from lectural import deps


_BINARY_NAMES = ("ffmpeg", "yt-dlp", "tesseract")
_OS_LABELS = ("win:", "linux:", "macos:")


def test_missing_binary_status_details_include_per_os_install_labels(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)

    for name in _BINARY_NAMES:
        status = deps.binary_status(name)

        assert status.available is False
        assert all(label in status.detail for label in _OS_LABELS)
