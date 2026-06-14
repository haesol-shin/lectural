# WU-6 verification — 2026-06-14

Evidence artifacts:

- `artifacts/wu6-rubric.json`
- `artifacts/wu6-real-video-evidence.json`
- `artifacts/wu6-focused-tests.txt`

Source video: `https://www.youtube.com/watch?v=19vYXnpDIyg`  
Output folder: `output/wu6-real/96강-강박장애-손에-피가날-정도로-씻어도-불안한-이유/` (`folder=title` slug: true)

Heavy generated outputs remain under `output/` (`video.mkv`, `frames/*.png`, transcript/notes/coverage intermediates) and are not committed.

## Commands and results

| Purpose | Command | Result |
|---|---|---|
| Existing real-video run | `lectural https://www.youtube.com/watch?v=19vYXnpDIyg --out ./output/wu6-real` | exit 0 observed by leader; `.lectural_runstate.json` status `complete`; `coverage.json overall_pass=true` |
| Pre-enrichment Stop hook | `uv run python scripts/completeness_hook.py` | exit 2 observed by leader because `notes.md` still contained `<!-- 미보강 -->` |
| Post-enrichment Stop hook | `uv run python scripts/completeness_hook.py` | exit 0; `LecturAL 완전성 게이트 통과: 1개 run 모두 완전.` |
| Focused WU-6 rubric | `uv run python -c "$WU6_RUBRIC_CODE"` | exit 0; `artifacts/wu6-rubric.json` top-level `pass=true` |
| Focused offline WU tests | `PYTHONUTF8=1 PYTHONIOENCODING=utf-8 uv run --with pytest --with numpy --with psutil pytest -q tests/test_notes.py tests/test_cli.py tests/test_coverage.py tests/test_hook.py tests/test_redteam_notes.py tests/test_redteam_notes_contract.py tests/test_doctor.py tests/test_deps.py tests/test_redteam_packaging.py tests/test_redteam_cli_hook.py tests/test_redteam_readme.py tests/test_redteam_synthesis.py` | exit 0; `175 passed in 5.59s`; evidence in `artifacts/wu6-focused-tests.txt` |

## AC-19 — executor rubric over generated notes.md

Passed. `artifacts/wu6-rubric.json` records `pass=true` and individual checks for:

- seven-section `notes.md` structure;
- exactly 4 TOC entries and exactly 4 `## 상세 노트` slide sections;
- exactly 4 slide image links;
- 127/127 concept/detail/question bullets carrying valid `transcript.md#t...` anchors and `https://youtu.be/19vYXnpDIyg?t=...` deeplinks with seconds matching the transcript anchor within ±1s;
- 131/131 total citations resolving to transcript anchors with matching YouTube seconds;
- no `<!-- 미보강 -->`, `TODO`, `TBD`, `PLACEHOLDER`, or similar residue;
- no exact transcript prose-line copy in enriched prose sections;
- `coverage.json overall_pass=true` and `scene_coverage.slide_frames_total=4`.
- focused offline tests across WUs: `175 passed in 5.59s` with `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`; evidence in `artifacts/wu6-focused-tests.txt`.

## AC-20 — real-video before/after evidence

Passed. `artifacts/wu6-real-video-evidence.json` records the before/after hook and real-video output facts.

| Check | Evidence |
|---|---|
| Target URL | `https://www.youtube.com/watch?v=19vYXnpDIyg` |
| Folder=title slug | `96강-강박장애-손에-피가날-정도로-씻어도-불안한-이유` |
| 4 TOC/detail sections | rubric check `exactly_4_toc_entries_and_detail_sections=true` |
| 4 slide frames | coverage `scene_coverage.slide_frames_total=4`; rubric `exactly_4_slide_image_links=true` |
| Citation/deeplinks | rubric citation check passed for 127 required bullets, with no missing/invalid links |
| Before enrichment | Stop hook exit 2, marker `<!-- 미보강 -->` present |
| After enrichment | marker absent; Stop hook exit 0; rubric pass |

Utterance-proportional detail rows:

| Section | Transcript utterances | Detail bullets | Ratio |
|---|---:|---:|---:|
| sec-1 | 2 | 2 | 1.0 |
| sec-2 | 62 | 62 | 1.0 |
| sec-3 | 28 | 28 | 1.0 |
| sec-4 | 25 | 25 | 1.0 |

## AC-21 — completed enrichment gates

Passed. The existing real-video CLI run exited 0, `coverage.json` reports `overall_pass=true`, and the post-enrichment Stop hook exits 0. The focused rubric command also exits 0 and wrote `artifacts/wu6-rubric.json` with top-level `pass=true`.
