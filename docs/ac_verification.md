# AC-1..AC-13 Verification Matrix

Offline command: `uv run --with pytest --with numpy pytest -q` → **112 passed**.
Real-invocation evidence: `artifacts/g00*-pytest.txt`, `artifacts/g003-hook-smoke.txt`.

| AC | Requirement | How verified | Status |
|----|-------------|--------------|--------|
| AC-1 | Single URL runs end-to-end, output folder created | `tests/test_cli.py::test_run_single` (injected processor proves orchestration + runstate); real pipeline needs binaries → **smoke** | unit (orchestration) + smoke (real video) |
| AC-2 | Multiple URLs processed sequentially, per-URL folders | `tests/test_cli.py::test_run_sequential_batch_records_each`, `test_redteam_cli_hook.py::test_cli_run_continues_batch_on_processor_error_and_records_failure` (every URL pre-registered + recorded) | unit ✅ |
| AC-3 | Captions used if present, else STT fallback | `tests/test_acquisition.py` (VTT/json3 parsers, usable-caption heuristic); `acquire_speech` source selection + `--force-stt`; live caption/STT switch → **smoke** | unit (parsers/selection) + smoke |
| AC-4 | STT = faster-whisper medium int8 CPU, timestamped | `lectural/speech.py` (device="cpu", compute_type=int8); `should_warn_long_video` unit; real transcription → **smoke** | unit (config/logic) + smoke |
| AC-5 | ffmpeg keyframe/scene extract + histogram/SSIM dedup | `tests/test_dedup.py`, `tests/test_ssim.py` (windowed SSIM); ffmpeg extraction → **smoke** | unit (dedup/SSIM) + smoke |
| AC-6 | OCR (ko/en) on slides, incremental re-split | `tests/test_ocr.py` (classify/re-split, is_slide); PaddleOCR/Tesseract run → **smoke** | unit (logic) + smoke |
| AC-7 | transcript.md (raw) + summary.md produced | `tests/test_summary_anchors.py::test_transcript_md_has_all_utterances`, `test_summary_md_required_anchors_present` | unit ✅ |
| AC-8 | summary.md TOC + coverage header + timestamp/slide links | `tests/test_summary_anchors.py` (anchors, escaping, no-drop); hook validates anchors `tests/test_hook.py` | unit ✅ |
| AC-9 | Transcript covers full duration; no >60s untranscribed speech gap | `tests/test_vad.py` (long-silence PASS, real-gap FAIL, quiet-speech); `coverage.gap_check` | unit ✅ |
| AC-10 | SKILL.md + scripts + references; callable in Claude/Codex | `.claude/skills/lectural/SKILL.md` + `references/`; `.claude/settings.json` Stop hook; `uv run python -m lectural.cli --help` | artifact + CLI ✅ |
| AC-11 | Core pipeline runs as standalone CLI/module | `lectural` console script + `python -m lectural.cli`; `tests/test_cli.py` parse/run; package imports offline | unit + CLI ✅ |
| AC-12 | Outputs to ./output/<title>/ {transcript,summary,frames,coverage.json} | `lectural/cli.py` output_dir_for + `_default_processor` layout; `tests/test_cli.py::test_output_dir_for`; coverage.json schema round-trip `tests/test_coverage.py` | unit ✅ (layout) + smoke (files) |
| AC-13 | Completeness hook: gap + scene + artifacts; exit 2 blocks done | `tests/test_hook.py` + `tests/test_redteam_cli_hook.py`; **real**: `artifacts/g003-hook-smoke.txt` (no-runstate→0, good→0, failed/pending→2, malformed→2) | unit ✅ + CLI ✅ |

## Smoke (requires ffmpeg + yt-dlp + models; not run in this environment)

ffmpeg/yt-dlp/tesseract are NOT installed here, so live acquisition/STT/visual/OCR
paths are exercised by a real-video smoke run after `uv pip install -e ".[run]"`
and installing the binaries. Suggested smoke commands:

```bash
lectural "https://www.youtube.com/watch?v=<captioned-lecture>"   # AC-1,3,7,8,12
lectural "<url-a>" "<url-b>"                                       # AC-2 sequential
lectural "<no-caption-url>" --force-stt --model medium            # AC-3,4 STT path
python scripts/completeness_hook.py < /dev/null                   # AC-13 (after a run)
```

Deterministic logic (dedup, gap, OCR re-split, anchors, coverage, hook, CLI
orchestration) is fully proven offline; only the external-binary I/O edges are
smoke-only.
