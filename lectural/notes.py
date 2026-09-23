"""Generate the notes artifacts from a v2 evidence bundle."""

from __future__ import annotations

import json
import os

from . import evidence
from .coverage import build_coverage, coverage_inputs_from_extraction, write_coverage
from .synthesis import build_synthesis_input, render_notes_md, write_synthesis_input, write_text


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise evidence.ContractError("SOURCE_INVALID", "The evidence bundle is invalid.")
    return value


def generate_notes(bundle_dir: str) -> dict:
    """Build notes, synthesis handoff, and coverage using only bundle evidence.

    Input is limited to ``evidence.json`` and the transcript/frame files named
    by that manifest. No extraction internals or acquisition sidecars are read.
    """
    output_dir = os.path.realpath(os.path.abspath(bundle_dir))
    manifest_path = os.path.join(output_dir, "evidence.json")
    manifest = _read_json(manifest_path)
    if manifest.get("contract_version") != evidence.EXTRACTION_CONTRACT_VERSION:
        raise evidence.ContractError("SOURCE_INVALID", "The evidence bundle version is unsupported.")

    artifacts = manifest.get("artifacts") or {}
    transcript_path = evidence.assert_contained(output_dir, artifacts.get("transcript") or "")
    if not os.path.isfile(transcript_path):
        raise evidence.ContractError("ARTIFACT_INCOMPLETE", "The evidence transcript is missing.")
    with open(transcript_path, "r", encoding="utf-8") as stream:
        transcript_text = stream.read()

    source = manifest.get("source") or {}
    extraction = manifest.get("extraction") or {}
    speech_completeness = extraction.get("speech_completeness") or {}
    visual_completeness = extraction.get("visual_completeness") or {}
    transcript_items = (manifest.get("transcript") or {}).get("segments") or []
    segments = [
        {"t": float(item["start"]), "text": str(item.get("text") or "")}
        for item in transcript_items
    ]
    speech = manifest.get("speech") or {}
    video = {
        "title": source.get("title") or "Untitled",
        "duration_sec": float(source.get("duration_sec") or 0.0),
        "language": speech.get("language"),
        "speech_source": speech.get("source", "unknown"),
        "input_source": {
            "kind": source.get("kind"),
            "argument": source.get("argument"),
            "has_video": source.get("has_video"),
            "citation": source.get("citation") or {},
        },
    }
    frame_items = manifest.get("frames") or []
    frames_by_id = {item["id"]: item for item in frame_items}
    if len(frames_by_id) != len(frame_items):
        raise evidence.ContractError("SOURCE_INVALID", "The evidence frame identifiers are invalid.")
    slides = []
    for frame_id in visual_completeness.get("notes_frame_ids") or []:
        item = frames_by_id.get(frame_id)
        if item is None:
            raise evidence.ContractError("SOURCE_INVALID", "A notes frame reference is invalid.")
        frame_path = evidence.assert_contained(output_dir, item.get("path") or "")
        if not os.path.isfile(frame_path):
            raise evidence.ContractError("ARTIFACT_INCOMPLETE", "A referenced evidence frame is missing.")
        annotation = item.get("ocr") or {}
        slides.append({
            "t": float(item["start"]),
            "frame": os.path.relpath(frame_path, output_dir).replace(os.sep, "/"),
            "ocr_text": annotation.get("text") or "" if annotation.get("reliable") is True else "",
            "is_slide": True,
        })

    synthesis_input = build_synthesis_input(video, segments, slides)
    synthesis_path = os.path.join(output_dir, "synthesis_input.json")
    notes_path = os.path.join(output_dir, "notes.md")
    coverage_path = os.path.join(output_dir, "coverage.json")
    write_synthesis_input(synthesis_input, synthesis_path)

    duration = video["duration_sec"]
    speech_spans = [tuple(span) for span in speech_completeness.get("speech_spans") or []]
    segment_times = [float(item["start"]) for item in transcript_items]
    raw_sample_times = [float(value) for value in visual_completeness.get("raw_sample_times") or []]
    ocr = extraction.get("ocr") or {}
    visual_required = bool(source.get("has_video"))
    ocr_required = bool(visual_completeness.get("ocr_required", visual_required))
    ocr_failed = ocr.get("status") == "failed"

    def _coverage_inputs(notes_text: str | None):
        return coverage_inputs_from_extraction(
            video_title=video["title"],
            duration_sec=duration,
            speech_spans=speech_spans,
            segment_times=segment_times,
            raw_sample_times=raw_sample_times,
            slides=slides,
            transcript_path=transcript_path,
            notes_path=notes_path,
            ocr_engine=ocr.get("engine", "none"),
            visual_required=visual_required,
            ocr_required=ocr_required,
            ocr_failed=ocr_failed,
            transcript_text=transcript_text,
            notes_text=notes_text,
        )

    coverage = build_coverage(_coverage_inputs(""))
    notes_text = render_notes_md(synthesis_input, coverage)
    coverage = build_coverage(_coverage_inputs(notes_text))
    notes_text = render_notes_md(synthesis_input, coverage)
    coverage = build_coverage(_coverage_inputs(notes_text))
    write_text(notes_text, notes_path)
    write_coverage(coverage, coverage_path)
    return {
        "output_dir": output_dir,
        "notes_md": notes_path,
        "synthesis_input_json": synthesis_path,
        "coverage_json": coverage_path,
        "coverage": coverage,
        "overall_pass": bool(coverage["overall_pass"]),
    }


__all__ = ["generate_notes"]
