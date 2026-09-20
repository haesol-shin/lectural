"""`lectural` CLI: turn lecture media into complete study notes.

Usage:
    lectural doctor [--fix] [--json]
    lectural <source> [<source> ...] [--force-stt] [--model medium]
             [--out ./output] [--keep-frames] [--skip-ocr]

The per-source pipeline is shared across YouTube, local video, and local WAV
inputs. Heavy dependencies remain lazy so deterministic logic runs offline.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import inspect
import json
import math
import os
import re
import sys

from . import evidence
from . import runstate
from .config import DEFAULT_STT_MODEL, OCR_RELIABLE_CONFIDENCE_THRESHOLD
from .source import classify_source


def slugify(title: str, fallback: str = "video") -> str:
    """Pure: filesystem-safe directory name from a title."""
    title = (title or "").strip()
    slug = re.sub(r"[^\w\-가-힣]+", "-", title, flags=re.UNICODE).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or fallback)[:80]


def output_dir_for(out_root: str, title: str, fallback: str = "video") -> str:
    """Pure: ``out_root/<slug>`` path for a source's artifacts."""
    return os.path.join(out_root, slugify(title, fallback))


def _output_path_key(path: str) -> str:
    """Normalize an output path for collision checks on every platform."""
    return os.path.normcase(os.path.abspath(path))


def _reserve_output_dir(
    out_root: str,
    title: str,
    fallback: str = "video",
    reserved_output_dirs: set[str] | None = None,
) -> str:
    """Reserve a non-colliding ``out_root/<slug>`` artifact directory.

    Existing files/directories and paths reserved earlier in the same batch
    are both occupied.  The unsuffixed slug remains the first choice so the
    single-source output contract is unchanged.
    """
    reserved = reserved_output_dirs if reserved_output_dirs is not None else set()
    slug = slugify(title, fallback)
    candidate = os.path.join(out_root, slug)
    suffix = 2
    while os.path.lexists(candidate) or _output_path_key(candidate) in reserved:
        candidate = os.path.join(out_root, f"{slug}-{suffix}")
        suffix += 1
    reserved.add(_output_path_key(candidate))
    return candidate


def _positive_finite_duration(*values: object) -> float:
    """Return the first usable duration, or zero as an explicit fail-closed value."""
    for value in values:
        try:
            duration = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(duration) and duration > 0:
            return duration
    return 0.0


def _ocr_reliable_or_none(frame, ocr_status: str) -> bool | None:
    """Expose quality only for successfully annotated text frames."""
    if ocr_status in {"skipped", "failed"} or not (frame.ocr_text or "").strip():
        return None
    if frame.ocr_confidence is None:
        return None
    return bool(frame.ocr_confidence >= OCR_RELIABLE_CONFIDENCE_THRESHOLD)


def _ocr_reliable(frame, ocr_status: str) -> bool:
    return _ocr_reliable_or_none(frame, ocr_status) is True


def _frame_link(image_path: str, out_dir: str) -> str:
    """Pure: relative slide-image path as a POSIX markdown link."""
    return os.path.relpath(image_path, out_dir).replace(os.sep, "/")


def _run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lectural",
        description="Lecture media -> complete study notes",
        epilog="Command: lectural doctor [--fix] [--json]",
    )
    parser.add_argument(
        "sources",
        nargs="*",
        help="One or more YouTube URLs/IDs or local mp4/webm/mkv/wav files (processed sequentially)",
    )
    parser.add_argument("--force-stt", action="store_true", help="Skip captions; always transcribe with STT")
    parser.add_argument("--model", default=DEFAULT_STT_MODEL, help="faster-whisper model size (default: medium)")
    parser.add_argument("--out", default="./output", help="Output root directory (default: ./output)")
    parser.add_argument(
        "--keep-frames",
        action="store_true",
        help="Archive raw sampled frames under frames/raw/ instead of deleting extras",
    )
    parser.add_argument(
        "--skip-ocr",
        action="store_true",
        default=False,
        help="Keep scene frames but skip OCR and the slide-text coverage check",
    )
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="store_true", help=argparse.SUPPRESS)
    return parser


def _extract_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lectural extract",
        description="Extract a versioned evidence bundle from one lecture source",
    )
    parser.add_argument("source", help="One YouTube URL/ID or local mp4/webm/mkv/wav file")
    parser.add_argument("--out", required=True, help="New, empty output directory for this extraction")
    parser.add_argument("--force-stt", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--model", default=DEFAULT_STT_MODEL, help=argparse.SUPPRESS)
    parser.add_argument("--skip-ocr", action="store_true", help="Skip OCR while retaining representative frames")
    parser.add_argument("--json", action="store_true", help="Print the versioned JSON response")
    return parser


def _doctor_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lectural doctor", description="Validate LecturAL runtime and plugin distribution"
    )
    parser.add_argument("--fix", action="store_true", help="Attempt safe bounded fixes for missing yt-dlp/ffmpeg")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable JSON report")
    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    argv = list(argv)
    if argv and argv[0] == "doctor":
        args = _doctor_parser().parse_args(argv[1:])
        args.command = "doctor"
        return args

    if argv and argv[0] == "extract":
        args = _extract_parser().parse_args(argv[1:])
        args.command = "extract"
        return args

    parser = _run_parser()
    args = parser.parse_args(argv)
    if args.version:
        args.command = "version"
        return args
    args.command = "run"
    if not args.sources:
        parser.error("the following arguments are required: sources (or use `lectural doctor`)")
    return args


def run(
    sources: list[str],
    out_root: str = "./output",
    force_stt: bool = False,
    model: str = DEFAULT_STT_MODEL,
    processor=None,
    runstate_file: str | None = None,
    keep_frames: bool = False,
    skip_ocr: bool = False,
) -> list[dict]:
    """Sequentially process each source and record every run-state entry."""
    processor = processor or _default_processor
    reserved_output_dirs: set[str] = set()
    used_output_dirs: set[str] = set()

    def _call_processor(source_argument: str, out_dir: str) -> dict:
        try:
            signature = inspect.signature(processor)
        except (TypeError, ValueError):
            return processor(source_argument, out_dir, force_stt, model)

        accepts_var_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        kwargs: dict[str, object] = {}
        if accepts_var_kwargs or "keep_frames" in signature.parameters:
            kwargs["keep_frames"] = keep_frames
        if accepts_var_kwargs or "skip_ocr" in signature.parameters:
            kwargs["skip_ocr"] = skip_ocr
        if accepts_var_kwargs or "reserved_output_dirs" in signature.parameters:
            kwargs["reserved_output_dirs"] = reserved_output_dirs
        return processor(source_argument, out_dir, force_stt, model, **kwargs)

    runstate.start_session(sources, runstate_file)
    results: list[dict] = []
    for index, source_argument in enumerate(sources):
        out_dir = os.path.join(out_root, f"video_{index + 1:02d}")  # provisional
        try:
            result = _call_processor(source_argument, out_dir)
            result_output_dir = result.get("output_dir")
            if not isinstance(result_output_dir, str) or not result_output_dir:
                raise ValueError("Processor returned no output directory")
            result_output_key = _output_path_key(result_output_dir)
            if result_output_key in used_output_dirs:
                raise RuntimeError(
                    f"Processor returned an output directory already used in this batch: {result_output_dir}"
                )
            used_output_dirs.add(result_output_key)
            reserved_output_dirs.add(result_output_key)
            runstate.update_run(
                index,
                status="complete",
                output_dir=result["output_dir"],
                coverage_json=result["coverage_json"],
                notes_md=result["notes_md"],
                path=runstate_file,
            )
            results.append(result)
        except Exception as exc:  # noqa: BLE001 - record + continue
            runstate.update_run(
                index,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                path=runstate_file,
            )
            results.append(
                {
                    "output_dir": out_dir,
                    "source": source_argument,
                    "overall_pass": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return results


def _default_processor(
    source_argument: str,
    out_dir_hint: str,
    force_stt: bool,
    model: str,
    *,
    keep_frames: bool = False,
    skip_ocr: bool = False,
    reserved_output_dirs: set[str] | None = None,
    exact_output_dir: str | None = None,
) -> dict:
    """Run the shared speech/visual/synthesis/coverage pipeline for one source."""
    from . import acquisition, media, visual
    from .coverage import build_coverage, coverage_inputs_from_extraction, write_coverage
    from .synthesis import (
        build_synthesis_input,
        render_notes_md,
        render_transcript_md,
        write_synthesis_input,
        write_text,
    )
    from .vad import detect_speech_spans

    source = classify_source(source_argument)
    metadata = media.probe_source(source)
    metadata_title = metadata.title
    metadata_duration = metadata.duration
    metadata_video_id = metadata.video_id
    fallback_title = metadata_video_id or source.video_id or source.title_hint or "video"
    title_seed = metadata_title or fallback_title
    if exact_output_dir is not None:
        out_dir = os.path.realpath(os.path.abspath(exact_output_dir))
        os.makedirs(out_dir, exist_ok=True)
    else:
        out_root = os.path.dirname(out_dir_hint) or "."
        out_dir = _reserve_output_dir(
            out_root,
            title_seed,
            fallback=fallback_title,
            reserved_output_dirs=reserved_output_dirs,
        )
        os.makedirs(out_dir, exist_ok=True)

    # Speech acquisition is common to every source. Caption policy lives in
    # acquisition; local inputs go directly through the STT resolver.
    track = acquisition.acquire_speech(source, out_dir, force_stt=force_stt, model=model)
    title = metadata_title or track.meta.get("title") or fallback_title
    duration = _positive_finite_duration(metadata_duration, track.meta.get("duration"))

    frames_dir = os.path.join(out_dir, "frames")
    raw_frames = []
    slide_frames = []
    representative_frames = []
    ocr_engine = "not_applicable"
    ocr_status = "skipped"
    ocr_failed = False
    source_resolution = {"width": None, "height": None}
    if source.has_video:
        os.makedirs(frames_dir, exist_ok=True)
        video_path = media.resolve_video(source, out_dir)
        if video_path is None:  # defensive: source capability and resolver agree
            raise RuntimeError("Video source did not resolve to a video path")
        width, height = media.probe_video_resolution(video_path)
        source_resolution = {"width": width, "height": height}
        raw_frames = visual.extract_candidate_frames(video_path, frames_dir)
        slides = visual.dedupe_frames(raw_frames)
        representative_frames = list(slides)
        if skip_ocr:
            # Deduplicated scene frames remain first-class synthesis artifacts;
            # no OCR module import or call occurs in this branch.
            for frame in slides:
                frame.ocr_text = ""
                frame.is_slide = True
            slide_frames = slides
            ocr_engine = "skipped"
            ocr_status = "skipped"
        else:
            from .ocr import ocr_frames

            try:
                slide_frames, ocr_engine = ocr_frames(slides)
                ocr_status = "completed-with-text" if any(
                    (frame.ocr_text or "").strip() for frame in representative_frames
                ) else "completed-no-text"
            except Exception:  # noqa: BLE001 - expose only a bounded contract code
                # Keep every deduplicated frame as visual evidence even when
                # OCR fails part way through annotating the list.
                slide_frames = []
                ocr_engine = "failed"
                ocr_status = "failed"
                ocr_failed = True
    elif source.kind.value not in {"local_audio"}:
        raise ValueError(f"Unsupported source kind: {source.kind!r}")

    audio_path = track.meta.get("audio_path", os.path.join(out_dir, "audio.wav"))
    speech_spans = (
        detect_speech_spans(audio_path, duration)
        if os.path.isfile(audio_path)
        else [(0.0, duration)]
    )

    source_dict = {**source.safe_as_dict(), "resolution": source_resolution}
    video = {
        "title": title,
        "duration_sec": duration,
        "language": track.language,
        "speech_source": track.source,
        "input_source": source_dict,
    }
    segments = [segment.as_dict() for segment in track.segments]
    slide_dicts = [
        {
            "t": frame.timestamp,
            "frame": _frame_link(frame.image_path, out_dir),
            "ocr_text": frame.ocr_text if _ocr_reliable(frame, ocr_status) else "",
            "is_slide": True,
        }
        for frame in slide_frames
    ]

    synthesis_input = build_synthesis_input(video, segments, slide_dicts)
    transcript_path = os.path.join(out_dir, "transcript.md")
    notes_path = os.path.join(out_dir, "notes.md")
    transcript_md = render_transcript_md(video, segments)
    write_text(transcript_md, transcript_path)
    write_synthesis_input(synthesis_input, os.path.join(out_dir, "synthesis_input.json"))

    raw_sample_times = [frame.timestamp for frame in raw_frames]
    visual_required = source.has_video
    ocr_required = source.has_video and not skip_ocr

    def _cov_inputs(notes_md_text: str | None):
        return coverage_inputs_from_extraction(
            video_title=title,
            duration_sec=duration,
            speech_spans=speech_spans,
            segment_times=[segment["t"] for segment in segments],
            raw_sample_times=raw_sample_times,
            slides=slide_dicts,
            transcript_path=transcript_path,
            notes_path=notes_path,
            ocr_engine=ocr_engine,
            visual_required=visual_required,
            ocr_required=ocr_required,
            ocr_failed=ocr_failed,
            transcript_text=transcript_md,
            notes_text=notes_md_text,
        )

    draft_coverage = build_coverage(_cov_inputs(""))
    draft_notes_md = render_notes_md(synthesis_input, draft_coverage)
    coverage = build_coverage(_cov_inputs(draft_notes_md))
    notes_md = render_notes_md(synthesis_input, coverage)
    coverage = build_coverage(_cov_inputs(notes_md))
    write_text(notes_md, notes_path)
    coverage_path = write_coverage(coverage, os.path.join(out_dir, "coverage.json"))
    # OCR annotates frames; it does not decide which visual evidence survives.
    visual.cleanup_raw_frames(raw_frames, representative_frames, keep_frames=keep_frames)

    representative_frame_dicts = [
        {
            "timestamp_sec": round(float(frame.timestamp), 3),
            "path": os.path.abspath(frame.image_path),
            "ocr_text": frame.ocr_text,
            "is_slide": bool(frame.is_slide),
            "reliable": _ocr_reliable_or_none(frame, ocr_status),
            "width": frame.meta.get("width"),
            "height": frame.meta.get("height"),
        }
        for frame in representative_frames
    ]

    return {
        "output_dir": out_dir,
        "coverage_json": coverage_path,
        "notes_md": notes_path,
        "transcript_md": transcript_path,
        "synthesis_input_json": os.path.join(out_dir, "synthesis_input.json"),
        "source": source_dict,
        "source_kind": source.kind.value,
        "coverage": coverage,
        "transcript_segments": segments,
        "representative_frames": representative_frame_dicts,
        "frames_dir": frames_dir if source.has_video else None,
        "ocr_status": ocr_status,
        "ocr_engine": ocr_engine,
        "ocr_failed": ocr_failed,
        "overall_pass": coverage["overall_pass"],
    }


def _emit_json(payload: dict) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")


def _extract_reasons(result: dict) -> list[dict]:
    coverage = result.get("coverage") or {}
    reasons: list[dict] = []
    gap = coverage.get("gap_check") or {}
    scene = coverage.get("scene_coverage") or {}
    artifacts = coverage.get("artifacts") or {}
    notes_contract = coverage.get("notes_contract") or {}
    if not gap.get("pass", False):
        reasons.append(evidence.reason("SPEECH_INCOMPLETE"))
    if scene.get("visual_required", True) and not scene.get("timeline_pass", False):
        reasons.append(evidence.reason("VISUAL_INCOMPLETE"))
    if scene.get("ocr_required", False) and scene.get("ocr_failed", False):
        reasons.append(evidence.reason("OCR_FAILED"))
    elif scene.get("ocr_required", False) and not scene.get("slide_text_pass", False):
        reasons.append(evidence.reason("OCR_INCOMPLETE"))
    if not artifacts.get("pass", False):
        reasons.append(evidence.reason("ARTIFACT_INCOMPLETE"))
    if not notes_contract.get("pass", True):
        reasons.append(evidence.reason("NOTES_CONTRACT_INVALID"))
    return reasons


def _extract_main(args: argparse.Namespace) -> int:
    """Run one source through the public extraction contract."""
    try:
        source = classify_source(args.source)
    except FileNotFoundError:
        _emit_json(evidence.build_failure_response("SOURCE_UNAVAILABLE"))
        return 2
    except (TypeError, ValueError):
        _emit_json(evidence.build_failure_response("SOURCE_INVALID"))
        return 2

    try:
        output_dir = evidence.prepare_empty_output(args.out)
    except evidence.ContractError as exc:
        _emit_json(evidence.build_failure_response(exc.code))
        return 2

    diagnostics = io.StringIO()
    try:
        with redirect_stdout(diagnostics):
            result = _default_processor(
                args.source,
                output_dir,
                args.force_stt,
                args.model,
                skip_ocr=args.skip_ocr,
                exact_output_dir=output_dir,
            )
    except Exception:  # noqa: BLE001 - never expose traceback or source details
        if diagnostics.getvalue().strip():
            print(diagnostics.getvalue(), file=sys.stderr, end="")
        _emit_json(evidence.build_failure_response(
            "EXTRACTION_FAILED",
            output_dir=output_dir,
            source=source.safe_as_dict(),
        ))
        return 1
    if diagnostics.getvalue().strip():
        print(diagnostics.getvalue(), file=sys.stderr, end="")

    frame_items = result.get("representative_frames", [])
    timestamp = evidence.timestamp_integrity(
        (result.get("coverage") or {}).get("duration_sec", 0),
        result.get("transcript_segments", []),
        frame_items,
        allow_unknown_duration=not bool((result.get("source") or source.safe_as_dict()).get("has_video", True)),
    )
    reasons = _extract_reasons(result)
    if not timestamp.get("pass", False):
        reasons.append(evidence.reason("TIMESTAMP_INVALID"))

    hard_failure = bool(result.get("ocr_failed")) or not timestamp.get("pass", False)
    if hard_failure:
        extraction_status = "fail"
        failure_code = "OCR_FAILED" if result.get("ocr_failed") else "TIMESTAMP_INVALID"
        failure_info = evidence.failure(failure_code)
    elif result.get("overall_pass"):
        extraction_status = "pass"
        failure_info = None
    else:
        extraction_status = "warn"
        failure_info = None

    evidence_path = os.path.join(output_dir, "evidence.json")
    try:
        manifest = evidence.build_evidence_manifest(
            source=result.get("source") or source.safe_as_dict(),
            output_dir=output_dir,
            paths={
                "output_dir": output_dir,
                "transcript_md": result.get("transcript_md"),
                "notes_md": result.get("notes_md"),
                "synthesis_input_json": result.get("synthesis_input_json"),
                "coverage_json": result.get("coverage_json"),
                "evidence_json": evidence_path,
                "frames_dir": result.get("frames_dir"),
            },
            coverage=result.get("coverage") or {},
            transcript_segments=result.get("transcript_segments", []),
            representative_frames=frame_items,
            ocr_status=result.get("ocr_status", "failed"),
            ocr_engine=result.get("ocr_engine", "failed"),
            extraction_status=extraction_status,
            reasons=reasons,
            failure_info=failure_info,
        )
    except evidence.ContractError as exc:
        _emit_json(evidence.build_failure_response(
            exc.code,
            output_dir=output_dir,
            source=source.safe_as_dict(),
        ))
        return 1
    except Exception:  # noqa: BLE001 - keep the public response bounded
        _emit_json(evidence.build_failure_response(
            "CONTRACT_INTERNAL",
            output_dir=output_dir,
            source=source.safe_as_dict(),
        ))
        return 1
    manifest["extraction_status"] = extraction_status
    try:
        evidence.write_json(manifest, evidence_path)
    except Exception:  # noqa: BLE001 - JSON response still gets a bounded error
        _emit_json(evidence.build_failure_response(
            "CONTRACT_INTERNAL",
            output_dir=output_dir,
            source=source.safe_as_dict(),
        ))
        return 1
    _emit_json(evidence.build_extract_response(manifest))
    return 0 if extraction_status == "pass" else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.command == "version":
        if getattr(args, "json", False):
            _emit_json(evidence.build_version_response())
        else:
            print(evidence.build_version_response()["tool_version"])
        return 0
    if args.command == "doctor":
        try:
            from . import doctor

            report = doctor.run(fix=args.fix)
            doctor.print_report(report, json_output=args.json)
            return int(report["exit_code"])
        except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
            print(f"lectural doctor: internal failure — {exc}", file=sys.stderr)
            return 1

    if args.command == "extract":
        return _extract_main(args)

    try:
        results = run(
            args.sources,
            out_root=args.out,
            force_stt=args.force_stt,
            model=args.model,
            keep_frames=args.keep_frames,
            skip_ocr=args.skip_ocr,
        )
    except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
        print(f"lectural: 실패 — {exc}", file=sys.stderr)
        return 1
    ok = all(result.get("overall_pass") for result in results)
    for result in results:
        mark = "OK" if result.get("overall_pass") else "미달"
        print(f"[{mark}] {result['output_dir']}")
    print("완료 게이트는 Stop 훅(scripts/completeness_hook.py)이 최종 검증합니다.")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
