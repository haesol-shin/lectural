"""`lectural` CLI: turn video into deterministic evidence for video-based work.

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
import os
import re
import sys

from . import evidence
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



def _run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lectural",
        description="Video-based work -> deterministic evidence as markdown notes",
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
        description="Extract a versioned JSON evidence bundle from one source",
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
    processor = processor or _extract_then_notes_processor
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


def _extract_then_notes_processor(
    source_argument: str,
    out_dir_hint: str,
    force_stt: bool,
    model: str,
    *,
    keep_frames: bool = False,
    skip_ocr: bool = False,
    reserved_output_dirs: set[str] | None = None,
) -> dict:
    """Compose the evidence extractor with the notes consumer for bare runs."""
    from . import extract, media, notes

    source = classify_source(source_argument)
    metadata = media.probe_source(source)
    fallback_title = metadata.video_id or source.video_id or source.title_hint or "video"
    title = metadata.title or fallback_title
    out_root = os.path.dirname(out_dir_hint) or "."
    out_dir = _reserve_output_dir(
        out_root,
        title,
        fallback=fallback_title,
        reserved_output_dirs=reserved_output_dirs,
    )
    os.makedirs(out_dir, exist_ok=True)
    result = extract.extract_source(
        source_argument,
        out_dir,
        force_stt=force_stt,
        model=model,
        keep_frames=keep_frames,
        skip_ocr=skip_ocr,
        source=source,
        metadata=metadata,
    )
    notes_result = notes.generate_notes(out_dir)
    return {
        **notes_result,
        "source": result["manifest"]["source"],
        "manifest": result["manifest"],
        "overall_pass": notes_result["overall_pass"],
    }


def _emit_json(payload: dict) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")


def _extract_main(args: argparse.Namespace) -> int:
    """Run one source through the public extraction contract."""
    from . import extract

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
            result = extract.extract_source(
                args.source,
                output_dir,
                force_stt=args.force_stt,
                model=args.model,
                skip_ocr=args.skip_ocr,
                source=source,
            )
    except evidence.ContractError as exc:
        if diagnostics.getvalue().strip():
            print(diagnostics.getvalue(), file=sys.stderr, end="")
        _emit_json(evidence.build_failure_response(
            exc.code,
            output_dir=output_dir,
            source=source.safe_as_dict(),
        ))
        return 1
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

    manifest = result["manifest"]
    _emit_json(evidence.build_extract_response(manifest))
    return 0 if manifest["extraction"]["status"] == "pass" else 1

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
