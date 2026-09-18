# Plan: Establish reproducible evidence quality and resource benchmarks

## Inputs
- Issue: #21 (haesol-shin/lectural)
- Specification: none (issue is the contract)
- Research:
  - Reviewer pass (agent `RegisteredDormouse`, `reviewer` role) on the first draft — required independent review of rendered fixtures (not just scripts), a caption-path fixture reachable through `acquisition.py`, accurate metric-to-API mapping, an explicit resource protocol, and `jiwer` as a benchmark-only dependency.
  - Web research on lecture-video benchmark practice: LPM (Lecture Presentations Multimodal, ICCV 2023) as an observational reference dataset; Augraphy for synthetic OCR degradation (ink/paper/post-processing phases); audiomentations/pyroomacoustics for synthetic ASR degradation (noise, RIR); jiwer + whisper-normalizer as the standard WER/CER stack.
  - `pi-server` (Debian 13 trixie, aarch64, 4 cores) verified reachable via `ssh pi-server`; `lectural doctor --fix` then `uv pip install -e ".[run]"` produced a clean `lectural doctor` → `ready (exit 0)`, including a working `paddleocr`/`paddlepaddle==2.6.2` import and engine init (model download succeeded). ARM64 is not a blocker for the current stack. The pi-server checkout is stale (`feat/local-source`, pre-#19) and must be synced to `main` before use.
  - CI (`ci.yml`) already runs the offline suite on `windows-latest`/`ubuntu-latest`/`macos-latest` (x86_64 only); no ARM64 job exists today.

## Decision drivers
1. Issue #21 requires "independently reviewed" ground truth, not merely internally generated ground truth — a script authored before synthesis is necessary but not sufficient.
2. Local synthetic fixtures cannot reach the caption/caption-fallback code path: `acquisition.py` only fetches YouTube captions; local sources always STT.
3. Production dedupe/coverage/speech internals must not be modified or instrumented in ways that could change Issue #19 extraction-status semantics.
4. CPU-only, no-GPU, no-mandatory-720p constraints from the prior quality track and this issue's non-goals apply directly to fixture and profile design.
5. Real-time factor (RTF) and per-stage CPU attribution matter to end users (processing time competitive with video length) even though issue #21 itself does not set a product default.

## Options considered

### Option A — Purely synthetic fixtures (script = ground truth, no degradation)
Fast to build, fully deterministic, but tautological: WER/CER score the TTS/render pipeline, not real-world failure modes (occlusion, glare, 360p compression, disfluency). Rejected per reviewer finding P0-1.

### Option B — Real recorded lecture clips only
Matches real failure modes but is not redistributable/deterministic, and manual re-review is required whenever a fixture is replaced. Conflicts with the issue's "deterministic, redistributable fixtures for offline regression" requirement.

### Option C — Synthetic core + injected degradation + one independent human review pass, real dataset as observational reference (chosen)
TTS + PIL-rendered fixtures stay deterministic and redistributable. Augraphy (visual) and audiomentations (audio) inject controlled, real-failure-mode degradation. One independent human review of the rendered media (not just the script) against the script is performed once per fixture set and recorded in the benchmark definition. LPM / the existing 555-second YouTube run remain observational-only, never ground truth. This satisfies "independently reviewed" without sacrificing redistributability.

## Chosen approach
Option C. Concretely:

- **Fixture generation** (`tests/fixtures/benchmark/generate.py` + committed locked-seed generator config + committed output media, EN/KO/mixed):
  - Script (ground truth) authored first; TTS renders audio; PIL renders slide frames from the same script's key terms/numbers.
  - Augraphy degrades slide frames (blur, shadow, perspective, compression-equivalent) at at least two severity levels and includes deliberate near-duplicate/persistence frames (small crops/re-encodes of the same slide) so `visual.dedupe_frames`'s duplicate-rate metric has real positives to score; audiomentations/ffmpeg inject background noise, silence gaps, and a 360p re-encode variant.
  - Committing the rendered media (not only the generator/seed) is required, not optional, so the fixture set stays redistributable and reviewable as a fixed artifact; regeneration from the locked seed is a determinism check, not the distribution mechanism.
  - Caption/fallback path fixture: a VTT/json3 file plus a deliberately sparse/malformed variant, each with a GT JSON. `parse_vtt`/`captions_are_usable` are scored as pure parser/heuristic units directly against these files. Reaching `acquisition.acquire_speech`'s actual caption/fallback branches requires a `SourceKind.YOUTUBE`-shaped fixture source with `acquisition.fetch_caption_segments` monkeypatched to return the fixture's parsed Segments (or raise, for the fetch-failure branch) and `media.resolve_audio` monkeypatched to the fixture's local audio — the same dependency-injection pattern `tests/test_extraction_contract.py` already uses, not a new production hook. This exercises usable-caption, unusable-caption-fallback, fetch-failure-fallback, and `force_stt`-fallback without any change to `lectural/acquisition.py`. Live YouTube caption fetch, including the 555-second case, stays `observational: true` only.
  - GT speech spans (for VAD recall) and GT slide-change timestamps (for frame recall) are recorded from the script/render step, independent of any `vad.py`/`visual.py` output.
  - One independent review pass (human, or a separate fresh-context reviewer subagent standing in during automation) compares rendered audio/video against the script once; the review outcome is recorded in `docs/benchmark_definition.md`.
  - Current extraction output, current VAD output, and current LLM summaries are never used as ground truth (non-goal compliance).

- **Metrics** (`lectural_bench/metrics.py`, new benchmark-only module, not imported by `lectural/`):
  - WER/CER via `jiwer`, normalization via `whisper-normalizer` (EN) and a documented space-insensitive Hangul syllable CER rule (KO), matching reviewer P2.
  - Terminology recall: fixed technical-term list per fixture, checked post-normalization.
  - Timestamp accuracy: cue-start median/P95 against GT cue timestamps (word-level P95 is out of reach because `speech.py` sets `word_timestamps=False`; this limitation is stated explicitly rather than silently narrowed).
  - Voiced-speech recall / max untranscribed gap: reuse `lectural.vad.detect_speech_spans` and `max_non_silence_untranscribed_gap`, scored against fixture-authored GT speech spans (never against the same VAD run's own mask).
  - Frame recall / duplicate rate: score `visual.extract_candidate_frames` + `visual.dedupe_frames` **output** against GT slide-change timestamps; production dedupe logic itself is not modified or reimplemented.
  - OCR CER / key-field recall / usable precision-recall: run `ocr.ocr_frames` against Augraphy-degraded frames; key-field list and "usable" threshold defined per fixture in its GT JSON; exact + Levenshtein-ratio fuzzy match, per the reviewed KFR methodology.

- **Resource harness** (`scripts/benchmark.py`, new script, local-fixture entry point — distinct from `scripts/perf_smoke.py`'s YouTube-only `run()`):
  - Reuses `StageSampler` (CPU%/RSS/process-tree sampling) from `perf_smoke.py` without modifying it.
  - Adds: temp vs. final storage delta, explicit cold run (first model load / no cache) vs. warm run (cached models) protocol for faster-whisper and PaddleOCR, `n=3` repetitions with median and variance, machine spec + dependency versions per run (existing `_machine_spec`/`_dep_versions` pattern).
  - Adds RTF (`wall_time / fixture_duration_sec`) per run and per stage.
  - Execution matrix: `{caption (mocked fetch), caption-fallback (unusable/fetch-failure), forced-STT} × {OCR-on, OCR-off(--skip-ocr)} × {EN, KO, mixed} × {cold, warm} × 3 reps`. Frame selection (`extract_candidate_frames` + `dedupe_frames`) always runs when the fixture has video, independent of the OCR axis — it is not a separate matrix value. The live 555-second YouTube case is included as one additional `observational: true` row (not repeated 3x, not cold/warm-controlled) alongside a resolution factorial (360p vs 720p source) and an STT model-size factorial (`small` vs `medium`) on one local fixture, isolating what is measurable without changing `lectural/`.
  - `--skip-ocr` on/off pair is reported side by side (CPU/time/RTF delta and completeness-coverage delta) to give #22 a resource baseline for OCR-off tradeoffs.
  - Runs on x86_64 dev/CI hosts and, opt-in, on `pi-server` (ARM64) via `ssh pi-server`, after syncing that checkout to `main` and re-running `lectural doctor`. Platform is recorded in every report; no default profile is set from this issue.

- **Report and contract**:
  - `docs/contracts/benchmark.schema.json` — versioned JSON schema for a benchmark report (fixture id, path exercised, language, profile/platform, quality metrics, resource metrics incl. RTF and storage, cold/warm, run count, environment).
  - `docs/benchmark_definition.md` — fixture list, degradation levels, GT schema, normalization rules, metric definitions, supported profiles (x86_64, ARM64/pi-server), measurement procedure, the recorded independent-review note.
  - `docs/reports/benchmark_<date>.md` + `.json` — actual run output; the current 555-second YouTube result and any LPM-derived observation are included only under an explicit `observational: true` field, never merged into the quality-gate GT set.
  - `tests/test_benchmark_contract.py` — offline: report schema validation, fixture GT determinism (regenerating a fixture's GT from its script is stable), and that `scripts/benchmark.py --help`/dry-run does not import `jiwer`/`augraphy`/heavy deps at CLI-parse time. Does not run the real heavy benchmark (opt-in only).

  Every report records the exact command line, fixture identifiers, and machine environment used to produce each row, plus the raw per-run measurements underlying the reported median/variance — required by the issue's acceptance criteria, not only the aggregated numbers.

## Contract and dependency impact
- No change to `lectural/` public CLI, `evidence.json` schema, or completeness-gate (pass/warn/fail) semantics from Issue #19. Benchmark instrumentation reads existing module outputs; it does not alter `coverage.py`, `evidence.py`, `vad.py`, `visual.py`, `ocr.py`, or `speech.py`.
- New `pyproject.toml` extra, e.g. `[project.optional-dependencies.bench]` = `jiwer`, `whisper-normalizer`, `augraphy`, `audiomentations` (or `Levenshtein` alone if `audiomentations`'s dependency footprint proves too heavy for aarch64 — verified during implementation). Never added to `[run]`; offline CI does not install it. This follows the existing pinned-heavy-dependency precedent in `CONTRIBUTING.md` without touching those caps.
- `docs/benchmark_definition.md` is a new versioned artifact (starts at `v1`); later revisions bump the version field, not silently rewrite history.

## Execution slices
1. Scaffolding: `.ops/plans/21-evidence-benchmark.md` (this file), branch `feat/21-evidence-benchmark`, directory layout (`tests/fixtures/benchmark/`, `docs/reports/`, `docs/contracts/benchmark.schema.json` stub).
2. Fixture generation module + EN/KO/mixed fixture sets: script, TTS audio, PIL slides, Augraphy/audiomentations degraded + near-duplicate variants, VTT usable/sparse/malformed caption files, GT JSON (speech spans, slide-change timestamps, key fields), one independent-review note. All rendered media committed at a locked seed.
3. `lectural_bench/metrics.py` (WER/CER/terminology/timestamp/VAD-recall/frame-recall/OCR metrics), unit-tested against hand-computed small examples.
4. `scripts/benchmark.py` harness: the caption/fallback monkeypatch mechanism (`fetch_caption_segments` + `media.resolve_audio` injection) exercising usable/unusable/fetch-failure/force-stt branches, the OCR-on/off × language × cold/warm × 3-rep matrix with frame selection always on, the resolution and STT-model-size factorials, RTF, and storage.
5. `docs/contracts/benchmark.schema.json`, `docs/benchmark_definition.md`, report writer producing `docs/reports/benchmark_<date>.{md,json}` covering EN/KO/mixed plus the one `observational: true` live-YouTube 555-second row, with exact commands/fixture ids/environment/raw measurements per row.
6. `tests/test_benchmark_contract.py` (offline schema/determinism/no-heavy-import-at-parse-time checks).
7. `pyproject.toml` `bench` extra; `CONTRIBUTING.md` note on when/how to run the benchmark; `CHANGELOG.md` entry.
8. Sync `pi-server` checkout to `main`, re-run `lectural doctor`, execute the opt-in ARM64 profile once, record its result in the first `docs/reports/benchmark_<date>.md`.

## Verification
- `uv run --with pytest --with numpy pytest -q` stays green (existing Issue #19 suite untouched; new `test_benchmark_contract.py` added and green).
- `lectural doctor` remains `ready` on the dev host after adding the `bench` extra (extra is optional, not installed by default doctor checks).
- A real (opt-in) run of `scripts/benchmark.py` covering EN, KO, and mixed local fixture sets plus the one observational live-YouTube 555-second row, on both an x86_64 host and `pi-server`, producing a schema-valid report with cold/warm/3-rep data, the `--skip-ocr` comparison, and exact commands/fixture ids/environment/raw measurements recorded under `docs/reports/`.
- `claude plugin validate .` unaffected (no plugin manifest changes).

## Rollout
No production/runtime rollout — this is dev/maintainer tooling. Merges to `main` behind the normal PR gate; `scripts/benchmark.py` and the `bench` extra are inert for ordinary `/lectural:notes` users.

## Rollback or mitigation
Revert the PR; no schema or CLI surface used by consumers changes. If `pi-server`'s ARM64 profile proves unreliable (e.g., flaky heavy-dependency install), drop it to a documented "unverified platform" note rather than blocking the rest of the benchmark.

## Open decisions
- Exact Korean CER normalization rule (space-insensitive syllable-level) — finalize during metrics implementation with a worked example in `docs/benchmark_definition.md`.
- Whether `audiomentations` installs cleanly on `pi-server` aarch64 (unverified); fallback is `ffmpeg`-based noise/gap injection only, dropping the RIR-based augmentation.

## Pre-mortem
Not required (risk:medium, not risk:high per issue label); the main credible failure mode — fixtures that look rigorous but are actually tautological — is the reviewer's P0 finding and is addressed structurally in "Chosen approach" (independent review + injected degradation + non-GT-from-own-output rule).
