"""`lectural` CLI: extract evidence bundles and consume them as notes.

Usage:
    lectural extract <source> --out <directory> [--json]
    lectural notes <input> [<input> ...] [--out ./output]
    lectural doctor [--fix] [--json]
    lectural --version [--json]

Extraction creates versioned evidence; notes are one consumer of that bundle.
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



class _LecturalArgumentParser(argparse.ArgumentParser):
    """Root parser with a useful hint when a source is used as a command."""

    input_argv: list[str] = []

    def error(self, message: str) -> None:
        argv = self.input_argv
        if argv and _looks_like_source(argv[0]):
            message = (
                f"unknown command {argv[0]!r}; to generate notes use: "
                "lectural notes <source>"
            )
        super().error(message)


def _looks_like_source(value: str) -> bool:
    if os.path.isfile(os.path.expanduser(value)):
        return True
    if value.startswith(("http://", "https://")):
        return True
    try:
        classify_source(value)
    except (OSError, TypeError, ValueError):
        return False
    return True


def _cli_parser(argv: list[str]) -> argparse.ArgumentParser:
    parser = _LecturalArgumentParser(
        prog="lectural",
        description=(
            "Evidence comes first: extract creates a versioned evidence bundle; "
            "notes is one consumer that generates study notes."
        ),
        epilog=(
            "Use `lectural extract` to create evidence.json, or `lectural notes` "
            "to create notes from a source or an existing bundle."
        ),
    )
    parser.input_argv = argv
    parser.add_argument("--version", action="store_true", help="Show the LecturAL version")
    parser.add_argument("--json", dest="version_json", action="store_true", help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command")

    extract_parser = commands.add_parser(
        "extract",
        help="Extract a source into a versioned evidence bundle",
        description="Extract speech and visual evidence into a versioned bundle; does not generate notes.",
    )
    extract_parser.add_argument("source", help="One YouTube URL/ID or local media file")
    extract_parser.add_argument("--out", required=True, help="New, empty output directory")
    extract_parser.add_argument("--force-stt", action="store_true", help=argparse.SUPPRESS)
    extract_parser.add_argument("--model", default=DEFAULT_STT_MODEL, help=argparse.SUPPRESS)
    extract_parser.add_argument("--skip-ocr", action="store_true", help="Skip OCR while retaining representative frames")
    extract_parser.add_argument("--json", action="store_true", help="Print the versioned JSON response")

    notes_parser = commands.add_parser(
        "notes",
        help="Generate notes from a source or existing evidence bundle",
        description=(
            "For a source, extract evidence and then generate notes. For an existing "
            "directory with evidence.json, regenerate notes in that directory."
        ),
    )
    notes_parser.add_argument(
        "inputs",
        nargs="+",
        help="YouTube URL/ID, local media file, or evidence bundle directory (processed sequentially)",
    )
    notes_parser.add_argument(
        "--out",
        default="./output",
        help="Output root for source inputs; evidence bundles are always updated in place",
    )
    notes_parser.add_argument(
        "--force-stt",
        action="store_true",
        default=None,
        help="Skip captions and always transcribe source inputs",
    )
    notes_parser.add_argument("--model", default=None, help="faster-whisper model size (default: medium)")
    notes_parser.add_argument(
        "--skip-ocr",
        action="store_true",
        default=None,
        help="Keep scene frames but skip OCR for source inputs",
    )
    notes_parser.add_argument(
        "--keep-frames",
        action="store_true",
        default=None,
        help="Archive raw sampled frames for source inputs",
    )

    doctor_parser = commands.add_parser(
        "doctor",
        help="Validate LecturAL runtime and plugin distribution",
        description="Validate LecturAL runtime and plugin distribution",
    )
    doctor_parser.add_argument("--fix", action="store_true", help="Attempt safe bounded fixes for missing yt-dlp/ffmpeg")
    doctor_parser.add_argument("--json", action="store_true", help="Print a machine-readable JSON report")
    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    argv = list(argv)
    parser = _cli_parser(argv)
    if not argv:
        parser.print_help()
        parser.exit(2)
    args = parser.parse_args(argv)
    if args.command is None:
        if getattr(args, "version", False):
            args.command = "version"
            return args
        parser.error("--version is required when no command is given")
    if getattr(args, "version", False) or getattr(args, "version_json", False):
        parser.error("--version and its --json option must be used without a command")
    return args

def _captured_stderr(exc: BaseException) -> str:
    value = getattr(exc, "stderr", None)
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    return value.strip() if isinstance(value, str) else ""


def _run_error_message(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    stderr = _captured_stderr(exc)
    if stderr:
        message = f"{message}\n{stderr[-500:]}"
    return message

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
            error_message = _run_error_message(exc)
            runstate.update_run(
                index,
                status="failed",
                error=error_message,
                path=runstate_file,
            )
            results.append(
                {
                    "output_dir": out_dir,
                    "source": source_argument,
                    "overall_pass": False,
                    "error": error_message,
                }
            )
    return results


def _is_evidence_bundle(argument: str) -> bool:
    path = os.path.expanduser(argument)
    return os.path.isdir(path) and os.path.isfile(os.path.join(path, "evidence.json"))


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
    """Extract source evidence and pass the bundle to the notes consumer."""
    if _is_evidence_bundle(source_argument):
        from . import notes

        return notes.generate_notes(source_argument)

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
    except Exception as exc:  # noqa: BLE001 - never expose traceback or source details
        if diagnostics.getvalue().strip():
            print(diagnostics.getvalue(), file=sys.stderr, end="")
        error_output = _captured_stderr(exc)
        if error_output:
            print(error_output[-500:], file=sys.stderr)
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
        if args.version_json:
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

    bundle_inputs = [value for value in args.inputs if _is_evidence_bundle(value)]
    extraction_options = (
        ("--force-stt", args.force_stt is not None),
        ("--model", args.model is not None),
        ("--skip-ocr", args.skip_ocr is not None),
        ("--keep-frames", args.keep_frames is not None),
    )
    used_options = [option for option, used in extraction_options if used]
    if bundle_inputs and used_options:
        joined = ", ".join(used_options)
        print(
            f"lectural notes: {joined} apply only to source inputs and cannot be used with evidence bundles.",
            file=sys.stderr,
        )
        return 2

    try:
        results = run(
            args.inputs,
            out_root=args.out,
            force_stt=bool(args.force_stt),
            model=args.model or DEFAULT_STT_MODEL,
            keep_frames=bool(args.keep_frames),
            skip_ocr=bool(args.skip_ocr),
        )
    except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
        print(f"lectural notes: failed — {exc}", file=sys.stderr)
        return 1
    ok = all(result.get("overall_pass") for result in results)
    for result in results:
        mark = "OK" if result.get("overall_pass") else "FAIL"
        print(f"[{mark}] {result['output_dir']}")
        if not result.get("overall_pass") and result.get("error"):
            print(result["error"], file=sys.stderr)
    print("The Stop hook (scripts/completeness_hook.py) performs the final completeness check.")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
