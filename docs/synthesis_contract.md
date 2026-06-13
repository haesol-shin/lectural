# Synthesis Contract (`synthesis_input.json` + `summary.md` anchors)

`schema_version` is `1` (`lectural.config.SCHEMA_VERSION`). Bump it on any
incompatible change to the shapes below; readers MUST check it.

## `synthesis_input.json`

The deterministic core writes this compact, **text-only** handoff. It is the
ONLY thing an optional host-agent enrichment step reads — no raw images are
ever sent to the model (token minimization).

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

## `summary.md` required anchors (validated by the completeness hook)

The deterministic BASELINE `summary.md` MUST contain these anchors. A host
agent MAY rewrite/expand prose but MUST preserve them, so the hook can verify
structure regardless of who wrote the file:

| Anchor | Constant | Meaning |
|--------|----------|---------|
| `<!-- lectural:baseline -->` | `ENRICH_MARKER` | first line; marks a LecturAL summary |
| `## 커버리지 요약` | `COVERAGE_ANCHOR` | coverage header (gap / scene / OCR engine) |
| `## 목차` | `TOC_ANCHOR` | table of contents with `(#sec-N)` links |
| `## 섹션 N. [HH:MM:SS] ...` | `SECTION_PREFIX` | per-section heading with timestamp |
| `![...](frames/...)` | — | slide image link (present when slides exist) |

The hook checks: ENRICH_MARKER present, COVERAGE_ANCHOR present, TOC_ANCHOR
present, at least one `[HH:MM:SS]` timestamp link, and — when `frames/` images
exist for the run — at least one `frames/` image link.

## `coverage.json`

See `lectural.coverage.build_coverage`. Top-level `overall_pass` is the AND of
`gap_check.pass`, `scene_coverage.pass`, and `artifacts.pass`.
