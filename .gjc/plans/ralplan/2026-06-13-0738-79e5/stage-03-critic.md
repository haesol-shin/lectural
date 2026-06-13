**[ITERATE]**

**Justification**: Planner의 Option A backbone은 방향이 맞다. raw transcript, OCR, dedup, coverage를 결정론적 Python core로 만들고 host agent는 요약에만 쓰는 구조는 token-zero와 CPU-first 원칙에 대체로 맞다. 그러나 실행자는 현재 계획만으로 AC-8, AC-9, AC-11, AC-13을 안정적으로 만족시킬 수 없다. Architect의 HIGH 4건은 모두 실제 execution blocker 수준의 계획 결함이며, 특히 host only summary와 약한 hook gate는 완전성 보증이라는 핵심 제품 가치를 깨뜨린다. Verdict는 fundamental rejection이 아니라 fixable iteration이다.

**Summary**:
- Clarity: 모듈 경계와 phase 흐름은 명확하지만 coverage semantics, hook run context, summary producer 책임이 불명확하다.
- Verifiability: 테스트 파일명은 있으나 AC-1..AC-13 전부에 대해 곧바로 실행 가능한 command, fixture, URL, expected assertion이 부족하다.
- Completeness: AC-8 summary structure와 AC-11 standalone summary 생성이 빠져 있다. AC-13 gate가 AC-8을 강제하지 않는다.
- Big Picture: deterministic core plus thin skill은 맞다. 하지만 confidence guarantee는 coverage plus hook에 걸려 있으므로 gate semantics를 먼저 고쳐야 한다.
- Principle/Option Consistency: token-zero, deterministic raw, CPU-only 원칙과 Option A는 대체로 일치한다. 단 host only summary는 AC-11 standalone과 AC-13 enforceability에 불일치한다. Tesseract silent fallback은 Korean OCR confidence를 약화한다.
- Alternatives Depth: Option B local LLM과 Option C multimodal ingest는 defer, token explosion, nondeterminism 때문에 공정하게 무효화되었다. Architect의 Option A-prime은 충분히 고려되지 않았고 채택해야 한다.
- Risk/Verification Rigor: yt-dlp와 CPU STT mitigations는 대체로 구체적이다. PaddleOCR weight, Korean OCR accuracy, frame dedup tuning은 degraded mode visibility와 regression details가 부족하다.

## 1. Principle option consistency
- P1 token-zero and deterministic raw: PASS for acquisition, STT, OCR, dedup, coverage. ISSUE for summary because host only `summary.md` is not deterministic and not produced headless.
- P2 pipeline and skill separation: PASS structurally via `lectural/` plus `scripts/`. ISSUE because standalone CLI cannot satisfy AC-7 and AC-11 unless it also produces a valid baseline `summary.md`.
- P3 CPU-only: PASS for faster-whisper medium int8 CPU and external binary preflight. ISSUE if OCR fallback silently drops from PaddleOCR Korean to weaker Tesseract with no coverage signal.
- P4 automated completeness gate: NOT READY. Gate checks do not match AC-9 and do not enforce AC-8.
- P5 caption-first and compressed input: PASS. This is consistent with token minimization.

## 2. Fair alternatives
- Option B is fairly invalidated for v1 because local LLM is explicitly deferred and CPU local inference adds install weight and latency.
- Option C is fairly invalidated because multimodal video ingest violates token minimization and deterministic completeness.
- Option A-prime is the real missing alternative. It preserves all reasons for Option A but adds deterministic extractive baseline `summary.md` with TOC, coverage header, timestamp links, and slide links. Host enrichment becomes optional. This must replace pure Option A before execution.

## 3. Risk mitigation clarity
- yt-dlp breakage: ADEQUATE. Version pin, transcript-api fallback, clear errors, troubleshooting docs are concrete enough. Add one smoke command in verification.
- CPU STT latency: MOSTLY ADEQUATE. medium int8, duration warning, `--model` override, progress logs are actionable. Add exact warning threshold and a short forced-STT smoke.
- PaddleOCR weight: INSUFFICIENT. Optional fallback is not enough for a Korean lecture product. Add preflight, documented install, explicit degraded fallback warning, and `ocr_engine` in coverage.
- Korean OCR accuracy: INSUFFICIENT. PP-OCRv5 ko first is good, but optional host vision is not a deterministic mitigation. Add Korean slide fixture, confidence or nonempty text assertions, and coverage recording of engine and degraded state.
- frame-dedup tuning: PARTIAL. Config constants and `test_dedup.py` are good, but thresholds and expected fixture behavior are absent. Add over/under dedup fixtures and post-OCR re-split for incremental slide text changes.

## 4. AC testability matrix
- AC-1: GAP. E2E caption smoke is named but no exact command, URL, duration cap, or expected output assertions.
- AC-2: GAP. Batch smoke is named but no exact two URLs, command, or expected two folder assertions.
- AC-3: GAP. Caption and no-caption paths are named but no stable fixtures or URLs; no forced-STT switch is planned.
- AC-4: GAP. STT checks mention timestamps but do not assert CPU int8 medium in logs or config.
- AC-5: PARTIAL. `test_dedup.py` exists in plan, but thresholds, synthetic frames, and expected kept frames are unspecified.
- AC-6: GAP. OCR fixture is mentioned but Korean and English fixtures, engine preflight, and expected OCR assertions are unspecified.
- AC-7: GAP. `transcript.md` is deterministic, but `summary.md` is host only and not runnable headless.
- AC-8: FAIL. There is no runnable test or gate for TOC, coverage summary, timestamp links, and slide links.
- AC-9: FAIL. Current wall-clock ratio can reject valid silent spans. Needs VAD or silence-masked speech coverage tests.
- AC-10: GAP. SKILL.md path is planned but no concrete validation of frontmatter, references, and runner command.
- AC-11: FAIL. CLI standalone cannot produce complete outputs unless deterministic baseline summary is added.
- AC-12: GAP. Output structure is specified but no exact E2E assertions for `transcript.md`, `summary.md`, `frames/`, `coverage.json`.
- AC-13: FAIL. Hook unit tests are planned, but context resolution, no-op scoping, batch handling, and AC-8 validation are missing.

## 5. Concrete verification steps assessment
Smoke tests are not specified well enough. The plan says short public lecture, no-caption video, and batch two videos, but gives no URLs, no commands, no maximum duration, no expected artifacts, no skip or replacement policy when YouTube changes, and no way to force STT if captions unexpectedly appear. Unit tests are also too high level: they name `test_dedup.py`, `test_coverage.py`, and `test_synthesis_input.py`, but do not define fixtures and assertions. Executors would have to guess.

Minimum needed: a verification matrix with exact commands, pinned URLs or local fixture videos, expected output paths, expected coverage fields, expected hook exit codes, and exact AC mapping. For network smoke tests, include stable duration constraints and a documented replacement rule.

## 6. Architect HIGH adjudication
1. HIGH-1 coverage metric conflates silence with missed speech: MUST fix before execution. Minimum change: define coverage over VAD-detected speech regions or explicit silence mask, remove wall-clock `transcript_covered_ratio >= 0.98` or redefine it as speech-region coverage, and add tests where silent intro and outro pass while a non-silence 61s speech gap fails. Tied to AC-9 and AC-13.
2. HIGH-2 gate does not enforce AC-8 structure: MUST fix before execution. Minimum change: hook validates `summary.md` for TOC marker, coverage summary, timestamp links, and frame links, with passing and failing fixtures. Best paired with deterministic baseline summary. Tied to AC-8 and AC-13.
3. HIGH-3 hook run context and scoping unspecified: MUST fix before execution. Minimum change: CLI writes an active run pointer such as `output/.lectural_active_run.json` containing output dirs and batch members; hook no-ops when no active LecturAL marker exists; hook has explicit event and matcher. Tied to AC-13.
4. HIGH-4 host-agent summary unverifiable headless vs AC-11: MUST fix before execution. Minimum change: adopt Option A-prime so `synthesis.py` always emits a structurally valid baseline `summary.md`; host agent enrichment is optional and must preserve required anchors. Tied to AC-7, AC-8, AC-11, AC-13.

## 7. Representative implementation simulation
- Simulating coverage.py for a 50 minute lecture with 3 minutes of silence: current `transcript_covered_ratio >= 0.98` would fail around 0.94 even if every spoken word is covered. This contradicts AC-9.
- Simulating headless `python -m lectural.cli <url>`: acquisition, speech, visual, OCR, transcript, coverage can complete, but no host agent writes `summary.md`. AC-7, AC-8, AC-11, and AC-13 cannot pass.
- Simulating Stop hook after unrelated work: plan only says identify cwd and load `output/<slug>/coverage.json`. With no slug or active marker, hook either blocks unrelated stops or cannot locate the current batch output.

## Required plan revisions
1. Replace pure Option A with Option A-prime: deterministic baseline `summary.md` from `synthesis.py`, host enrichment optional, required anchors preserved. Covers AC-7, AC-8, AC-11, AC-13 and Architect HIGH-4.
2. Rewrite coverage semantics for speech gaps: use VAD or silence mask, gate on max non-silence untranscribed gap <= 60s, remove or redefine wall-clock 0.98 ratio, add silent-span pass and speech-gap fail fixtures. Covers AC-9, AC-13 and HIGH-1.
3. Make the hook executable without guessing: define active run pointer or output-dir env written by CLI, batch semantics, no-op behavior outside LecturAL runs, exact Stop or PostToolUse matcher, and AC-8 summary structure validation. Covers AC-8, AC-13 and HIGH-2/HIGH-3.
4. Add a full AC-1..AC-13 verification matrix with exact commands, exact URLs or local fixtures, expected output paths, expected coverage fields, and expected hook exit codes. Include a forced-STT path or local no-caption fixture. Covers every AC.
5. Strengthen OCR and visual risks: PaddleOCR preflight, explicit degraded Tesseract fallback warning, `ocr_engine` in `coverage.json`, Korean and English OCR fixtures, concrete dedup thresholds, over/under dedup tests, and post-OCR re-split for incremental slides. Covers AC-5, AC-6, AC-13.
6. Update alternatives and principles section to explain why A-prime preserves token-zero, deterministic raw, and CPU-only while fixing standalone verification. Covers principle-option consistency.

Verdict: ITERATE.
