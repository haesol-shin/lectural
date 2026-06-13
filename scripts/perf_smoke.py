#!/usr/bin/env python3
"""Non-product performance smoke harness for LecturAL.

This wraps the EXISTING lectural pipeline stage functions (it does not modify
`lectural/` product logic) to measure, for one real YouTube video:

  * per-stage wall-clock time (time.perf_counter), and
  * per-stage CPU% and RSS (peak/avg), sampled across the whole process tree
    so that ffmpeg / yt-dlp child processes are included.

It then runs the completeness hook as a subprocess and reports its exit code.

Usage:
    uv run --with psutil python scripts/perf_smoke.py \
        --url https://www.youtube.com/watch?v=19vYXnpDIyg \
        --sample-interval 0.2 --out ./output/perf-smoke

Output:
    <out>/perf_metrics.json   machine-readable per-stage metrics
    stdout                    human-readable summary

If a required external dependency is missing, the harness records the blocker in
perf_metrics.json (status="blocked") and exits non-zero WITHOUT fabricating any
timing/CPU/RAM numbers.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

# Make `import lectural` work regardless of where this is launched from.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


@dataclass
class StageSampler:
    """Background sampler attributing CPU%/RSS samples to the active stage."""

    interval: float
    _psutil: object
    _proc: object
    _stage: str = "idle"
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    # stage -> {"cpu": [..], "rss": [..]}
    samples: dict[str, dict[str, list[float]]] = field(default_factory=dict)

    def _tree(self) -> list[object]:
        procs = [self._proc]
        try:
            procs += self._proc.children(recursive=True)
        except Exception:  # noqa: BLE001
            pass
        return procs

    def _sample_once(self) -> tuple[float, float]:
        cpu = 0.0
        rss = 0.0
        for p in self._tree():
            try:
                cpu += p.cpu_percent(interval=None)
                rss += p.memory_info().rss
            except Exception:  # noqa: BLE001 (process may have exited)
                continue
        return cpu, rss

    def _loop(self) -> None:
        # Prime cpu_percent (first call returns 0.0 / establishes baseline).
        self._sample_once()
        while not self._stop.wait(self.interval):
            cpu, rss = self._sample_once()
            bucket = self.samples.setdefault(self._stage, {"cpu": [], "rss": []})
            bucket["cpu"].append(cpu)
            bucket["rss"].append(rss)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def set_stage(self, stage: str) -> None:
        self._stage = stage

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def summary(self) -> dict:
        out = {}
        for stage, b in self.samples.items():
            cpu = b["cpu"] or [0.0]
            rss = b["rss"] or [0.0]
            out[stage] = {
                "cpu_pct_avg": round(sum(cpu) / len(cpu), 1),
                "cpu_pct_peak": round(max(cpu), 1),
                "rss_mb_avg": round(sum(rss) / len(rss) / 1e6, 1),
                "rss_mb_peak": round(max(rss) / 1e6, 1),
                "n_samples": len(b["cpu"]),
            }
        return out


def _machine_spec() -> dict:
    return {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }


def _dep_versions() -> dict:
    import importlib

    out = {}
    for mod in ("yt_dlp", "faster_whisper", "cv2", "paddleocr", "webrtcvad", "numpy", "psutil"):
        try:
            m = importlib.import_module(mod)
            out[mod] = getattr(m, "__version__", "unknown")
        except Exception as exc:  # noqa: BLE001
            out[mod] = f"MISSING ({exc.__class__.__name__})"
    for binname in ("ffmpeg", "yt-dlp"):
        try:
            r = subprocess.run([binname, "-version"], capture_output=True, text=True, timeout=20)
            out[f"{binname} (binary)"] = (r.stdout or r.stderr).splitlines()[0] if r.returncode == 0 else "MISSING"
        except Exception:  # noqa: BLE001
            out[f"{binname} (binary)"] = "MISSING"
    return out


def _write_metrics(out_dir: str, payload: dict) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "perf_metrics.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def run(url: str, out_root: str, sample_interval: float, model: str, force_stt: bool) -> int:
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    base = {
        "harness": "scripts/perf_smoke.py",
        "command": f'uv run --with psutil python scripts/perf_smoke.py --url {url} --sample-interval {sample_interval} --out {out_root}',
        "url": url,
        "started_at": started_at,
        "machine": _machine_spec(),
        "dependency_versions": _dep_versions(),
        "sample_interval_sec": sample_interval,
    }

    # Preflight: refuse to fabricate metrics if the environment cannot run.
    try:
        import psutil  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        base.update(status="blocked", blocker=f"psutil not available: {exc}. Run via 'uv run --with psutil ...'.")
        path = _write_metrics(out_root, base)
        print(json.dumps(base, ensure_ascii=False, indent=2))
        print(f"[BLOCKED] metrics written to {path}", file=sys.stderr)
        return 3

    from lectural.deps import has_binary

    missing = [b for b in ("ffmpeg", "yt-dlp") if not has_binary(b)]
    if missing:
        base.update(
            status="blocked",
            blocker=f"Required binaries missing on PATH: {missing}. assert_acquisition_ready would fail; refusing to fabricate metrics.",
        )
        path = _write_metrics(out_root, base)
        print(json.dumps(base, ensure_ascii=False, indent=2))
        print(f"[BLOCKED] metrics written to {path}", file=sys.stderr)
        return 3

    import psutil

    sampler = StageSampler(interval=sample_interval, _psutil=psutil, _proc=psutil.Process(os.getpid()))
    stage_times: dict[str, float] = {}
    stage_errors: dict[str, str] = {}

    def timed(label: str, fn):
        sampler.set_stage(label)
        t0 = time.perf_counter()
        try:
            return fn(), None
        except Exception as exc:  # noqa: BLE001
            stage_errors[label] = f"{exc.__class__.__name__}: {exc}"
            raise
        finally:
            stage_times[label] = round(time.perf_counter() - t0, 3)

    # Lazy product imports (mirror cli._default_processor sequence, no edits to product).
    from lectural.acquisition import acquire_speech, extract_video_id
    from lectural.cli import _download_video, _frame_link, output_dir_for
    from lectural.coverage import build_coverage, coverage_inputs_from_extraction, write_coverage
    from lectural.deps import assert_acquisition_ready
    from lectural.ocr import ocr_frames
    from lectural.runstate import start_session, update_run
    from lectural.synthesis import (
        build_synthesis_input,
        render_summary_md,
        render_transcript_md,
        write_synthesis_input,
        write_text,
    )
    from lectural.vad import detect_speech_spans
    from lectural.visual import dedupe_frames, extract_candidate_frames

    assert_acquisition_ready()
    os.makedirs(out_root, exist_ok=True)
    work_hint = os.path.join(out_root, "_work")
    os.makedirs(work_hint, exist_ok=True)

    start_session([url])
    sampler.start()
    hook_exit: int | None = None
    overall_pass: bool | None = None
    out_dir = None
    try:
        track, _ = timed("acquisition", lambda: acquire_speech(url, work_hint, force_stt=force_stt))
        title = track.meta.get("title") or extract_video_id(url) or "video"
        out_dir = output_dir_for(out_root, title)
        frames_dir = os.path.join(out_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)

        video_path, _ = timed("video_download", lambda: _download_video(url, out_dir))
        raw_frames, _ = timed("visual_extract", lambda: extract_candidate_frames(video_path, frames_dir))
        slides, _ = timed("visual_dedupe", lambda: dedupe_frames(raw_frames))
        (slide_frames, ocr_engine), _ = timed("ocr", lambda: ocr_frames(slides))

        duration = float(track.meta.get("duration", 0.0))
        audio_path = track.meta.get("audio_path", os.path.join(work_hint, "audio.wav"))
        speech_spans, _ = timed(
            "vad",
            lambda: detect_speech_spans(audio_path, duration) if os.path.isfile(audio_path) else [(0.0, duration)],
        )

        video = {"title": title, "url": url, "duration_sec": duration,
                 "language": track.language, "source": track.source}
        segments = [s.as_dict() for s in track.segments]
        slide_dicts = [{"t": f.timestamp,
                        "frame": _frame_link(f.image_path, out_dir),
                        "ocr_text": f.ocr_text, "is_slide": True} for f in slide_frames]

        transcript_path = os.path.join(out_dir, "transcript.md")
        summary_path = os.path.join(out_dir, "summary.md")

        def _synth():
            si = build_synthesis_input(video, segments, slide_dicts)
            transcript_md = render_transcript_md(video, segments)
            write_text(transcript_md, transcript_path)
            write_synthesis_input(si, os.path.join(out_dir, "synthesis_input.json"))
            return si, transcript_md

        (si, transcript_md), _ = timed("synthesis", _synth)

        def _coverage():
            def _cov_inputs(summary_md_text):
                return coverage_inputs_from_extraction(
                    video_title=title, duration_sec=duration, speech_spans=speech_spans,
                    segment_times=[s["t"] for s in segments],
                    raw_sample_times=[f.timestamp for f in raw_frames],
                    slides=slide_dicts, transcript_path=transcript_path, summary_path=summary_path,
                    ocr_engine=ocr_engine,
                    transcript_text=transcript_md, summary_text=summary_md_text,
                )

            summary_md = render_summary_md(si, build_coverage(_cov_inputs("")))
            cov = build_coverage(_cov_inputs(summary_md))
            write_text(summary_md, summary_path)
            write_coverage(cov, os.path.join(out_dir, "coverage.json"))
            return cov

        coverage, _ = timed("coverage", _coverage)
        overall_pass = bool(coverage["overall_pass"])
        update_run(
            0,
            status="complete",
            output_dir=out_dir,
            coverage_json=os.path.join(out_dir, "coverage.json"),
            summary_md=summary_path,
        )

        def _hook():
            r = subprocess.run([sys.executable, os.path.join(_REPO_ROOT, "scripts", "completeness_hook.py")],
                               capture_output=True, text=True)
            return r.returncode
        hook_exit, _ = timed("completeness_hook", _hook)
    except Exception as exc:  # noqa: BLE001
        base["pipeline_error"] = f"{exc.__class__.__name__}: {exc}"
    finally:
        sampler.stop()

    base.update(
        status="completed" if not stage_errors and hook_exit == 0 else "partial",
        output_dir=out_dir,
        overall_pass=overall_pass,
        completeness_hook_exit=hook_exit,
        stage_wall_seconds=stage_times,
        stage_resource_usage=sampler.summary(),
        stage_errors=stage_errors,
        finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    path = _write_metrics(out_root, base)
    print(json.dumps(base, ensure_ascii=False, indent=2))
    print(f"[{base['status'].upper()}] metrics written to {path}", file=sys.stderr)
    return 0 if base["status"] == "completed" else 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="perf_smoke", description="LecturAL per-stage performance smoke")
    p.add_argument("--url", required=True)
    p.add_argument("--sample-interval", type=float, default=0.2)
    p.add_argument("--out", default="./output/perf-smoke")
    p.add_argument("--model", default="medium")
    p.add_argument("--force-stt", action="store_true")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    return run(args.url, args.out, args.sample_interval, args.model, args.force_stt)


if __name__ == "__main__":
    raise SystemExit(main())
