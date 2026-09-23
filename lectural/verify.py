"""Deterministic structural and completeness checks for v2 evidence bundles."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
import os
import re
from typing import Any, Callable

from . import __version__
from .bundle import Bundle, BundleError, load_bundle
from .config import EXTRACTION_CONTRACT_VERSION, EXTRACTION_SCHEMA_VERSION
from .coverage import gap_check, scene_coverage
from .source import classify_source


_SEGMENT_ID = re.compile(r"^s[0-9]{4,}$")
_FRAME_ID = re.compile(r"^f[0-9]{4,}$")
_SOURCE_ID = re.compile(r"^(sha256:[0-9a-f]{64}|youtube:[A-Za-z0-9_-]{11})$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_REASON_CODE = re.compile(r"^[A-Z0-9_]+$")
_HARD_FAILURES = {"OCR_FAILED", "ARTIFACT_INCOMPLETE", "TIMESTAMP_INVALID"}


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _string(value: object, *, minimum: int = 0, maximum: int | None = None,
            pattern: re.Pattern[str] | None = None, enum: set[str] | None = None) -> bool:
    return (
        isinstance(value, str)
        and len(value) >= minimum
        and (maximum is None or len(value) <= maximum)
        and (pattern is None or pattern.fullmatch(value) is not None)
        and (enum is None or value in enum)
    )


def _object(value: object, required: set[str], properties: dict[str, Callable[[object], bool]],
            *, additional: bool = False) -> bool:
    if not isinstance(value, dict) or not required.issubset(value):
        return False
    if not additional and value.keys() - properties.keys():
        return False
    return all(key not in value or validator(value[key]) for key, validator in properties.items())


def _nullable(validator: Callable[[object], bool]) -> Callable[[object], bool]:
    return lambda value: value is None or validator(value)


def _enum(*values: str) -> Callable[[object], bool]:
    allowed = set(values)
    return lambda value: _string(value, enum=allowed)


def _number(value: object, *, minimum: float | None = None) -> bool:
    return _is_number(value) and (minimum is None or value >= minimum)



def _integer(value: object, *, minimum: int | None = None) -> bool:
    return _is_integer(value) and (minimum is None or value >= minimum)

def _valid_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return "T" in value and parsed.tzinfo is not None


def _valid_pair_list(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(pair, list) and len(pair) == 2 and all(_is_number(item) for item in pair)
        for pair in value
    )


def _valid_array(value: object, item_validator: Callable[[object], bool]) -> bool:
    return isinstance(value, list) and all(item_validator(item) for item in value)


def _valid_failure(value: object) -> bool:
    return _object(
        value, {"code", "message"},
        {"code": lambda item: _string(item, minimum=1, pattern=_REASON_CODE),
         "message": lambda item: _string(item, minimum=1, maximum=200)},
    )


def _valid_source(value: object) -> bool:
    citation = lambda item: _object(
        item, {"kind"},
        {"kind": _enum("youtube", "transcript"),
         "video_id": lambda val: _string(val, pattern=re.compile(r"^[A-Za-z0-9_-]{11}$"))},
    )
    resolution = lambda item: _object(
        item, {"width", "height"},
        {"width": _nullable(lambda val: _integer(val, minimum=1)),
         "height": _nullable(lambda val: _integer(val, minimum=1))},
    )
    return _object(
        value, {"id", "kind", "argument", "title", "duration_sec", "has_video", "resolution", "citation"},
        {"id": lambda item: _string(item, pattern=_SOURCE_ID),
         "kind": _enum("youtube", "local_video", "local_audio"),
         "argument": lambda item: _string(item, minimum=1),
         "title": lambda item: _string(item, minimum=1),
         "duration_sec": lambda item: _number(item, minimum=0),
         "has_video": lambda item: isinstance(item, bool),
         "resolution": resolution,
         "citation": citation},
    )


def _valid_speech(value: object) -> bool:
    fallback = lambda item: item is None or _object(
        item, {"code"}, {"code": _enum("captions_unavailable", "captions_unusable", "forced_stt", "local_source")}
    )
    return _object(
        value, {"source", "language", "model", "fallback"},
        {"source": _enum("caption", "stt"),
         "language": _nullable(lambda item: isinstance(item, str)),
         "model": _nullable(lambda item: isinstance(item, str)),
         "fallback": fallback},
    )


def _valid_completeness(value: object) -> bool:
    if not isinstance(value, dict) or not {"status", "pass"}.issubset(value):
        return False
    if not isinstance(value["status"], str) or not isinstance(value["pass"], bool):
        return False
    optional: dict[str, Callable[[object], bool]] = {
        "speech_spans": _valid_pair_list,
        "raw_sample_times": lambda item: _valid_array(item, _is_number),
        "slide_frame_ids": lambda item: _valid_array(item, lambda val: _string(val, pattern=_FRAME_ID)),
        "max_untranscribed_speech_gap_sec": lambda item: _number(item, minimum=0),
        "threshold_sec": lambda item: _number(item, minimum=0),
        "bins": lambda item: _integer(item, minimum=1),
        "carry_max_sec": lambda item: _number(item, minimum=0),
        "visual_required": lambda item: isinstance(item, bool),
        "ocr_required": lambda item: isinstance(item, bool),
        "ocr_failed": lambda item: isinstance(item, bool),
        "duration_valid": lambda item: isinstance(item, bool),
        "timeline_pass": lambda item: isinstance(item, bool),
        "slide_text_pass": lambda item: isinstance(item, bool),
        "slide_frames_total": lambda item: _integer(item, minimum=0),
        "slide_frames_with_text": lambda item: _integer(item, minimum=0),
        "speech_bins": lambda item: _valid_array(item, lambda val: _integer(val, minimum=0)),
        "covered_speech_bins": lambda item: _valid_array(item, lambda val: _integer(val, minimum=0)),
        "uncovered_speech_bins": lambda item: _valid_array(item, lambda val: _integer(val, minimum=0)),
    }
    return all(key not in value or check(value[key]) for key, check in optional.items())


def _valid_frame(value: object) -> bool:
    ocr = lambda item: _object(
        item, {"status", "text", "is_slide", "reliable"},
        {"status": _enum("text", "no-text", "skipped", "failed"),
         "text": _nullable(lambda val: isinstance(val, str)),
         "is_slide": lambda val: isinstance(val, bool),
         "reliable": _nullable(lambda val: isinstance(val, bool))},
    )
    nullable_dimension = _nullable(lambda item: _integer(item, minimum=1))
    return _object(
        value, {"id", "start", "path", "sha256", "width", "height", "ocr"},
        {"id": lambda item: _string(item, pattern=_FRAME_ID),
         "start": lambda item: _number(item, minimum=0),
         "path": lambda item: _string(item, minimum=1),
         "sha256": lambda item: _string(item, pattern=_HASH),
         "width": nullable_dimension,
         "height": nullable_dimension,
         "ocr": ocr},
    )


def _valid_manifest_shape(manifest: dict[str, Any]) -> bool:
    segment = lambda item: _object(
        item, {"id", "start", "end", "text"},
        {"id": lambda val: _string(val, pattern=_SEGMENT_ID),
         "start": lambda val: _number(val, minimum=0),
         "end": lambda val: _number(val, minimum=0),
         "text": lambda val: isinstance(val, str)},
    )
    transcript = lambda item: _object(
        item, {"segments"}, {"segments": lambda val: _valid_array(val, segment)}
    )
    artifacts = lambda item: _object(
        item, {"evidence", "transcript", "frames_dir", "output_dir"},
        {"evidence": lambda val: _string(val, minimum=1),
         "transcript": lambda val: _string(val, minimum=1),
         "frames_dir": _nullable(lambda val: _string(val, minimum=1)),
         "output_dir": lambda val: _string(val, minimum=1)},
    )
    extraction_ocr = lambda item: _object(
        item, {"status", "engine", "annotation_only"},
        {"status": _enum("skipped", "completed-no-text", "completed-with-text", "failed", "not_applicable"),
         "engine": lambda val: isinstance(val, str),
         "annotation_only": lambda val: val is True},
        additional=True,
    )
    extraction = lambda item: _object(
        item, {"status", "reasons", "speech_completeness", "visual_completeness", "timestamp_integrity", "ocr"},
        {"status": _enum("pass", "warn", "fail"),
         "reasons": lambda val: _valid_array(val, _valid_failure),
         "speech_completeness": _valid_completeness,
         "visual_completeness": _valid_completeness,
         "timestamp_integrity": _valid_completeness,
         "ocr": extraction_ocr},
    )
    stages = lambda item: _object(
        item, {"speech", "frames", "dedupe", "ocr"},
        {key: lambda val: _number(val, minimum=0) for key in ("speech", "frames", "dedupe", "ocr")},
    )
    resources = lambda item: _object(
        item, {"wall_sec", "stages", "peak_rss_mb", "artifact_bytes", "frames_candidate", "frames_retained"},
        {"wall_sec": lambda val: _number(val, minimum=0),
         "stages": stages,
         "peak_rss_mb": _nullable(lambda val: _number(val, minimum=0)),
         "artifact_bytes": lambda val: _integer(val, minimum=0),
         "frames_candidate": lambda val: _integer(val, minimum=0),
         "frames_retained": lambda val: _integer(val, minimum=0)},
    )
    top = {
        "schema_version": lambda val: type(val) is int and val == EXTRACTION_SCHEMA_VERSION,
        "contract_version": lambda val: type(val) is int and val == EXTRACTION_CONTRACT_VERSION,
        "tool": lambda val: val == "lectural",
        "tool_version": lambda val: _string(val, minimum=1),
        "generated_at": _valid_datetime,
        "source": _valid_source,
        "speech": _valid_speech,
        "transcript": transcript,
        "frames": lambda val: _valid_array(val, _valid_frame),
        "artifacts": artifacts,
        "extraction": extraction,
        "resources": resources,
        "failure": lambda val: val is None or _valid_failure(val),
    }
    return _object(manifest, set(top), top)


def _check(name: str, passed: bool, code: str, detail: str) -> dict[str, str]:
    if passed:
        return {"name": name, "status": "pass"}
    return {"name": name, "status": "fail", "code": code, "detail": detail}


def _manifest_items(bundle: Bundle) -> tuple[list[Any], list[Any]]:
    transcript = bundle.manifest.get("transcript")
    segments = transcript.get("segments") if isinstance(transcript, dict) else None
    frames = bundle.manifest.get("frames")
    return (segments if isinstance(segments, list) else [], frames if isinstance(frames, list) else [])


def _verify_artifacts(bundle: Bundle) -> bool:
    evidence_path = bundle.artifact_paths.get("evidence")
    transcript_path = bundle.artifact_paths.get("transcript")
    source = bundle.manifest.get("source")
    visual_required = isinstance(source, dict) and source.get("has_video") is True
    frames_dir = bundle.artifact_paths.get("frames_dir")
    try:
        return (
            evidence_path is not None and os.path.isfile(evidence_path)
            and transcript_path is not None and os.path.isfile(transcript_path)
            and os.path.getsize(transcript_path) > 0
            and (not visual_required or (frames_dir is not None and os.path.isdir(frames_dir)))
        )
    except OSError:
        return False


def _hash_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_frame_hashes(bundle: Bundle) -> bool:
    _, frames = _manifest_items(bundle)
    if len(bundle.frame_paths) != len(frames):
        return False
    for frame, path in zip(frames, bundle.frame_paths):
        if not isinstance(frame, dict) or path is None:
            return False
        try:
            if not os.path.isfile(path) or _hash_file(path) != frame.get("sha256"):
                return False
        except OSError:
            return False
    return True


def _verify_identifiers(bundle: Bundle) -> bool:
    segments, frames = _manifest_items(bundle)
    segment_ids = [item.get("id") if isinstance(item, dict) else None for item in segments]
    frame_ids = [item.get("id") if isinstance(item, dict) else None for item in frames]
    if (
        any(not isinstance(item, str) or _SEGMENT_ID.fullmatch(item) is None for item in segment_ids)
        or len(set(segment_ids)) != len(segment_ids)
        or any(item != f"s{index:04d}" for index, item in enumerate(segment_ids, start=1))
    ):
        return False
    if (
        any(not isinstance(item, str) or _FRAME_ID.fullmatch(item) is None for item in frame_ids)
        or len(set(frame_ids)) != len(frame_ids)
        or any(item != f"f{index:04d}" for index, item in enumerate(frame_ids, start=1))
    ):
        return False
    for items, ids, field in ((segments, segment_ids, "start"), (frames, frame_ids, "start")):
        try:
            ordered = sorted(zip(items, ids), key=lambda pair: float(pair[0][field]))
        except (KeyError, TypeError, ValueError, OverflowError):
            return False
        if any(identifier != f"{prefix}{index:04d}" for index, (item, identifier) in enumerate(ordered, start=1)
               for prefix in ("s" if items is segments else "f",)):
            return False
    extraction = bundle.manifest.get("extraction")
    visual = extraction.get("visual_completeness") if isinstance(extraction, dict) else None
    slide_ids = visual.get("slide_frame_ids") if isinstance(visual, dict) else None
    if isinstance(slide_ids, list):
        return all(identifier in set(frame_ids) for identifier in slide_ids)
    return False


def _verify_timestamps(bundle: Bundle) -> bool:
    source = bundle.manifest.get("source")
    duration = source.get("duration_sec") if isinstance(source, dict) else None
    if not _number(duration, minimum=0):
        return False
    segments, frames = _manifest_items(bundle)
    segment_starts: list[float] = []
    for item in segments:
        if not isinstance(item, dict):
            return False
        start, end = item.get("start"), item.get("end")
        if not _number(start, minimum=0) or not _number(end, minimum=0):
            return False
        if start > end or end > duration + 0.001:
            return False
        segment_starts.append(float(start))
    if segment_starts != sorted(segment_starts):
        return False
    frame_starts: list[float] = []
    for item in frames:
        if not isinstance(item, dict) or not _number(item.get("start"), minimum=0):
            return False
        start = float(item["start"])
        if start > duration + 0.001:
            return False
        frame_starts.append(start)
    return frame_starts == sorted(frame_starts)


def _verify_completeness(bundle: Bundle) -> bool:
    manifest = bundle.manifest
    source = manifest.get("source")
    extraction = manifest.get("extraction")
    if not isinstance(source, dict) or not isinstance(extraction, dict):
        return False
    speech = extraction.get("speech_completeness")
    visual = extraction.get("visual_completeness")
    if not isinstance(speech, dict) or not isinstance(visual, dict):
        return False
    duration = source.get("duration_sec")
    spans_raw = speech.get("speech_spans")
    segments, frames = _manifest_items(bundle)
    if not _number(duration, minimum=0) or not _valid_pair_list(spans_raw):
        return False
    if not _number(speech.get("threshold_sec"), minimum=0):
        return False
    spans = [(float(span[0]), float(span[1])) for span in spans_raw]
    if any(start < 0 or start > end or end > duration + 0.001 for start, end in spans):
        return False
    try:
        segment_starts = [float(item["start"]) for item in segments]
        gap = gap_check(spans, segment_starts, float(duration), float(speech["threshold_sec"]))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    expected_speech_status = "pass" if gap["pass"] else "fail"
    if (
        speech.get("pass") is not gap["pass"]
        or speech.get("status") != expected_speech_status
        or not _number(speech.get("max_untranscribed_speech_gap_sec"), minimum=0)
        or abs(float(speech["max_untranscribed_speech_gap_sec"]) - gap["max_untranscribed_speech_gap_sec"]) > 0.001
    ):
        return False

    raw_times = visual.get("raw_sample_times")
    if not _valid_array(raw_times, _is_number):
        return False
    required_keys = ("bins", "carry_max_sec", "visual_required", "ocr_required")
    if any(key not in visual for key in required_keys):
        return False
    bins = visual.get("bins")
    carry = visual.get("carry_max_sec")
    visual_required = visual.get("visual_required")
    ocr_required = visual.get("ocr_required")
    if (
        not _integer(bins, minimum=1) or bins > 1000
        or not _number(carry, minimum=0)
        or not isinstance(visual_required, bool)
        or not isinstance(ocr_required, bool)
    ):
        return False
    slide_ids = visual.get("slide_frame_ids")
    frame_by_id = {
        item["id"]: item for item in frames
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if not isinstance(slide_ids, list) or any(
        not isinstance(item, str) or item not in frame_by_id for item in slide_ids
    ):
        return False
    slide_frames = [frame_by_id[item] for item in slide_ids]
    slide_total = len(slide_frames)
    slide_with_text = 0
    for frame in slide_frames:
        text = _mapping(frame.get("ocr")).get("text")
        slide_with_text += bool(text.strip()) if isinstance(text, str) else 0
    ocr_state = _mapping(extraction.get("ocr")).get("status")
    ocr_failed = ocr_state == "failed"
    if (
        visual.get("slide_frames_total") != slide_total
        or visual.get("slide_frames_with_text") != slide_with_text
        or visual.get("ocr_failed") is not ocr_failed
    ):
        return False
    try:
        scene = scene_coverage(
            [float(item) for item in raw_times], spans, float(duration),
            bins=bins,
            slide_frames_total=slide_total,
            slide_frames_with_text=slide_with_text,
            carry_max_sec=float(carry),
            visual_required=visual_required,
            ocr_required=ocr_required,
            ocr_failed=ocr_failed,
        )
    except (TypeError, ValueError, OverflowError):
        return False
    timeline_pass = scene["timeline_pass"]
    expected_visual_pass = not visual_required or timeline_pass
    expected_visual_status = "not-applicable" if not visual_required else ("pass" if timeline_pass else "fail")
    if (
        visual.get("timeline_pass") is not timeline_pass
        or visual.get("slide_text_pass") is not scene["slide_text_pass"]
        or visual.get("pass") is not expected_visual_pass
        or visual.get("status") != expected_visual_status
        or visual.get("duration_valid") is not scene["duration_valid"]
    ):
        return False

    reasons = extraction.get("reasons")
    status = extraction.get("status")
    if not isinstance(reasons, list) or status not in {"pass", "warn", "fail"}:
        return False
    codes: list[str] = []
    for reason in reasons:
        if not isinstance(reason, dict) or not _string(reason.get("code"), minimum=1, pattern=_REASON_CODE):
            return False
        codes.append(reason["code"])
    hard_failure = any(code in _HARD_FAILURES for code in codes)
    return (status == "fail") == hard_failure and (status == "pass") == (not reasons)


def _verify_source(bundle: Bundle, argument: str) -> tuple[bool, str, str]:
    source = bundle.manifest.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("id"), str):
        return False, "SOURCE_MISMATCH", "The supplied source does not match the recorded identity."
    expanded = os.path.expanduser(argument)
    if os.path.isfile(expanded):
        digest = hashlib.sha256()
        try:
            with open(expanded, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return False, "SOURCE_UNAVAILABLE", "The supplied source cannot be read."
        return source["id"] == f"sha256:{digest.hexdigest()}", "SOURCE_MISMATCH", "The supplied source does not match the recorded identity."
    try:
        classified = classify_source(argument)
    except (FileNotFoundError, TypeError, ValueError):
        return False, "SOURCE_INVALID", "The supplied source is not a supported file or YouTube identifier."
    expected = f"youtube:{classified.video_id}" if classified.video_id else ""
    return expected == source["id"], "SOURCE_MISMATCH", "The supplied source does not match the recorded identity."


def verify_bundle(path: str, *, source: str | None = None) -> dict[str, Any]:
    """Run every deterministic check, marking source identity skipped if absent."""
    bundle = load_bundle(path)
    checks: list[dict[str, str]] = [
        _check("schema", _valid_manifest_shape(bundle.manifest), "SCHEMA_INVALID", "The evidence manifest shape does not match contract v2."),
        _check("containment", bundle.containment_valid, "BUNDLE_CONTAINMENT", "A recorded artifact path is outside its bundle."),
        _check("artifacts", _verify_artifacts(bundle), "ARTIFACTS_INCOMPLETE", "A required evidence artifact is missing or empty."),
        _check("frame_hashes", _verify_frame_hashes(bundle), "FRAME_HASH_MISMATCH", "A frame is missing or its SHA-256 does not match."),
        _check("identifiers", _verify_identifiers(bundle), "IDENTIFIERS_INVALID", "Segment or frame identifiers are invalid or inconsistent."),
        _check("timestamps", _verify_timestamps(bundle), "TIMESTAMPS_INVALID", "Segment or frame timestamps are invalid or unordered."),
        _check("completeness", _verify_completeness(bundle), "COMPLETENESS_INVALID", "Declared completeness does not match the evidence."),
    ]
    if source is None:
        checks.append({"name": "source", "status": "skipped", "detail": "No source was supplied."})
    else:
        passed, code, detail = _verify_source(bundle, source)
        checks.append(_check("source", passed, code, detail))
    return {"valid": all(check["status"] != "fail" for check in checks), "checks": checks}


def response(result: dict[str, Any]) -> dict[str, Any]:
    """Build the common JSON envelope for a verifier result."""
    failed = [
        {"code": item["code"], "message": item.get("detail", "Bundle verification failed.")}
        for item in result["checks"] if item["status"] == "fail"
    ]
    return {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "contract_version": EXTRACTION_CONTRACT_VERSION,
        "tool": "lectural",
        "tool_version": __version__,
        "status": "ok" if result["valid"] else "error",
        "result": result,
        "errors": failed,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def error_response(error: BundleError) -> dict[str, Any]:
    return {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "contract_version": EXTRACTION_CONTRACT_VERSION,
        "tool": "lectural",
        "tool_version": __version__,
        "status": "error",
        "result": {"valid": False, "checks": []},
        "errors": [{"code": error.code, "message": error.safe_message}],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def render_result(result: dict[str, Any]) -> str:
    lines = []
    for check in result["checks"]:
        suffix = f" ({check['code']})" if check.get("code") else ""
        lines.append(f"{check['name']}: {check['status'].upper()}{suffix}")
    lines.append("VALID" if result["valid"] else "INVALID")
    return "\n".join(lines)


__all__ = ["BundleError", "error_response", "render_result", "response", "verify_bundle"]
