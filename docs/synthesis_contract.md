# Synthesis Contract (`synthesis_input.json` + `summary.md`/`outline.md` pair)

`schema_version` is `1` (`lectural.config.SCHEMA_VERSION`). Bump it on any
incompatible change to the shapes below; readers MUST check it.

## `synthesis_input.json`

The deterministic core writes this compact, **text-only** handoff. It is the
ONLY input a skill-driven host-agent enrichment step reads — no raw images are
ever sent to the model (token minimization). Bare CLI runs stop at deterministic
low-level artifacts and do not call an external LLM.

```jsonc
{
  "schema_version": 1,
  "video":   { "title": str, "url": str, "duration_sec": float,
               "language": str|null, "source": "caption"|"stt" },
  "transcript_segments": [ { "t": float /*sec*/, "text": str } ],
  "slides":  [ { "t": float, "frame": "frames/xxxx.png",
                 "ocr_text": str, "is_slide": true } ],
  "section_hints": [ { "index": int, "t": float, "t_end": float,
                       "title": str, "frame": str|null } ]
}
```

## Markdown outputs (`transcript.md` + `summary.md`/`outline.md` pair)

The deterministic core writes three markdown outputs with separate ownership:

| File | Ownership |
|------|-----------|
| `transcript.md` | verbatim, timestamped transcript; no summarization or enrichment |
| `summary.md` | prose-first deterministic baseline; owns `ENRICH_MARKER`, `COVERAGE_ANCHOR`, deterministic summary prose, and the `TO-ENRICH` host-agent cue |
| `outline.md` | structural navigation/detail file; owns `TOC_ANCHOR`, section anchors/headings, `[HH:MM:SS]` timestamps, slide image links, and transcript bullets |

For skill-driven runs, after the CLI succeeds, the host agent MUST enrich only
the prose in `summary.md`. It MUST preserve `summary.md` anchors
(`ENRICH_MARKER`, `COVERAGE_ANCHOR`, `TO-ENRICH`) and MUST leave `outline.md`
structural anchors and transcript bullets intact. Bare CLI runs do not perform
this enrichment. Do not move the TOC, timestamps, slide links, or transcript
bullets into `summary.md`; those belong to `outline.md`.

## `summary.md` required anchors (validated by the completeness hook)

| Anchor | Constant | Meaning |
|--------|----------|---------|
| `<!-- lectural:baseline -->` | `ENRICH_MARKER` | first line; marks a LecturAL summary |
| `## 커버리지 요약` | `COVERAGE_ANCHOR` | coverage header (gap / scene / OCR engine / artifact status) |
| `## TO-ENRICH` + `TO-ENRICH:` | — | host-agent cue for mandatory skill-driven prose enrichment |

The hook checks `summary.md` for `ENRICH_MARKER` and `COVERAGE_ANCHOR`. The
`TO-ENRICH` cue is part of the summary contract: skill-driven enrichment may
rewrite prose but must not remove the cue or the required summary anchors.

## `outline.md` required structure (validated by the completeness hook)

| Anchor/shape | Constant | Meaning |
|--------------|----------|---------|
| `## 목차` | `TOC_ANCHOR` | table of contents with `(#sec-N)` links |
| `<a id="sec-N"></a>` + `## 섹션 N. [HH:MM:SS] ...` | `SECTION_PREFIX` | per-section structural anchor and timestamped heading |
| `![...](frames/...)` | — | slide image link (present when slide frames exist) |
| `- [HH:MM:SS] transcript text` | — | transcript bullet assigned to a section |

The hook checks `outline.md` for `TOC_ANCHOR`, `[HH:MM:SS]` timestamps,
transcript bullets, and — when `frames/` images exist for the run — at least one
`frames/` image link.

## `coverage.json`

See `lectural.coverage.build_coverage`. Top-level `overall_pass` is the AND of
`gap_check.pass`, `scene_coverage.pass`, and `artifacts.pass`.
