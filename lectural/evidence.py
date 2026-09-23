"""Public, versioned extraction response and evidence-manifest helpers.

This module is deliberately independent from the notes/synthesis contract.  It
owns only deterministic extraction facts and safe paths; assignment meaning and
project eligibility belong to consumers.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from typing import Iterable

from . import __version__
from .config import EXTRACTION_CONTRACT_VERSION, EXTRACTION_SCHEMA_VERSION


class ContractError(ValueError):
    """A bounded, user-actionable contract failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


_FAILURE_MESSAGES = {
    "OUTPUT_EXISTS": "The requested output directory already exists.",
    "OUTPUT_PATH_ESCAPE": "An artifact path would escape the requested output directory.",
    "SOURCE_INVALID": "The source is not a supported YouTube URL or local media file.",
    "SOURCE_UNAVAILABLE": "The source could not be accessed for extraction.",
    "OCR_FAILED": "Requested OCR failed; visual evidence frames were retained when available.",
    "TIMESTAMP_INVALID": "Extraction produced invalid or inconsistent timestamps.",
    "SPEECH_INCOMPLETE": "Speech coverage contains an untranscribed interval.",
    "VISUAL_INCOMPLETE": "Visual timeline coverage contains an uncovered interval.",
    "OCR_INCOMPLETE": "OCR did not annotate every required slide frame.",
    "ARTIFACT_INCOMPLETE": "A required extraction artifact is missing or empty.",
    "EXTRACTION_FAILED": "Extraction could not produce a complete evidence bundle.",
    "CONTRACT_INTERNAL": "LecturAL could not produce a safe extraction response.",
}


def failure(code: str) -> dict:
    """Return a bounded failure object with no exception or input details."""
    return {"code": code, "message": _FAILURE_MESSAGES.get(code, _FAILURE_MESSAGES["EXTRACTION_FAILED"])}


def reason(code: str) -> dict:
    """Return a bounded machine-readable extraction reason."""
    item = failure(code)
    return {"code": item["code"], "message": item["message"]}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _resolved(path: str | os.PathLike[str]) -> str:
    return os.path.realpath(os.path.abspath(os.fspath(path)))


def is_contained(root: str | os.PathLike[str], path: str | os.PathLike[str]) -> bool:
    """Return whether ``path`` resolves beneath ``root`` on Windows or POSIX."""
    try:
        return os.path.commonpath([_resolved(root), _resolved(path)]) == _resolved(root)
    except (OSError, ValueError):
        # ValueError covers different Windows drives.
        return False


def assert_contained(root: str, path: str) -> str:
    resolved = _resolved(path)
    if not is_contained(root, resolved):
        raise ContractError("OUTPUT_PATH_ESCAPE", _FAILURE_MESSAGES["OUTPUT_PATH_ESCAPE"])
    return resolved


def prepare_empty_output(path: str) -> str:
    """Create a new output directory, rejecting every pre-existing target."""
    expanded = os.path.expanduser(path)
    candidate = os.path.abspath(expanded)
    if os.path.lexists(candidate):
        raise ContractError("OUTPUT_EXISTS", _FAILURE_MESSAGES["OUTPUT_EXISTS"])

    parent = os.path.dirname(candidate) or os.curdir
    try:
        os.makedirs(parent, exist_ok=True)
        os.mkdir(candidate)
    except FileExistsError as exc:
        raise ContractError("OUTPUT_EXISTS", _FAILURE_MESSAGES["OUTPUT_EXISTS"]) from exc
    except OSError as exc:
        raise ContractError("OUTPUT_PATH_ESCAPE", _FAILURE_MESSAGES["OUTPUT_PATH_ESCAPE"]) from exc
    return _resolved(candidate)


def _finite_timestamp(value: object, duration: float) -> bool:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(timestamp) or timestamp < 0:
        return False
    return not duration > 0 or timestamp <= duration + 0.001


def timestamp_integrity(
    duration_sec: object,
    transcript_segments: Iterable[dict],
    frames: Iterable[dict],
    *,
    allow_unknown_duration: bool = False,
) -> dict:
    """Validate public segment intervals and frame start timestamps."""
    try:
        duration = float(duration_sec)
    except (TypeError, ValueError):
        duration = 0.0
    duration_valid = math.isfinite(duration) and duration > 0
    segments = list(transcript_segments)
    frame_items = list(frames)
    segment_ok = True
    for item in segments:
        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
        except (TypeError, ValueError):
            segment_ok = False
            break
        if not (
            math.isfinite(start)
            and math.isfinite(end)
            and start >= 0
            and start <= end
            and (not duration > 0 or end <= duration + 0.001)
        ):
            segment_ok = False
            break
    frame_ok = all(_finite_timestamp(item.get("start"), duration) for item in frame_items)
    frame_ordered = all(
        float(frame_items[index - 1]["start"]) <= float(frame_items[index]["start"])
        for index in range(1, len(frame_items))
        if _finite_timestamp(frame_items[index - 1].get("start"), duration)
        and _finite_timestamp(frame_items[index].get("start"), duration)
    )
    issues: list[str] = []
    if not duration_valid and not allow_unknown_duration:
        issues.append("DURATION_INVALID")
    if not segment_ok:
        issues.append("TRANSCRIPT_TIMESTAMP_INVALID")
    if not frame_ok:
        issues.append("FRAME_TIMESTAMP_INVALID")
    if not frame_ordered:
        issues.append("FRAME_TIMESTAMP_UNORDERED")
    passed = not issues
    return {
        "status": "pass" if passed else "fail",
        "pass": passed,
        "duration_sec": round(duration, 3) if math.isfinite(duration) else 0.0,
        "duration_known": duration_valid,
        "transcript_segments": {"count": len(segments), "valid": segment_ok},
        "frames": {"count": len(frame_items), "valid": frame_ok, "ordered": frame_ordered},
        "issues": issues,
    }


def _artifact_paths(output_dir: str, paths: dict[str, str | None]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in ("evidence", "transcript", "frames_dir", "output_dir"):
        path = paths.get(name)
        if path is None:
            result[name] = None
        else:
            result[name] = assert_contained(output_dir, path)
    return result


def _safe_source(source: dict) -> dict:
    """Return the public source identity and bounded display metadata."""
    kind = source.get("kind")
    citation = source.get("citation") if isinstance(source.get("citation"), dict) else {}
    safe_citation = {"kind": citation.get("kind")}
    if kind == "youtube" and citation.get("video_id"):
        safe_citation["video_id"] = citation["video_id"]
        argument = f"https://youtu.be/{citation['video_id']}"
    else:
        raw_argument = str(source.get("argument") or "local-media")
        argument = os.path.basename(raw_argument.replace("\\", "/")) or "local-media"
    raw_resolution = source.get("resolution")
    resolution = raw_resolution if isinstance(raw_resolution, dict) else {}

    def _dimension(value: object) -> int | None:
        return value if isinstance(value, int) and value > 0 else None

    duration = source.get("duration_sec")
    try:
        duration_value = float(duration)
    except (TypeError, ValueError):
        duration_value = 0.0
    if not math.isfinite(duration_value) or duration_value < 0:
        duration_value = 0.0
    return {
        "id": str(source.get("id") or ""),
        "kind": kind,
        "argument": argument,
        "title": str(source.get("title") or "Untitled"),
        "duration_sec": round(duration_value, 3),
        "has_video": bool(source.get("has_video", kind in {"youtube", "local_video"})),
        "resolution": {"width": _dimension(resolution.get("width")), "height": _dimension(resolution.get("height"))},
        "citation": safe_citation,
    }




def build_version_response() -> dict:
    """Build the stable ``lectural --version --json`` response."""
    result = {
        "version": __version__,
        "lectural_version": __version__,
        "contract": "extraction",
        "contract_version": EXTRACTION_CONTRACT_VERSION,
        "supported_contract_versions": [EXTRACTION_CONTRACT_VERSION],
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "supported_schema_versions": [EXTRACTION_SCHEMA_VERSION],
    }
    return {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "contract_version": EXTRACTION_CONTRACT_VERSION,
        "tool": "lectural",
        "tool_version": __version__,
        "version": __version__,
        "supported_contract_versions": [EXTRACTION_CONTRACT_VERSION],
        "supported_schema_versions": [EXTRACTION_SCHEMA_VERSION],
        "status": "ok",
        "result": result,
        "errors": [],
        "generated_at": utc_now(),
    }


def build_evidence_manifest(
    *,
    source: dict,
    output_dir: str,
    paths: dict[str, str | None],
    transcript_segments: list[dict],
    frames: list[dict],
    speech: dict,
    speech_completeness: dict,
    visual_completeness: dict,
    timestamp_integrity_result: dict,
    ocr_status: str,
    ocr_engine: str,
    extraction_status: str,
    reasons: list[dict],
    resources: dict,
    failure_info: dict | None = None,
) -> dict:
    """Build the v2 public manifest using only safe, output-contained paths."""
    safe_paths = _artifact_paths(output_dir, paths)
    safe_source = _safe_source(source)
    checked_frames: list[dict] = []
    for frame in frames:
        path = assert_contained(output_dir, str(frame["path"]))
        checked_frames.append({
            "id": str(frame["id"]),
            "start": round(float(frame["start"]), 3),
            "path": path,
            "sha256": str(frame["sha256"]),
            "width": frame.get("width"),
            "height": frame.get("height"),
            "ocr": {
                "status": frame["ocr"]["status"],
                "text": frame["ocr"].get("text"),
                "is_slide": bool(frame["ocr"].get("is_slide")),
                "reliable": frame["ocr"].get("reliable"),
            },
        })

    extraction = {
        "status": extraction_status,
        "reasons": list(reasons),
        "speech_completeness": speech_completeness,
        "visual_completeness": visual_completeness,
        "timestamp_integrity": timestamp_integrity_result,
        "ocr": {
            "status": ocr_status,
            "engine": ocr_engine,
            "annotation_only": True,
        },
    }
    return {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "contract_version": EXTRACTION_CONTRACT_VERSION,
        "tool": "lectural",
        "tool_version": __version__,
        "generated_at": utc_now(),
        "source": safe_source,
        "speech": speech,
        "transcript": {"segments": transcript_segments},
        "frames": checked_frames,
        "artifacts": safe_paths,
        "extraction": extraction,
        "resources": resources,
        "failure": failure_info,
    }

def build_extract_response(evidence: dict) -> dict:
    """Wrap a v2 evidence manifest in the common JSON CLI envelope."""
    status = (evidence.get("extraction") or {}).get("status")
    envelope_status = {"pass": "ok", "warn": "partial", "fail": "error"}.get(status, "error")
    error_list = [] if status == "pass" else list((evidence.get("extraction") or {}).get("reasons", []))
    return {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "contract_version": EXTRACTION_CONTRACT_VERSION,
        "tool": "lectural",
        "tool_version": __version__,
        "status": envelope_status,
        "result": evidence,
        "errors": error_list,
        "generated_at": evidence.get("generated_at", utc_now()),
    }


def build_failure_response(code: str, *, output_dir: str | None = None, source: dict | None = None) -> dict:
    """Build a bounded response when extraction fails before a v2 manifest."""
    item = failure(code)
    result = {
        "contract_version": EXTRACTION_CONTRACT_VERSION,
        "source": _safe_source(source) if source else None,
        "artifacts": {
            "evidence": os.path.join(output_dir, "evidence.json") if output_dir else None,
            "transcript": os.path.join(output_dir, "transcript.md") if output_dir else None,
            "frames_dir": None,
            "output_dir": output_dir,
        },
        "extraction": {"status": "fail", "reasons": [reason(code)]},
        "failure": item,
    }
    return {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "contract_version": EXTRACTION_CONTRACT_VERSION,
        "tool": "lectural",
        "tool_version": __version__,
        "status": "error",
        "result": result,
        "errors": [item],
        "generated_at": utc_now(),
    }


def write_json(payload: dict, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


__all__ = [
    "ContractError",
    "EXTRACTION_CONTRACT_VERSION",
    "EXTRACTION_SCHEMA_VERSION",
    "assert_contained",
    "build_evidence_manifest",
    "build_extract_response",
    "build_failure_response",
    "build_version_response",
    "failure",
    "is_contained",
    "prepare_empty_output",
    "reason",
    "timestamp_integrity",
    "write_json",
]
