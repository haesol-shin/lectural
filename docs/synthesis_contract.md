# Synthesis Contract (synthesis_input.json + notes.md)

`schema_version` is `2` (`lectural.config.SCHEMA_VERSION`). Readers MUST check
it and reject incompatible versions.

## Accepted sources

The CLI accepts YouTube URLs/IDs and existing local `.mp4`, `.webm`, `.mkv`, or
`.wav` files. Local media is read in place and uses STT; it is never copied,
renamed, deleted, modified, captioned, or resolved through yt-dlp. Video sources
retain deduplicated scene frames independently of `--keep-frames`.

## `synthesis_input.json`

The deterministic core writes this compact, **text-only** handoff. It is the
primary input a command-driven host-agent enrichment step reads to enrich
`notes.md`; raw frame images remain separate under `frames/` and may be opened
on disk when OCR text is garbled. Bare CLI runs stop at deterministic low-level
artifacts and do not call an external LLM.

```jsonc
{
  "schema_version": 2,
  "video": {
    "title": str,
    "duration_sec": float,
    "language": str|null,
    "speech_source": "caption"|"stt",
    "input_source": {
      "kind": "youtube"|"local_video"|"local_audio",
      "argument": str,
      "has_video": bool,
      "citation": { "kind": "youtube", "video_id": str }|{ "kind": "transcript" }
    }
  },
  "transcript_segments": [ { "t": float /*sec*/, "text": str } ],
  "slides": [ { "t": float, "frame": "frames/xxxx.png",
                 "ocr_text": str, "is_slide": true } ],
  "section_hints": [ { "index": int, "t": float, "t_end": float,
                       "title": str, "frame": str|null } ]
}
```

`video.input_source` is the serialized source descriptor. Runtime-only
normalized local paths are deliberately not citation targets.

## Markdown outputs (`transcript.md` + `notes.md`)

The deterministic core writes two markdown outputs with separate ownership:

| File | Ownership |
|------|-----------|
| `transcript.md` | Verbatim, timestamped transcript with per-cue `<a id="tHHMMSS[-n]">` anchors; no summarization or enrichment |
| `notes.md` | Deterministic seven-section study-note skeleton; owns `NOTES_ENRICH_MARKER`, section anchors, `<!-- 미보강 -->` placeholders, source-appropriate citation guidance, and the coverage footer |

For `/lectural:notes` runs, after the CLI succeeds, the host agent MUST enrich
only the prose in `notes.md` sections marked by `<!-- 미보강 -->`. It MUST
preserve the marker contract, seven anchors, frame links, citation form selected
by `video.input_source.citation.kind`, transcript anchors, and the `정리 커버리지`
footer. Bare CLI runs do not perform this enrichment.

Citation forms are source-specific:

- YouTube: `([영상 M:SS](https://youtu.be/<VID>?t=<sec>))` with seconds within ±1 second of a real cue.
- Local video/audio: `([전사 M:SS](transcript.md#tHHMMSS[-n]))` with an exact anchor emitted in `transcript.md`; duplicate cues use the suffixed anchor (`-2`, `-3`, ...).

## `notes.md` required structure (validated by the completeness hook)

| Anchor/shape | Constant | Meaning |
|--------------|----------|---------|
| `<!-- lectural:notes -->` | `NOTES_ENRICH_MARKER` | First line; marks a LecturAL notes file |
| `## 3줄 요약` | `NOTES_TAKEAWAY_ANCHOR` | Takeaway section |
| `## 목차` | `NOTES_TOC_ANCHOR` | Table of contents section |
| `## 흐름` | `NOTES_FLOW_ANCHOR` | Flow prose section |
| `## 핵심 개념·이론` | `NOTES_CONCEPTS_ANCHOR` | Concept and theory section |
| `## 정리 노트` | `NOTES_DETAIL_ANCHOR` | Per-slide or whole-source details |
| `## 복습 질문` | `NOTES_QUESTIONS_ANCHOR` | Review-question section |
| `## 정리 커버리지` | `NOTES_COVERAGE_ANCHOR` | Coverage footer section |
| `<!-- 미보강 -->` | `NOTES_UNENRICHED_MARKER` | Deterministic placeholder marker for host-agent prose enrichment |
| `<img src="frames/..." ...>` | — | Retained video slide image (when frames exist) |
| Source-appropriate citation | — | YouTube deeplink or exact `transcript.md#tHHMMSS[-n]` anchor |

The hook checks `notes.md` for the marker on line 1, all seven section anchors,
source-appropriate citations, and — when `frames/` images exist for the run —
at least one `frames/` slide image link. Local audio has an explicit image-exempt
state and one whole-source detail section.

## `coverage.json`

See `lectural.coverage.build_coverage`. Top-level `overall_pass` is the AND of
the speech-gap, scene applicability/timeline and OCR applicability/text
predicates, artifact presence, and the Layer-1 notes structure contract.

`scene_coverage` serializes `visual_required`, `ocr_required`, `timeline_pass`,
and `slide_text_pass`. For `--skip-ocr`, raw and deduplicated frame counts remain
real and timeline coverage remains required, while `ocr_required=false` makes
only the slide-text predicate pass without changing those counts. For local
`.wav`, visual and OCR checks are explicitly not applicable and pass; speech-gap,
artifacts, and notes structure remain mandatory.
