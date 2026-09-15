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
import inspect
import os
import re
import sys

from . import runstate
from .config import DEFAULT_STT_MODEL
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

    parser = _run_parser()
    args = parser.parse_args(argv)
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
        return processor(source_argument, out_dir, force_stt, model, **kwargs)

    runstate.start_session(sources, runstate_file)
    results: list[dict] = []
    for index, source_argument in enumerate(sources):
        out_dir = os.path.join(out_root, f"video_{index + 1:02d}")  # provisional
        try:
            result = _call_processor(source_argument, out_dir)
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
    out_root = os.path.dirname(out_dir_hint) or "."
    out_dir = output_dir_for(out_root, title_seed, fallback=fallback_title)
    os.makedirs(out_dir, exist_ok=True)

    # Speech acquisition is common to every source. Caption policy lives in
    # acquisition; local inputs go directly through the STT resolver.
    track = acquisition.acquire_speech(source, out_dir, force_stt=force_stt, model=model)
    title = metadata_title or track.meta.get("title") or fallback_title
    duration = float(metadata_duration or track.meta.get("duration") or 0.0)

    frames_dir = os.path.join(out_dir, "frames")
    raw_frames = []
    slide_frames = []
    ocr_engine = "not_applicable"
    if source.has_video:
        os.makedirs(frames_dir, exist_ok=True)
        video_path = media.resolve_video(source, out_dir)
        if video_path is None:  # defensive: source capability and resolver agree
            raise RuntimeError("Video source did not resolve to a video path")
        raw_frames = visual.extract_candidate_frames(video_path, frames_dir)
        slides = visual.dedupe_frames(raw_frames)
        if skip_ocr:
            # Deduplicated scene frames remain first-class synthesis artifacts;
            # no OCR module import or call occurs in this branch.
            for frame in slides:
                frame.ocr_text = ""
                frame.is_slide = True
            slide_frames = slides
            ocr_engine = "skipped"
        else:
            from .ocr import ocr_frames

            slide_frames, ocr_engine = ocr_frames(slides)
    elif source.kind.value not in {"local_audio"}:
        raise ValueError(f"Unsupported source kind: {source.kind!r}")

    audio_path = track.meta.get("audio_path", os.path.join(out_dir, "audio.wav"))
    speech_spans = (
        detect_speech_spans(audio_path, duration)
        if os.path.isfile(audio_path)
        else [(0.0, duration)]
    )

    video = {
        "title": title,
        "duration_sec": duration,
        "language": track.language,
        "speech_source": track.source,
        "input_source": source.as_dict(),
    }
    segments = [segment.as_dict() for segment in track.segments]
    slide_dicts = [
        {
            "t": frame.timestamp,
            "frame": _frame_link(frame.image_path, out_dir),
            "ocr_text": frame.ocr_text,
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
    visual.cleanup_raw_frames(raw_frames, slide_frames, keep_frames=keep_frames)

    return {
        "output_dir": out_dir,
        "coverage_json": coverage_path,
        "notes_md": notes_path,
        "transcript_md": transcript_path,
        "overall_pass": coverage["overall_pass"],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.command == "doctor":
        try:
            from . import doctor

            report = doctor.run(fix=args.fix)
            doctor.print_report(report, json_output=args.json)
            return int(report["exit_code"])
        except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
            print(f"lectural doctor: internal failure — {exc}", file=sys.stderr)
            return 1

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
