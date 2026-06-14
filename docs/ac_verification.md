# AC-1..AC-18 Verification Matrix

Offline verification is split across focused suites; use `uv run --with pytest --with numpy pytest -q` for the full offline suite or the narrower commands named below.
Real-invocation evidence: `artifacts/g00*-pytest.txt`, `artifacts/g003-hook-smoke.txt`.

| AC | Requirement | How verified | Status |
|----|-------------|--------------|--------|
| AC-1 | Single URL runs end-to-end, output folder created | `tests/test_cli.py::test_run_single` (injected processor proves orchestration + runstate); real pipeline needs binaries → **smoke** | unit (orchestration) + smoke (real video) |
| AC-2 | Multiple URLs processed sequentially, per-URL folders | `tests/test_cli.py::test_run_sequential_batch_records_each`, `test_redteam_cli_hook.py::test_cli_run_continues_batch_on_processor_error_and_records_failure` (every URL pre-registered + recorded) | unit ✅ |
| AC-3 | Captions used if present, else STT fallback | `tests/test_acquisition.py` (VTT/json3 parsers, usable-caption heuristic); `acquire_speech` source selection + `--force-stt`; live caption/STT switch → **smoke** | unit (parsers/selection) + smoke |
| AC-4 | STT = faster-whisper medium int8 CPU, timestamped | `lectural/speech.py` (device="cpu", compute_type=int8); `should_warn_long_video` unit; real transcription → **smoke** | unit (config/logic) + smoke |
| AC-5 | ffmpeg keyframe/scene extract + histogram/SSIM dedup | `tests/test_dedup.py`, `tests/test_ssim.py` (windowed SSIM); ffmpeg extraction → **smoke** | unit (dedup/SSIM) + smoke |
| AC-6 | OCR (ko/en) on slides, incremental re-split | `tests/test_ocr.py` (classify/re-split, is_slide); PaddleOCR/Tesseract run → **smoke** | unit (logic) + smoke |
| AC-7 | transcript.md (raw) + notes.md produced | `tests/test_notes.py::test_render_transcript_md_emits_anchor_per_cue`, `tests/test_notes.py::test_notes_sections_are_in_required_order_and_marker_is_line_one` | unit ✅ |
| AC-8 | notes.md 7-section contract: NOTES marker on line 1, ordered section anchors, transcript.md cue anchors, and citation deeplinks from 핵심 개념·이론/상세 노트 bullets to `transcript.md#tHHMMSS[-n]` + `youtu.be?t=`; two-layer gate validates notes.md with CLI coverage and Claude Stop hook | `tests/test_notes.py` (anchors, citations, transcript grounding); `tests/test_redteam_notes.py` (adversarial citation/legacy-marker checks); `tests/test_coverage.py`; `tests/test_hook.py` | unit ✅ |
| AC-9 | Transcript covers full duration; no >60s untranscribed speech gap | `tests/test_vad.py` (long-silence PASS, real-gap FAIL, quiet-speech); `coverage.gap_check` | unit ✅ |
| AC-10 | SKILL.md + scripts + references; callable in Claude/Codex | `.claude/skills/lectural/SKILL.md` + `references/`; `.claude/settings.json` Stop hook; `uv run python -m lectural.cli --help` | artifact + CLI ✅ |
| AC-11 | Core pipeline runs as standalone CLI/module | `lectural` console script + `python -m lectural.cli`; `tests/test_cli.py` parse/run; package imports offline | unit + CLI ✅ |
| AC-12 | Outputs to ./output/<title>/ {transcript.md, notes.md, frames, coverage.json} | `lectural/cli.py` output_dir_for + `_default_processor` layout; `tests/test_cli.py::test_output_dir_for`; notes/coverage.json schema round-trip `tests/test_cli.py`, `tests/test_coverage.py` | unit ✅ (layout) + smoke (files) |
| AC-13 | Completeness hook: gap + scene + notes.md contract + artifacts; exit 2 blocks done | `tests/test_hook.py` + `tests/test_redteam_cli_hook.py`; **real**: `artifacts/g003-hook-smoke.txt` (no-runstate→0, good→0, failed/pending→2, malformed→2) | unit ✅ + CLI ✅ |
| AC-15 | `coverage.json` folds `notes_contract` into `overall_pass` | `tests/test_coverage.py::test_bare_skeleton_notes_contract_is_marker_agnostic`, `::test_notes_contract_dangling_concept_anchor_fails_coverage`, `::test_notes_contract_youtube_seconds_mismatch_fails_coverage`; adversarial coverage folding in `tests/test_redteam_notes.py` and `tests/test_redteam_notes_contract.py` | unit ✅ |
| AC-16 | Stop hook validates the seven required notes sections and per-slide detail blocks: every `###` slide heading needs a bullet, and every non-intro slide heading needs its own `frames/` image when frames exist | `tests/test_hook.py` section-order failures, `test_hook_passes_when_every_slide_heading_has_image_and_bullet`, `test_hook_blocks_when_non_intro_slide_heading_lacks_own_image`, `test_hook_allows_intro_heading_without_image_when_real_slides_have_images`, `test_hook_blocks_when_slide_heading_has_image_but_no_bullet`; red-team checks in `tests/test_redteam_notes_contract.py` | unit ✅ |
| AC-17 | Full citation gate: 핵심 개념·이론/상세 노트 bullets cite `transcript.md#t<id>` that exists in `transcript.md` plus `youtu.be...?t=` within ±1s | `tests/test_notes.py`; `tests/test_redteam_notes.py` citation/deeplink tests; `tests/test_redteam_notes_contract.py::test_coverage_contract_rejects_dangling_anchor_and_missing_youtube`, `::test_youtube_seconds_tolerance_is_one_second` | unit ✅ |
| AC-18 | Stop hook blocks while `미보강` remains; CLI coverage is marker-agnostic, so the bare skeleton can still exit 0 when Layer-1 coverage passes | `tests/test_hook.py::test_hook_blocks_bare_skeleton_because_unenriched_marker_remains`; `tests/test_coverage.py::test_bare_skeleton_notes_contract_is_marker_agnostic`; `tests/test_redteam_notes_contract.py::test_layer1_coverage_is_marker_agnostic_for_bare_skeleton` | unit ✅ |

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

## Next Release (2026-06-13) — AC-A..AC-J

Offline command: `uv run --with pytest --with numpy pytest -q` (adds CLI exit-code + deps OS-label tests).

| AC | Requirement | How verified | Status |
|----|-------------|--------------|--------|
| AC-A | `lectural` CLI exits non-zero (2) on coverage failure, 0 on success | `tests/test_cli.py::test_main_exit_2_on_coverage_failure`, `::test_main_exit_0_on_success` (monkeypatch `cli.run`) | unit ✅ |
| AC-B | Thin English `AGENTS.md`; Codex honors non-zero `lectural` exit; no coverage reimpl / no Stop-hook equivalence claim | `AGENTS.md` present; wording reviewed | artifact ✅ |
| AC-C | README documents Windows/Linux/macOS install + uvx run-extra path | `README.md` install section (winget/apt\|dnf/brew) + uvx section | artifact ✅ |
| AC-D | preflight emits OS-aware (win/linux/macos) hints; DepStatus/return shape unchanged | `lectural/deps.py` `_BINARY_HINTS` widened (strings only) + `tests/test_deps.py` label assertions | unit ✅ |
| AC-E | README positioning broadened to "YouTube video → complete notes" (lecture sweet spot) | `README.md` intro/tagline | artifact ✅ |
| AC-F | One real-video uvx e2e exits 0 + offline tests green | **BLOCKED (packaging)** — see note. Deterministic pipeline + gate proven exit 0 via earlier perf-smoke with pinned 2.x OCR deps (`docs/perf_smoke_2026-06-13.md`); offline suite 139 green. Plain `uvx --from ".[run]"` fails OCR. | partial ⚠ |
| AC-G | Language rule (README ko; AGENTS.md/SKILL/ci.yml/tests/deps strings en; identifiers en) | Hangul grep over English artifacts = 0 (except pre-existing Korean slug data in `test_cli.py::test_slugify`) | ✅ |
| AC-H | Work-unit git commits (uv/uvx) | 806b92f, c66f0e2, 49a6723, 5e5bce1, 83ce571, 6940b7a | ✅ |
| AC-I | README·AGENTS.md·SKILL share the two-layer gate wording; no "hook wraps CLI"/equivalence | grep forbidden phrasing = 0; SKILL bodies sha256-identical | ✅ |
| AC-J | `.github/workflows/ci.yml` runs offline suite on win/ubuntu/macos | `.github/workflows/ci.yml` matrix (smoke excluded) | artifact ✅ (CI run pending first push) |

### AC-F blocker — OCR engine not provisioned by `[run]` extra
The real-video `uvx --from ".[run]" lectural ...` run reached download/extraction but failed OCR and exited 2 because:
1. `[run]` pins `paddleocr>=2.7.0` unbounded → uvx resolved **PaddleOCR 3.x**, whose API broke the product's 2.x call in `lectural/ocr.py::_ocr_paddle` (`Unknown argument: show_log`).
2. `[run]` contains **no `paddlepaddle`** (PaddleOCR's engine) and no OCR fallback binary, so even pinned PaddleOCR 2.x would lack its backend.

The deterministic pipeline + completeness gate are correct (proven exit 0 in `docs/perf_smoke_2026-06-13.md` with `paddleocr==2.7.3 paddlepaddle==2.6.2 numpy==1.26.4`). The gap is purely packaging: `[run]` does not yield a working OCR engine.

Resolution requires a packaging decision (outside the originally approved frozen scope):
- Pin `paddleocr>=2.7,<3`, add `paddlepaddle>=2.6,<3`, constrain `numpy<2` (ABI), keep `opencv-python<=4.6.0.66` in `[run]`; or
- Document Tesseract as the supported `[run]` OCR engine (`pytesseract` + Tesseract-on-PATH); or
- Keep OCR engine as an explicit separate install step (host-agent/preflight) and scope AC-F's uvx e2e to the non-OCR pipeline.
