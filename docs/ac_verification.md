# AC-1..AC-18 Verification Matrix

Offline verification uses focused tests; the full offline command is
`uv run --with pytest --with numpy pytest -q`. No offline test accesses
YouTube, invokes ffmpeg/yt-dlp, loads faster-whisper/OCR models, or uses a VLM.

LecturAL accepts YouTube URLs/IDs and existing local `.mp4`, `.webm`, `.mkv`, or
`.wav` files. Mixed positional sources are processed sequentially. Local files
are read in place and use STT; they never use captions or yt-dlp. The serialized
handoff and coverage artifacts use schema version `2`.

| Capability | Requirement | Offline verification |
|---|---|---|
| Source classification | YouTube URL/ID plus existing case-insensitive `.mp4`, `.webm`, `.mkv`, `.wav`; normalized local paths; clear rejects | `tests/test_source.py` |
| Speech acquisition | YouTube captions-first/STT fallback; local video/audio direct STT; selected model and `audio_path` retained | `tests/test_acquisition.py` |
| Media resolution | YouTube commands remain unchanged; local WAV resolves in place; local video uses ffmpeg only for generated `audio.wav`; no local yt-dlp | `tests/test_media.py` |
| CLI | Positional `sources`, mixed sequential batch, `--skip-ocr` default false/true, doctor remains separate, exit 0/2 behavior | `tests/test_cli.py` |
| Video path | Resolved video → candidate frames → deduplicated scene frames → OCR (unless skipped), shared synthesis/coverage path | `tests/test_cli.py`, `tests/test_dedup.py`, `tests/test_ocr.py` |
| Skip OCR | Frames remain linked and on disk; `ocr_engine=skipped`; only slide-text predicate is relaxed; timeline, speech, artifacts, notes, citations and exit behavior remain required | `tests/test_cli.py`, `tests/test_coverage.py` |
| Local audio | Visual/OCR stages are not called; one whole-source detail section; image requirement and scene/OCR checks explicitly not applicable | `tests/test_cli.py`, `tests/test_coverage.py`, `tests/test_notes.py` |
| Synthesis | Schema version 2; `video.speech_source`; source descriptor/citation policy; unchanged seven-section YouTube skeleton; local transcript guidance | `tests/test_notes.py` |
| Coverage | Actual frame/text counts, applicability flags, timeline and slide-text passes, overall formula; audio-only visual/OCR not-applicable state | `tests/test_coverage.py` |
| Notes contract | Layer 1 remains structure-only; Layer 2 validates YouTube links or exact local `transcript.md#tHHMMSS[-n]` anchors and rejects local `youtu.be` | `tests/test_notes_contract.py`, `tests/test_hook.py` |
| Completeness hook | Reads schema-2 `synthesis_input.json` citation policy; fails closed on missing/malformed policy; enforces per-slide images only when frames exist | `tests/test_hook.py` |
| Run state | Fresh session pre-registers `source` entries; failures remain visible and batch continues | `tests/test_cli.py` |

## Notes and citation forms

All runs retain the exact seven sections in this order: `3줄 요약`, `목차`,
`흐름`, `핵심 개념·이론`, `정리 노트`, `복습 질문`, `정리 커버리지`.
YouTube concept/review citations remain
`https://youtu.be/<VID>?t=<sec>` within ±1 second of a transcript cue. Local
concept/review citations must use exact relative `transcript.md#tHHMMSS[-n]`
anchors; duplicate rounded seconds use the emitted suffix (`-2`, etc.), and
any local `youtu.be/` link fails. Local audio has no image requirement.

## Smoke

Live acquisition/STT/visual/OCR smoke runs need the external binaries and
models and are not part of the offline tests:

```bash
lectural "https://www.youtube.com/watch?v=<captioned-lecture>"
lectural "./lecture.mp4" --skip-ocr
lectural "./lecture.wav"
python scripts/completeness_hook.py < /dev/null
```

`--skip-ocr` never calls `ocr_frames`, but video frame extraction and
Deduplication remain required. Local runs do not require yt-dlp; local video
still requires ffmpeg for generated STT audio.
