# Synthesis Contract (synthesis_input.json + notes.md)

`schema_version` is `2` (`lectural.config.SCHEMA_VERSION`). Bump it on any incompatible change to the shapes below; readers MUST check it.

## `synthesis_input.json`

The deterministic core writes this compact, **text-only** handoff. It is the primary input a command-driven host-agent enrichment step reads to enrich `notes.md`; raw frame images remain separate under `frames/` and may be opened on disk when OCR text is garbled. Bare CLI runs stop at deterministic low-level artifacts and do not call an external LLM.

```jsonc
{
  "schema_version": 2,
  "video":   { "title": str, "duration_sec": float,
               "language": str|null, "speech_source": "caption"|"stt",
               "input_source": { "kind": "youtube"|"local_video"|"local_audio",
                                 "argument": str /* safe label, not a runtime path */, "has_video": bool,
                                 "citation": { "kind": "youtube", "video_id": str }
                                              | { "kind": "transcript" } } },
  "transcript_segments": [ { "t": float /*sec*/, "text": str } ],
  "slides":  [ { "t": float, "frame": "frames/xxxx.png",
                 "ocr_text": str, "is_slide": true } ],
  "section_hints": [ { "index": int, "t": float, "t_end": float,
                       "title": str, "frame": str|null } ]
}
```

## Markdown outputs (`transcript.md` + `notes.md`)

The deterministic core writes two markdown outputs with separate ownership:

| File | Ownership |
|------|-----------|
| `transcript.md` | verbatim, timestamped transcript with per-cue `<a id="tHHMMSS[-n]">` anchors; no summarization or enrichment |
| `notes.md` | deterministic 7-section study-note skeleton; owns `NOTES_ENRICH_MARKER`, the seven section anchors, `<!-- 미보강 -->` placeholders, citation deeplinks, and the coverage footer |

For `/lectural:notes` runs, after the CLI succeeds, the host agent MUST enrich only the prose in `notes.md` sections marked by `<!-- 미보강 -->`. It MUST preserve `NOTES_ENRICH_MARKER`, the seven anchors, citation deeplinks, transcript anchors, and the `정리 커버리지` footer. Bare CLI runs do not perform this enrichment.

## `notes.md` required structure (validated by the completeness hook)

| Anchor/shape | Constant | Meaning |
|--------------|----------|---------|
| `<!-- lectural:notes -->` | `NOTES_ENRICH_MARKER` | first line; marks a LecturAL notes file |
| `## 3줄 요약` | `NOTES_TAKEAWAY_ANCHOR` | takeaway section |
| `## 목차` | `NOTES_TOC_ANCHOR` | table of contents section |
| `## 흐름` | `NOTES_FLOW_ANCHOR` | flow prose section |
| `## 핵심 개념·이론` | `NOTES_CONCEPTS_ANCHOR` | concept and theory section |
| `## 정리 노트` | `NOTES_DETAIL_ANCHOR` | per-slide image and condensed details |
| `## 복습 질문` | `NOTES_QUESTIONS_ANCHOR` | review-question section |
| `## 정리 커버리지` | `NOTES_COVERAGE_ANCHOR` | coverage footer section |
| `<!-- 미보강 -->` | `NOTES_UNENRICHED_MARKER` | deterministic placeholder marker for host-agent prose enrichment |
| `![...](frames/...)` | — | slide image link (present when slide frames exist) |
| `transcript.md#t<id>` + `youtu.be/<VID>?t=<sec>` | — | YouTube: `youtu.be` seconds. Local: exact relative `transcript.md#tHHMMSS[-n]` only |

The hook checks `notes.md` for `NOTES_ENRICH_MARKER` on line 1, all seven section anchors, and — when `frames/` images exist for the run — at least one `frames/` slide image link.

### Artifact-directory collision policy

The CLI initially uses `out_root/<slug>` for a source. If that path already exists, or was reserved earlier in the same sequential batch, it uses the next available suffix: `<slug>-2`, `<slug>-3`, and so on. The returned result and its run-state entry record the selected directory and artifact paths.

## `coverage.json`

See `lectural.coverage.build_coverage`. Top-level `overall_pass` is the AND of `gap_check.pass`, `scene_coverage.pass`, `artifacts.pass`, and the checked notes contract. For video sources, `scene_coverage.timeline_pass` fails closed when `duration_sec` is missing, zero, negative, or non-finite. Audio-only sources set `visual_required=false`, so the visual timeline remains not-applicable and passes independently of duration.
