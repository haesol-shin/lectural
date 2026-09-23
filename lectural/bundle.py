"""Load a v2 evidence bundle without trusting its recorded filesystem paths."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any

from .config import EXTRACTION_CONTRACT_VERSION, EXTRACTION_SCHEMA_VERSION


class BundleError(ValueError):
    """A bounded bundle-loading failure suitable for CLI output."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


@dataclass(frozen=True)
class Bundle:
    """A loaded manifest with bundle-local, safely rebased artifact paths."""

    root: str
    evidence_path: str
    manifest: dict[str, Any]
    artifact_paths: dict[str, str | None]
    frame_paths: tuple[str | None, ...]
    containment_valid: bool


def _contained(root: str, path: str) -> bool:
    try:
        return os.path.commonpath((root, path)) == root
    except (OSError, ValueError):
        return False


def _rebase_path(value: object, recorded_root: str, bundle_root: str) -> str | None:
    if not isinstance(value, str) or not value or not os.path.isabs(value):
        return None
    recorded = os.path.realpath(os.path.abspath(value))
    if not _contained(recorded_root, recorded):
        return None
    relative = os.path.relpath(recorded, recorded_root)
    rebased = os.path.realpath(os.path.join(bundle_root, relative))
    if not _contained(bundle_root, rebased):
        return None
    return rebased


def load_bundle(path: str | os.PathLike[str]) -> Bundle:
    """Load a bundle directory or its evidence.json manifest.

    Artifact and frame locations in v2 manifests are absolute paths. Their
    location relative to the recorded output directory is retained, then
    mapped onto the bundle's actual directory so copied bundles remain usable.
    """
    supplied = os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(path))))
    if os.path.isdir(supplied):
        root = supplied
        evidence_path = os.path.join(root, "evidence.json")
    else:
        evidence_path = supplied
        root = os.path.dirname(evidence_path)
    root = os.path.realpath(root)
    evidence_path = os.path.realpath(evidence_path)
    if not _contained(root, evidence_path):
        raise BundleError("BUNDLE_CONTAINMENT", "The evidence manifest is outside its bundle.")
    try:
        with open(evidence_path, "r", encoding="utf-8") as stream:
            manifest = json.load(stream)
    except FileNotFoundError as exc:
        raise BundleError("BUNDLE_UNAVAILABLE", "The evidence manifest is unavailable.") from exc
    except (OSError, UnicodeError) as exc:
        raise BundleError("BUNDLE_UNREADABLE", "The evidence manifest cannot be read.") from exc
    except json.JSONDecodeError as exc:
        raise BundleError("BUNDLE_JSON_INVALID", "The evidence manifest is not valid JSON.") from exc
    if not isinstance(manifest, dict):
        raise BundleError("BUNDLE_JSON_INVALID", "The evidence manifest must be a JSON object.")
    if (
        type(manifest.get("contract_version")) is not int
        or manifest.get("contract_version") != EXTRACTION_CONTRACT_VERSION
        or type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != EXTRACTION_SCHEMA_VERSION
    ):
        raise BundleError("BUNDLE_VERSION_UNSUPPORTED", "The evidence bundle version is unsupported.")

    artifacts = manifest.get("artifacts")
    recorded_root = artifacts.get("output_dir") if isinstance(artifacts, dict) else None
    if isinstance(recorded_root, str) and recorded_root and os.path.isabs(recorded_root):
        recorded_root = os.path.realpath(os.path.abspath(recorded_root))
    else:
        recorded_root = ""

    artifact_paths: dict[str, str | None] = {}
    containment_valid = bool(recorded_root and os.path.isabs(recorded_root))
    if isinstance(artifacts, dict):
        for key in ("evidence", "transcript", "frames_dir"):
            value = artifacts.get(key)
            if key == "frames_dir" and value is None:
                artifact_paths[key] = None
                continue
            rebased = _rebase_path(value, recorded_root, root) if recorded_root else None
            artifact_paths[key] = rebased
            if rebased is None:
                containment_valid = False
    else:
        artifact_paths = {"evidence": None, "transcript": None, "frames_dir": None}
        containment_valid = False

    raw_frames = manifest.get("frames")
    frame_paths: list[str | None] = []
    if isinstance(raw_frames, list):
        for frame in raw_frames:
            value = frame.get("path") if isinstance(frame, dict) else None
            rebased = _rebase_path(value, recorded_root, root) if recorded_root else None
            frame_paths.append(rebased)
            if rebased is None:
                containment_valid = False
    else:
        containment_valid = False

    return Bundle(
        root=root,
        evidence_path=evidence_path,
        manifest=manifest,
        artifact_paths=artifact_paths,
        frame_paths=tuple(frame_paths),
        containment_valid=containment_valid,
    )


__all__ = ["Bundle", "BundleError", "load_bundle"]
