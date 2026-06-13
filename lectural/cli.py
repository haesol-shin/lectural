"""`lectural` CLI: turn YouTube lecture URL(s) into complete study notes.

Usage:
    lectural <url> [<url> ...] [--force-stt] [--model medium] [--out ./output]

Single URL or a SEQUENTIAL batch (AC-1, AC-2). The per-video pipeline is the
real (lazy) module stack; orchestration (arg parsing, slugging, batch loop,
run-state recording) is pure and unit-tested with an injected processor so it
runs offline without ffmpeg/yt-dlp/models.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from . import runstate
from .config import DEFAULT_STT_MODEL


def slugify(title: str, fallback: str = "video") -> str:
    """Pure: filesystem-safe directory name from a video title."""
    title = (title or "").strip()
    slug = re.sub(r"[^\w\-가-힣]+", "-", title, flags=re.UNICODE).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or fallback)[:80]


def output_dir_for(out_root: str, title: str, fallback: str = "video") -> str:
    """Pure: ./out_root/<slug> path for a video's artifacts (AC-12)."""
    return os.path.join(out_root, slugify(title, fallback))

def _frame_link(image_path: str, out_dir: str) -> str:
    """Pure: relative slide-image path as a POSIX markdown link (Windows-safe)."""
    return os.path.relpath(image_path, out_dir).replace(os.sep, "/")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="lectural", description="YouTube lecture -> complete study notes")
    p.add_argument("urls", nargs="+", help="One or more YouTube URLs (processed sequentially)")
    p.add_argument("--force-stt", action="store_true", help="Skip captions; always transcribe with STT")
    p.add_argument("--model", default=DEFAULT_STT_MODEL, help="faster-whisper model size (default: medium)")
    p.add_argument("--out", default="./output", help="Output root directory (default: ./output)")
    return p.parse_args(argv)


def run(
    urls: list[str],
    out_root: str = "./output",
    force_stt: bool = False,
    model: str = DEFAULT_STT_MODEL,
    processor=None,
    runstate_file: str | None = None,
) -> list[dict]:
    """Sequentially process each URL; pre-register and record EVERY run.

    `processor(url, out_dir, force_stt, model) -> dict` is injectable; the
    default uses the real pipeline. Each result dict must include output_dir,
    coverage_json, summary_md, transcript_md, and overall_pass.

    Every URL is pre-registered as `pending` so a failed or unproduced video
    stays visible to the completeness hook (it cannot be hidden by aborting).
    A processor failure is recorded and the batch CONTINUES to the next URL.
    """
    processor = processor or _default_processor
    runstate.start_session(urls, runstate_file)
    results: list[dict] = []
    for i, url in enumerate(urls):
        out_dir = os.path.join(out_root, f"video_{i + 1:02d}")  # provisional
        try:
            result = processor(url, out_dir, force_stt, model)
            runstate.update_run(
                i,
                status="complete",
                output_dir=result["output_dir"],
                coverage_json=result["coverage_json"],
                summary_md=result["summary_md"],
                path=runstate_file,
            )
            results.append(result)
        except Exception as exc:  # noqa: BLE001 - record + continue, do not hide failures
            runstate.update_run(i, status="failed", error=f"{type(exc).__name__}: {exc}", path=runstate_file)
            results.append({"output_dir": out_dir, "url": url, "overall_pass": False,
                            "error": f"{type(exc).__name__}: {exc}"})
    return results


def _default_processor(url: str, out_dir_hint: str, force_stt: bool, model: str) -> dict:
    """Real pipeline for one video (lazy heavy deps; smoke-tested, not unit)."""
    from .acquisition import acquire_speech, extract_video_id, fetch_video_metadata
    from .coverage import build_coverage, coverage_inputs_from_extraction, write_coverage
    from .deps import assert_acquisition_ready
    from .ocr import ocr_frames
    from .synthesis import (
        build_synthesis_input,
        render_summary_md,
        render_transcript_md,
        write_synthesis_input,
        write_text,
    )
    from .vad import detect_speech_spans
    from .visual import dedupe_frames, extract_candidate_frames

    assert_acquisition_ready()
    out_root = os.path.dirname(out_dir_hint) or "."

    # 1. Metadata first: it determines the real artifact directory before any
    # captions/STT path can be selected.
    metadata = fetch_video_metadata(url)
    fallback_title = metadata.get("video_id") or extract_video_id(url) or "video"
    title_seed = metadata.get("title") or fallback_title
    out_dir = output_dir_for(out_root, title_seed, fallback=fallback_title)
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    # 2. Speech track (captions-first, STT fallback) writes into the final
    # title/video-id directory, not the provisional batch slot.
    track = acquire_speech(url, out_dir, force_stt=force_stt)
    track.meta.update({k: v for k, v in metadata.items() if v not in (None, "")})
    title = track.meta.get("title") or fallback_title

    # 3. Visual track: extract RAW candidate frames, dedupe to slides, OCR.
    video_path = _download_video(url, out_dir)
    raw_frames = extract_candidate_frames(video_path, frames_dir)
    slides = dedupe_frames(raw_frames)
    slide_frames, ocr_engine = ocr_frames(slides)

    duration = float(track.meta.get("duration") or 0.0)
    audio_path = track.meta.get("audio_path", os.path.join(out_dir, "audio.wav"))
    speech_spans = detect_speech_spans(audio_path, duration) if os.path.isfile(audio_path) else [(0.0, duration)]

    video = {"title": title, "url": url, "duration_sec": duration,
             "language": track.language, "source": track.source}
    segments = [s.as_dict() for s in track.segments]
    # Frame links are markdown/web paths -> always POSIX separators (so the
    # slide-link check and rendered links work on Windows too).
    slide_dicts = [{"t": f.timestamp,
                    "frame": _frame_link(f.image_path, out_dir),
                    "ocr_text": f.ocr_text, "is_slide": True} for f in slide_frames]

    # 4. Synthesis (deterministic, token-zero).
    si = build_synthesis_input(video, segments, slide_dicts)
    transcript_path = os.path.join(out_dir, "transcript.md")
    summary_path = os.path.join(out_dir, "summary.md")
    transcript_md = render_transcript_md(video, segments)
    write_text(transcript_md, transcript_path)
    write_synthesis_input(si, os.path.join(out_dir, "synthesis_input.json"))

    # 5. Coverage (raw sample times enforce the carry-cap contract). Render the
    # summary first so the artifact check judges the rendered content, not file
    # write ordering: build a coverage view to render the summary header, then
    # finalize coverage with the actual rendered transcript/summary text.
    def _cov_inputs(summary_md_text: str | None) -> "object":
        return coverage_inputs_from_extraction(
            video_title=title, duration_sec=duration, speech_spans=speech_spans,
            segment_times=[s["t"] for s in segments],
            raw_sample_times=[f.timestamp for f in raw_frames],
            slides=slide_dicts, transcript_path=transcript_path, summary_path=summary_path,
            ocr_engine=ocr_engine,
            transcript_text=transcript_md, summary_text=summary_md_text,
        )

    summary_md = render_summary_md(si, build_coverage(_cov_inputs("")))
    coverage = build_coverage(_cov_inputs(summary_md))
    write_text(summary_md, summary_path)
    coverage_path = write_coverage(coverage, os.path.join(out_dir, "coverage.json"))

    return {
        "output_dir": out_dir,
        "coverage_json": coverage_path,
        "summary_md": summary_path,
        "transcript_md": transcript_path,
        "overall_pass": coverage["overall_pass"],
    }


def _download_video(url: str, out_dir: str) -> str:
    """Download the video (for frame extraction) via yt-dlp. Lazy/subprocess."""
    import subprocess

    os.makedirs(out_dir, exist_ok=True)
    out_template = os.path.join(out_dir, "video.%(ext)s")
    subprocess.run(["yt-dlp", "-f", "bestvideo[height<=720]+bestaudio/best",
                    "-o", out_template, url], check=True)
    for name in os.listdir(out_dir):
        if name.startswith("video."):
            return os.path.join(out_dir, name)
    raise RuntimeError("Video download did not produce a video file")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        results = run(args.urls, out_root=args.out, force_stt=args.force_stt, model=args.model)
    except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
        print(f"lectural: 실패 — {exc}", file=sys.stderr)
        return 1
    ok = all(r.get("overall_pass") for r in results)
    for r in results:
        mark = "OK" if r.get("overall_pass") else "미달"
        print(f"[{mark}] {r['output_dir']}")
    print("완료 게이트는 Stop 훅(scripts/completeness_hook.py)이 최종 검증합니다.")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
