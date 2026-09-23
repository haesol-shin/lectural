"""Read-only inventory of a v2 evidence bundle."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import stat
from typing import Any

from . import __version__
from .bundle import Bundle, BundleError, load_bundle
from .config import EXTRACTION_CONTRACT_VERSION, EXTRACTION_SCHEMA_VERSION


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _size(path: str | None) -> int | None:
    if path is None:
        return None
    try:
        return os.path.getsize(path) if os.path.isfile(path) else None
    except OSError:
        return None


def _directory_size(path: str | None) -> int | None:
    if path is None or not os.path.isdir(path):
        return None
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(root, name))]
        for name in files:
            file_path = os.path.join(root, name)
            try:
                if not stat.S_ISLNK(os.lstat(file_path).st_mode):
                    total += os.path.getsize(file_path)
            except OSError:
                continue
    return total


def inventory(bundle: Bundle) -> dict[str, Any]:
    """Build a path-free, JSON-ready inventory without modifying the bundle."""
    manifest = bundle.manifest
    source = _mapping(manifest.get("source"))
    speech = _mapping(manifest.get("speech"))
    transcript = _mapping(manifest.get("transcript"))
    segments = _items(transcript.get("segments"))
    first = _mapping(segments[0]) if segments else {}
    last = _mapping(segments[-1]) if segments else {}
    frames = _items(manifest.get("frames"))
    extraction = _mapping(manifest.get("extraction"))
    ocr = _mapping(extraction.get("ocr"))
    completeness = {
        "speech": _mapping(extraction.get("speech_completeness")).get("status"),
        "visual": _mapping(extraction.get("visual_completeness")).get("status"),
        "timestamps": _mapping(extraction.get("timestamp_integrity")).get("status"),
    }
    reasons = _items(extraction.get("reasons"))
    reason_codes = [
        item.get("code") for item in reasons
        if isinstance(item, dict) and isinstance(item.get("code"), str)
    ]
    artifacts = _mapping(manifest.get("artifacts"))
    resources = _mapping(manifest.get("resources"))
    stages = _mapping(resources.get("stages"))
    duration = source.get("duration_sec")

    return {
        "source": {
            "kind": source.get("kind"),
            "title": source.get("title"),
            "id": source.get("id"),
            "duration_sec": duration,
        },
        "speech": {
            "source": speech.get("source"),
            "language": speech.get("language"),
            "model": speech.get("model"),
            "fallback_code": _mapping(speech.get("fallback")).get("code"),
        },
        "segments": {
            "count": len(segments),
            "first_start_sec": first.get("start"),
            "last_end_sec": last.get("end"),
        },
        "frames": {
            "count": len(frames),
            "ocr_status": ocr.get("status"),
            "ocr_engine": ocr.get("engine"),
        },
        "completeness": completeness,
        "extraction": {"status": extraction.get("status"), "reason_codes": reason_codes},
        "versions": {
            "contract_version": manifest.get("contract_version"),
            "schema_version": manifest.get("schema_version"),
            "tool": manifest.get("tool"),
            "tool_version": manifest.get("tool_version"),
        },
        "artifacts": {
            "evidence_bytes": _size(bundle.evidence_path),
            "transcript_bytes": _size(bundle.artifact_paths.get("transcript")),
            "frames_bytes": _directory_size(bundle.artifact_paths.get("frames_dir")),
        },
        "resources": {
            "wall_sec": resources.get("wall_sec"),
            "stages": {key: stages.get(key) for key in ("speech", "frames", "dedupe", "ocr")},
            "peak_rss_mb": resources.get("peak_rss_mb"),
        },
    }


def inspect_bundle(path: str) -> dict[str, Any]:
    """Load and inventory a bundle. Loading errors are raised as BundleError."""
    return inventory(load_bundle(path))


def _display_value(value: object, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}{suffix}"
    return f"{value}{suffix}"


def render_inventory(result: dict[str, Any]) -> str:
    """Render the concise aligned human-readable inventory."""
    source = result["source"]
    speech = result["speech"]
    segments = result["segments"]
    frames = result["frames"]
    complete = result["completeness"]
    extraction = result["extraction"]
    versions = result["versions"]
    artifacts = result["artifacts"]
    resources = result["resources"]
    fallback = speech.get("fallback_code") or "none"
    span = "-"
    if segments["count"]:
        span = f"{_display_value(segments['first_start_sec'], 's')} – {_display_value(segments['last_end_sec'], 's')}"
    lines = [
        f"Source:          {source.get('kind') or '-'} | {source.get('title') or '-'} | {source.get('id') or '-'}",
        f"Duration:        {_display_value(source.get('duration_sec'), 's')}",
        f"Speech:          {speech.get('source') or '-'} | {speech.get('language') or '-'} | model={speech.get('model') or '-'} | fallback={fallback}",
        f"Segments:        {segments['count']} | {span}",
        f"Frames:          {frames['count']} | OCR={frames.get('ocr_status') or '-'} ({frames.get('ocr_engine') or '-'})",
        f"Completeness:    speech={complete['speech'] or '-'} | visual={complete['visual'] or '-'} | timestamps={complete['timestamps'] or '-'}",
        f"Extraction:      {extraction.get('status') or '-'} | reasons={','.join(extraction['reason_codes']) or 'none'}",
        f"Versions:        contract={versions.get('contract_version')} schema={versions.get('schema_version')} tool={versions.get('tool') or '-'} {versions.get('tool_version') or '-'}",
        f"Artifact sizes:  evidence={_display_value(artifacts['evidence_bytes'], ' B')} transcript={_display_value(artifacts['transcript_bytes'], ' B')} frames={_display_value(artifacts['frames_bytes'], ' B')}",
        f"Resources:       wall={_display_value(resources.get('wall_sec'), 's')} | stages={resources['stages']} | peak_rss={_display_value(resources.get('peak_rss_mb'), ' MiB')}",
    ]
    return "\n".join(lines)


def response(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "contract_version": EXTRACTION_CONTRACT_VERSION,
        "tool": "lectural",
        "tool_version": __version__,
        "status": "ok",
        "result": result,
        "errors": [],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def error_response(error: BundleError) -> dict[str, Any]:
    return {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "contract_version": EXTRACTION_CONTRACT_VERSION,
        "tool": "lectural",
        "tool_version": __version__,
        "status": "error",
        "result": None,
        "errors": [{"code": error.code, "message": error.safe_message}],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


__all__ = ["error_response", "inspect_bundle", "inventory", "render_inventory", "response"]
