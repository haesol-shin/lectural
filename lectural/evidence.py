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
    "OCR_FAILED": "Requested OCR failed; representative frames were retained when available.",
    "TIMESTAMP_INVALID": "Extraction produced invalid or inconsistent timestamps.",
    "SPEECH_INCOMPLETE": "Speech coverage contains an untranscribed interval.",
    "VISUAL_INCOMPLETE": "Visual timeline coverage contains an uncovered interval.",
    "OCR_INCOMPLETE": "OCR did not annotate every required slide frame.",
    "ARTIFACT_INCOMPLETE": "A required extraction artifact is missing or empty.",
    "NOTES_CONTRACT_INVALID": "The deterministic notes contract is incomplete.",
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
    representative_frames: Iterable[dict],
    *,
    allow_unknown_duration: bool = False,
) -> dict:
    """Validate all public time references without interpreting their content."""
    try:
        duration = float(duration_sec)
    except (TypeError, ValueError):
        duration = 0.0
    duration_valid = math.isfinite(duration) and duration > 0
    segments = list(transcript_segments)
    frames = list(representative_frames)
    segment_ok = all(_finite_timestamp(item.get("t"), duration) for item in segments)
    frame_ok = all(_finite_timestamp(item.get("timestamp_sec"), duration) for item in frames)
    frame_ordered = all(
        float(frames[i - 1].get("timestamp_sec")) <= float(frames[i].get("timestamp_sec"))
        for i in range(1, len(frames))
        if _finite_timestamp(frames[i - 1].get("timestamp_sec"), duration)
        and _finite_timestamp(frames[i].get("timestamp_sec"), duration)
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
        "representative_frames": {"count": len(frames), "valid": frame_ok, "ordered": frame_ordered},
        "issues": issues,
    }


def _artifact_paths(output_dir: str, paths: dict[str, str | None]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name, path in paths.items():
        if path is None:
            result[name] = None
            continue
        result[name] = assert_contained(output_dir, path)
    # The explicit *_md/*_json aliases make the public shape readable while
    # keeping the short names used in consumer code stable.
    aliases = {
        "transcript": "transcript_md",
        "notes": "notes_md",
        "synthesis_input": "synthesis_input_json",
        "coverage": "coverage_json",
        "evidence": "evidence_json",
    }
    for short, long_name in aliases.items():
        if long_name in result:
            result[short] = result[long_name]
    return result


def _safe_source(source: dict) -> dict:
    """Defensively remove a raw source argument before writing public JSON."""
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
    return {
        "kind": kind,
        "argument": argument,
        "has_video": bool(source.get("has_video", kind in {"youtube", "local_video"})),
        "citation": safe_citation,
        "resolution": {"width": _dimension(resolution.get("width")), "height": _dimension(resolution.get("height"))},
    }


def completeness_from_coverage(coverage: dict) -> tuple[dict, dict]:
    gap = coverage.get("gap_check", {})
    scene = coverage.get("scene_coverage", {})
    speech_pass = bool(gap.get("pass"))
    speech = {
        "status": "pass" if speech_pass else "fail",
        "pass": speech_pass,
        "max_untranscribed_speech_gap_sec": gap.get("max_untranscribed_speech_gap_sec", 0),
        "threshold_sec": gap.get("threshold_sec"),
    }
    if not scene.get("visual_required", True):
        visual = {"status": "not-applicable", "pass": True, "timeline_pass": True}
    else:
        visual_pass = bool(scene.get("timeline_pass"))
        visual = {
            "status": "pass" if visual_pass else "fail",
            "pass": visual_pass,
            "timeline_pass": visual_pass,
            "speech_bins": scene.get("speech_bins", []),
            "covered_speech_bins": scene.get("covered_speech_bins", []),
            "uncovered_speech_bins": scene.get("uncovered_speech_bins", []),
        }
    return speech, visual


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
    coverage: dict,
    transcript_segments: list[dict],
    representative_frames: list[dict],
    ocr_status: str,
    ocr_engine: str,
    extraction_status: str,
    reasons: list[dict],
    failure_info: dict | None = None,
) -> dict:
    """Build the public manifest using only safe, output-contained paths."""
    safe_paths = _artifact_paths(output_dir, paths)
    source = _safe_source(source)
    checked_frames: list[dict] = []
    for frame in representative_frames:
        path = assert_contained(output_dir, str(frame["path"]))
        text = str(frame.get("ocr_text") or "")
        annotation_status = "text" if text else "no-text"
        if ocr_status == "skipped":
            annotation_status = "skipped"
        elif ocr_status == "failed":
            annotation_status = "failed"
        checked_frames.append(
            {
                "timestamp_sec": round(float(frame["timestamp_sec"]), 3),
                "path": path,
                "ocr": {
                    "status": annotation_status,
                    "text": text or None,
                    "is_slide": bool(frame.get("is_slide", False)),
                    "reliable": frame.get("reliable"),
                },
                "width": frame.get("width"),
                "height": frame.get("height"),
            }
        )

    timestamp = timestamp_integrity(
        coverage.get("duration_sec", 0),
        transcript_segments,
        checked_frames,
        allow_unknown_duration=not bool(source.get("has_video", True)),
    )
    speech, visual = completeness_from_coverage(coverage)
    if not timestamp["pass"] and not any(item.get("code") == "TIMESTAMP_INVALID" for item in reasons):
        reasons = [*reasons, reason("TIMESTAMP_INVALID")]

    extraction = {
        "status": extraction_status,
        "reasons": reasons,
        "speech_completeness": speech,
        "visual_completeness": visual,
        "timestamp_integrity": timestamp,
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
        "source": source,
        "source_kind": source.get("kind"),
        "status": extraction_status,
        "artifacts": safe_paths,
        "extraction": extraction,
        "representative_frames": checked_frames,
        "failure": failure_info,
    }


def build_extract_response(evidence: dict) -> dict:
    """Wrap an evidence manifest in the common JSON CLI envelope."""
    status = evidence.get("status")
    envelope_status = {"pass": "ok", "warn": "partial", "fail": "error"}.get(status, "error")
    error_list = [] if status == "pass" else list(evidence.get("extraction", {}).get("reasons", []))
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
    """Build a JSON response for failures that happen before a manifest exists."""
    item = failure(code)
    result = {
        "contract_version": EXTRACTION_CONTRACT_VERSION,
        "source": source,
        "source_kind": (source or {}).get("kind"),
        "output_dir": output_dir,
        "extraction_status": "fail",
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
