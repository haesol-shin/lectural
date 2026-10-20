# Plan: URL fetch pre-step (#45)

## Inputs and decision

- Understood as: rebuild public URL input as a disposable local-file preparation step on the source handlers, preserving the accepted behavior and test bank of PR #47 without transplanting its implementation.
- Target: `feat/45-url-prestep`, based on `origin/main` at `3ca5b0b` (PR #48 included). Reference: `feat/45-public-url` at `341280d5a94384db1e74aa6e91325f3e37107f06`, compared with its base `17485de`. Below, **current** and **reference** qualify repository-relative `file:line` citations; reference files need not exist on this branch.
- This deliverable is planning only. No implementation, runtime, test, formatter, push, or GitHub operation is represented as completed.
- Risk: high: downloaded media, signed URLs, redirect boundaries, and interruption cleanup.
- Accepted behavior: reference `.ops/plans/45-public-media-url.md:9-42,50-59`; source-handler direction: current `.ops/plans/source-handlers.md:109-113`. This plan supersedes that direction's provisional module names and specifies the single preparation boundary below.
- Live-run provenance is **owner-held sanitized evidence (2026-10-21)**. The owner retains the executable Instagram input and raw run instructions outside repository artifacts. The public fixture identity is `public-short-video-01`, represented only by `https://media.example.invalid/reel/synthetic-clip?tok=FAKESECRET42`; this is not an executable real-site substitute. Do not commit real page identifiers, local paths, raw logs, media attachments, or private infrastructure details.

## Scope and compatibility

Accept public non-YouTube HTTP(S) media/page URLs for `extract` and source-mode `notes`, without cookies or login. Download into private scratch, then pass an ordinary `InputSource(kind=local_video|local_audio)` to the unchanged handlers. Generic URLs use STT, transcript citations, and SHA-256 identity of the downloaded file (the merged file for split streams). Preserve YouTube/local behavior and contract/schema version 2. No remote source kind or handler is added.

Not included: `--cookies`, cookie discovery, credentials/login flows, site-specific application code, DRM bypass, media retention, segmented HLS/DASH video, speech-only/ranges (#44). Public means unauthenticated access, not an IP-range filter: loopback fixtures remain valid; this is not an SSRF isolation guarantee. Personal study only; no redistribution; users must follow the source's rules.

Current contracts grounding this boundary:

| Evidence | Consequence |
| --- | --- |
| current `lectural/source.py:18-21,56-119` | Keep three kinds and frozen identity/serialization; add only optional safe provenance. |
| current `lectural/sources/base.py:12-29`, `sources/__init__.py:10-21` | No Protocol change, new kind, registry entry, or handler hierarchy. |
| current `lectural/sources/local.py:12-18,21-56` | Local handlers already supply host title hints, SHA-256, STT fallback, and audio/video behavior. |
| current `lectural/media.py:85-89,132-136,161-165` | Keep delegates and patch seams intact; no fetch guard or remote exception here. |
| current `lectural/extract.py:102-116,277-304` | Extraction already accepts a prepared source; only add a working-directory seam. |
| current `lectural/verify.py:117-120,482-501`, `docs/contracts/cli.md:84,116-122` | Preserve public kinds and offline verification; generic URL verification remains invalid, with no fetch. |

## Seven old review concerns: checked against the reference

| Concern | Observed reference evidence | Decision |
| --- | --- | --- |
| 1. Repeated URL rules/masking | `source.py:40,74-145` owns `_REMOTE_SCHEMES` plus five label/origin helpers; `remote.py:64-65,142-160,199-201,368-375` repeats HTTP(S) checks; `evidence.py:186-202` independently recognizes origins. | One pure `urlpolicy.py` owns scheme/host parsing, accepted protocols, origin reduction and input labels. Other modules call/import it; no second regex in evidence. |
| 2. Two fetch starts | `cli.py:341-364` and `extract.py:317-333` both enter `remote.materialize`. | Only `fetch.prepare_source` starts fetching; CLI command adapters use it, extraction never does. |
| 3. Monolithic fetcher | `remote.py:1-610`: transport `149-244`, resolver `256-382`, local assembly `385-452`, orchestration `455-487`, lifecycle `490-605`. | Split by those jobs below; direct then page resolver is ordered fallback, not polymorphic source handlers. |
| 4. Remote-kind exceptions | `source.py:19-25`; `media.py` adds `_require_materialized` and three resolver entries; `verify.py:500-503` rejects REMOTE; `extract.py:317-333` materializes. `doctor.py:32` changes only the dependency minimum, not remote-kind behavior. | No REMOTE; no `media.py`, `verify.py`, acquisition or handler edits. Keep the doctor minimum bump because it is a real dependency requirement. |
| 5. Comment/line growth | The extended rationale at `remote.py:1-24,75-84,477-479` and long statements at `remote.py:305`, `source.py:142`, `cli.py:90` corroborate the style concern. The owner's 105→114 count was not independently recounted. | English why-only comments; short module docstrings; changed/new Python lines at most 110 characters. Do not restyle unrelated existing lines. |
| 6. Long changelog | reference `CHANGELOG.md:7-10` has four detailed implementation-bearing bullets. | Only the three short user-facing lines specified below. |
| 7. CI skips real yt-dlp | current/reference `.github/workflows/ci.yml:8-17` install only pytest/numpy; reference `tests/test_remote.py:589,652,793,798,805,818,938,961` use `importorskip`. | Keep the lightweight matrix; add a required Ubuntu URL-runtime step with yt-dlp, ffmpeg/ffprobe, and explicit execution/no-skip proof. |

## Architecture and ownership

### Module layout

Use functions and small immutable result records, not fetcher classes or a registration framework. Names in this section are implementation contracts, not existing code.

| File / owner unit | Single job and required interface |
| --- | --- |
| `lectural/urlpolicy.py` / A | Pure input policy. `HTTP_SCHEMES`, `is_http_url(value)`, `url_origin(value)`, `remote_url_origin(value)`, `is_youtube_url(value)`, `public_source_label(value)`. Own scheme syntax including single-letter schemes/Windows-drive distinction, host handling and schemeless-token masking. No network/tool imports. |
| `lectural/fetch/__init__.py` / B | Ordered preparation orchestration. `prepare_source(argument) -> ContextManager[PreparedSource]`; internal `fetch_url(url, dest_dir) -> FetchedMedia`. Own direct→resolver choice, 403 precedence and login-wall policy, not transport/lifecycle implementation. |
| `lectural/fetch/http.py` / B | Checked HTTP transport. `open_url(url, headers=None)`, response streaming and safe filename generation; `try_direct(url, dest_dir) -> FetchedMedia | PageFallback`. Own opener/redirect handlers and direct content-type handling. |
| `lectural/fetch/ytdlp.py` / B | Page resolution to selected HTTP(S) formats, never media download. `resolve_formats(url, *, allow_generic=True) -> list[dict]`; guarded request-director adapter, silent logger, format selector and validation. |
| `lectural/fetch/assets.py` / B | Turn checked stream downloads into validated self-contained local media. `download_formats(formats, dest_dir) -> FetchedMedia`, `probe(path) -> bool`, `merge(video_path, audio_path, dest_dir) -> str`. `probe` returns whether valid media has video excluding `attached_pic`; `False` means valid audio-only, while invalid/no-media input raises bounded `RemoteSourceError(SOURCE_UNAVAILABLE)` (reference `remote.py:385-410`). Uses `http.open_url`; owns the local ffmpeg/ffprobe input guard. |
| `lectural/fetch/scratch.py` / C | Scratch lifetime only. `scratch_space() -> ContextManager[str]`, `sweep_stale_scratch(root=None, *, now=None) -> list[str]`; lock, signal restoration, deletion. No source parsing or fetching. |
| `lectural/fetch/errors.py` / A | Bounded error classification: `RemoteSourceError(ContractError)`, HTTP/status-chain and extractor classifications, date-based fixed update hint. Message catalog remains in `evidence.py`. |

`FetchedMedia(path: str, has_video: bool)` belongs in `assets.py`. `PreparedSource(source: InputSource, work_dir: str | None)` belongs in `fetch/__init__.py`. `PageFallback(login_wall: bool)` belongs in `http.py`; a direct first-request 403 remains a `RemoteSourceError` for the orchestrator to catch. Import `assets` from `http.try_direct` locally to avoid an import-time cycle; assets calls transport by module attribute. These are records, not a fetcher hierarchy.

`urlpolicy.py` must not import the fetch package. Move current `source._is_youtube_url` host logic there; retain `source.extract_video_id` as the existing public function. If `public_source_label` needs ID recognition to preserve valid YouTube labels, import that function locally inside the label function, not at module initialization. Source classification must not call `public_source_label` recursively: use the policy's pure URL/origin result for invalid-input errors. Import the shared scheme tuple into the yt-dlp adapter and build its selector/protocol expression from it, rather than defining another allowed-protocol list. Rechecking at each untrusted network boundary is required; redefining the rule is not.

### One preparation entry point

`fetch.prepare_source(argument)` is the only public entry point allowed to start a generic URL fetch. Both CLI adapters enter this context; all private fetching calls sit beneath it. The Python extraction API stays local/YouTube-only; Python callers needing URL support explicitly enter this same context and pass `source` and `work_dir`. Do not add preparation to `extract_source`, handlers, `run`, or `media`.

1. Preserve existing-file precedence, tilde/symlink behavior and missing-path errors. If input is an existing file, yield `classify_source(argument)` unchanged, `work_dir=None`.
2. For a valid generic HTTP(S) URL, enter `scratch_space`, fetch and validate, then construct the local `InputSource` directly. Do not reclassify by extension: direct audio such as MP3/AIFF and generated Matroska are valid fetched media even though local CLI suffix support stays unchanged.
3. For all other inputs, call pure `classify_source`: valid YouTube passes through without scratch or generic fetch; unsupported/malformed URLs fail without echoing secrets. A YouTube-host URL without a recognized video ID never falls through to the generic resolver.
4. The yielded URL source uses `argument=origin`, `locator=<scratch file>`, `title_hint=<host only>`, `video_id=None`, and `origin=origin`. Raw URLs exist only inside preparation/transport, never in the yielded identity. `work_dir` is the same scratch root.
5. `cli._extract_main`: syntax preflight uses `classify_source` unless the argument is a non-file with a valid `remote_url_origin`; it never constructs a remote kind. Then call `evidence.check_new_output(args.out)`, enter preparation, and finally call `prepare_empty_output` to create output. Preserve `OUTPUT_EXISTS` precedence for syntactically valid inputs without starting network I/O. Fetch failure returns exit 2 with all artifact paths null and no output directory. Context stays open through extraction and JSON assembly; cleanup completes before returning.
6. `cli._extract_then_notes_processor`: keep bundle-input fast path; enter preparation before metadata probing/reserving a slug directory, then probe and call extraction with the prepared identity and working directory. Close the context before consuming the evidence bundle for notes. Batch ordering, unique output reservation and continuing after one failure remain unchanged.
7. `extract_source(..., work_dir: str | None = None)` forwards to `_extract_source`; only speech acquisition and its audio-path fallback use `work_dir or out_dir`. Frames, transcript and evidence stay under `output_dir`; video resolution continues through `media.resolve_video` (local video is already in scratch). Resource sampling scope stays extraction-only, as in current `extract.py:289-304` and reference `extract.py:320-336`.

Extract `evidence.check_new_output(path) -> str` from the normalization/`lexists` portion of current `evidence.py:89-94`; return the absolute candidate without creating it. `prepare_empty_output` calls this helper too and retains its atomic `mkdir`/`FileExistsError` handling (`:96-104`). This is output policy, not another fetch path. A race at final creation is still `OUTPUT_EXISTS`/exit 2 and closes scratch. Source syntax failure still precedes output checks.

### Fetch behavior to retain

The implementation is a rewrite against these contracts, not a copy of `remote.py`:

- Transport: HTTP(S)-only opener without file/data/FTP handlers or cookie processor; check initial URLs and every redirect, including resolver redirects and final stream redirects. Preserve timeout 60 seconds, 1 MiB streaming chunks and ten-redirect limit (reference `remote.py:64-69,154-176,199-206,233-244`). Empty/truncated declared bodies fail. Never use yt-dlp's media downloader or ffmpeg's network access.
- Try one direct GET first. `audio/*`/`video/*` streams to scratch and is probed; other content goes to page resolution. Only a direct first-request 403 gets one resolver retry. If that retry is merely unavailable, retain access-denied; explicit login/access/redirect classifications take precedence. Other direct failures do not gain retries (reference `remote.py:455-487`).
- A redirected login wall allows only a site-specific resolver for the original URL, with Generic excluded even for delegated extraction (`allowed_extractors=["default", "-generic"]`). Failed resolution stays login-required except redirect rejection. Never return media embedded in a login page (reference `remote.py:209-216,323-354,474-485`; tests `937-969`).
- Resolver: in-process yt-dlp, no config/user cookie discovery, no playlists, quiet logger, `cookiefile=None`, `cookiesfrombrowser=None`, `download=False`. Its only request handler is guarded HTTP(S) urllib. Missing `build_request_director` or required networking adapter fails closed with the existing bounded dependency-install guidance; never run an unrestricted fallback (reference `remote.py:256-292,323-354`).
- Select progressive HTTP(S) audio+video first, then HTTP(S) video-only+audio-only in that order, then audio-only only when the page offers no video. Unknown codec metadata must not incorrectly discard a progressive candidate. Reject playlists, unsupported protocols, malformed selections, more than two streams, and audio-only fallback when the page has video available only as fragments (reference `remote.py:74-84,357-382`; tests `783-813`).
- Stream downloads use the checked opener. Drop `Cookie`, `Authorization` and `Proxy-Authorization` from resolver-provided headers, case-insensitively. Retain other necessary headers such as User-Agent (reference `remote.py:97,432-452`). Do not enable user credentials from URL userinfo; public labels must omit it regardless of rejection behavior.
- Probe every fetched stream using `ffprobe -hide_banner -loglevel error -protocol_whitelist file -format_whitelist mov,matroska,mp3,aac,ogg,wav,w64,flac,aiff,caf,mpegts,flv,avi,asf,mpeg -show_entries stream=codec_type:stream_disposition=attached_pic -of json <path>`. On valid media, return `has_video`, excluding `attached_pic`; `False` means valid audio-only, not failed validation. Invalid input or no media streams raises bounded `RemoteSourceError(SOURCE_UNAVAILABLE)` (reference `remote.py:385-410`). Manifests/concat must fail before any downstream ffmpeg stage can see them.
- Merge split files with `ffmpeg -nostdin -hide_banner -loglevel error`, the same input guards before each `-i`, `-map 0:v:0 -map 1:a:0 -c copy -f matroska -y <scratch>/media.mkv`. Remove split inputs after successful merge; keep merged media only until context exit. HLS/DASH fragment-only sources fail unavailable, with no segment fetch (reference `remote.py:385-452`).
- Scratch: private `lectural-fetch-*` directory; delete on success, ordinary error, `KeyboardInterrupt` and main-thread SIGTERM (`SystemExit(143)`), restoring the previous signal handler. Hold an exclusive nonblocking `flock` while live. Before a URL run, POSIX sweep removes only same-user real directories with matching prefix older than one hour and obtainable lock; preserve fresh/live/unrelated/symlink paths. No deletion based only on a name. Non-POSIX sweep is a no-op; SIGKILL is handled only by a later sweep. Failure to delete warns without embedding a raw URL (reference `remote.py:490-605`).

## Identity, redaction and errors

Add `origin: str | None = None` to the frozen `InputSource`; it is safe provenance, not behavior or a new kind. `as_dict`/`safe_as_dict` use the origin for fetched sources, with unchanged shapes for existing inputs. No serialized `origin` field is added. `evidence._safe_source` reduces URL-shaped arguments with the same `urlpolicy` function, not a separate origin regex; local filename and YouTube canonicalization rules stay intact. Origin means **scheme://host only**, lowercased with trailing host dot removed and IPv6 brackets preserved; exclude userinfo, port, path, query and fragment. Never derive titles from page metadata, URL basenames, or tool output (reference `source.py:79-109,157-199`; `remote.py:578-596`).

Example fetched-video source fragment (synthetic):

```json
{
  "id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "kind": "local_video",
  "argument": "https://media.example.invalid",
  "title": "media.example.invalid",
  "has_video": true,
  "citation": {"kind": "transcript"}
}
```

Generic URL speech remains `speech.source="stt"`, `speech.fallback.code="local_source"`; audio sources have no frames and not-applicable visual completeness. No scratch locator or derived `audio.wav` survives in a bundle/handoff. SHA-256 compares the acquired bytes, not the URL text.

Preserve bounded messages from reference `evidence.py:33-40` verbatim:

| Code / message | Classification |
| --- | --- |
| `SOURCE_INVALID`: The source is not a supported YouTube URL, public http(s) media URL, or local media file. | Invalid/missing host, unsupported scheme, malformed source. |
| `SOURCE_REDIRECT_REJECTED`: The source URL redirected to a location that is not http or https. | Any prohibited redirect, before following it. |
| `SOURCE_LOGIN_REQUIRED`: The source URL requires a login; only public URLs are supported. | 401/407, login/cookies requirement, unresolved login wall. |
| `SOURCE_ACCESS_DENIED`: The source URL refused access: the media may be private, or the site may block programmatic downloads; only public URLs are supported. | 403/private notice, after the single direct-403 resolution rule. |
| `SOURCE_UNAVAILABLE`: The source could not be accessed for extraction. | DNS/connection, 404/5xx, empty/truncated body, invalid media/format/manifest. |

`SOURCE_UNAUTHORIZED` is superseded and must not return. Preserve status-chain-before-message classification, strip embedded URL text before searching login/private words, and do not surface exception causes, yt-dlp logs or subprocess stderr for generic URL failures (reference `remote.py:295-320`). Missing yt-dlp/hook remains a bounded `DependencyError` with fixed install guidance, rather than inventing a new public failure code; the CLI maps it as the reference did to `EXTRACTION_FAILED`/exit 1, with null URL source identity. Add an explicit regression for this case because the old hook test checked only the exception boundary.

For login/access failures only, a yt-dlp release strictly more than 90 days old appends the fixed update hint from reference `remote.py:92-95` (including the `uv pip install -U "yt-dlp"` example). Unparseable/missing versions get no age hint. Keep `yt-dlp>=2026.8.19` in `[run]`, doctor and the regenerated lockfile (reference plan `:52-57`, current `pyproject.toml:27`, `doctor.py:32`). This minimum is a behavior reference, not a claim that every site works indefinitely.

Fetch/validation failures use exit 2, `status="error"`, `result.source=null`, `result.failure={code,message}`, identical entries in `errors` and `result.extraction.reasons`, and all four artifact paths null. Extend `build_failure_response(..., message=None)` only for bounded constant error text plus the fixed hint, not arbitrary exception messages (reference `evidence.py:340-375`). After a fetched-source pipeline failure, preserve exit 1 and null `result.source` as asserted by reference `tests/test_remote.py:302-313`; output paths may identify the created bundle but never scratch. Do not silently change this just because preparation now knows the media kind.

Sanitize before `runstate.start_session`, failed batch result creation and diagnostic rendering (current `cli.py:219-223,260,285-299` expose raw values today). Parser sanitization must cover root/subparsers, `--option=value`, longest-first replacement, and both raw/repr-escaped quoted inputs; preserve useful command hints. Local/recognized YouTube labels keep existing behavior. For generic sources, pipeline diagnostics/tool stderr and unexpected notes exceptions must be bounded rather than forwarded: a prepared local path can itself reveal sensitive scratch state. Keep ordinary local/YouTube diagnostics unchanged. Error handling must distinguish preparation errors from later extraction errors, not catch every `ContractError` as exit 2.

`verify --source <generic URL>` does not call preparation: pure `classify_source` still rejects it, so current `verify.py:496-501` already returns `SOURCE_INVALID`. Verify against an owner-held local copy or omit `--source`; do not refetch to manufacture identity.

## Exact reference-test disposition

These are test identities, not code to copy. **M** = move/rewrite into `tests/test_urlfetch.py` retaining name, every parameter row and observable assertions; update monkeypatch targets to the module that owns the function and replace `materialize(classify_source(url))` with `prepare_source(url)`. **K** = keep in its current file. **D** = drop only an obsolete internal assertion, never its behavioral coverage. Helpers (`server`, `temp_root`, `ftp_listener`, fake pipeline, token scanner, comparator and split-page generator) move as test support; fixtures remain synthetic and local-server-only.

All test functions in reference `tests/test_remote.py` are accounted for below. Line ranges include decorators/parameter data where relevant.

| Reference lines / function (`test_` prefix) | Disposition / preserved acceptance |
| --- | --- |
| 246-276 `url_fixture_produces_local_file_evidence_shape_and_leaves_no_media` | M: URL/local equivalence, source hash/title/citation, scratch audio, no token/media residue. |
| 279-290 `audio_url_becomes_local_audio_evidence` | M: audio kind, no visuals, cleanup. |
| 293-299 `redirect_to_http_media_is_followed` | M: allowed redirects. |
| 302-313 `failed_extraction_still_removes_fetched_media` | M: exit 1, null source and cleanup. |
| 316-348 `remote_failures_are_bounded_and_leave_nothing` | M: all nine redirect/auth/missing/truncated rows, no output or scratch. |
| 351-368 `direct_403_is_decided_after_one_page_resolution` | M: all three precedence rows and exactly one resolution. |
| 371-378 `direct_403_is_fetched_when_page_resolution_finds_public_media` | M: successful retry and local identity. |
| 381-393 `ytdlp_errors_map_to_the_three_classes` | M: all six rows, including URL words not becoming login/private evidence. |
| 396-410 `ytdlp_http_status_in_the_error_chain_wins_over_text` | M: nested 403 precedence. |
| 413-431 `outdated_ytdlp_adds_a_bounded_update_hint` | M: age/version cases and message equality across failure fields. |
| 434-439 `unreachable_url_is_bounded` | M: unavailable/exit 2. |
| 442-456 `non_http_sources_are_rejected_before_output_creation` | M: three schemes and no output. |
| 459-479 `notes_run_redacts_url_in_run_state_and_output` | M: mixed batch, safe handoff/state, no scratch. |
| 508-529 `page_url_downloads_the_single_progressive_format_ytdlp_selects` | M: selected bytes, host title, cookie suppression, no playlists. |
| 532-566 `page_url_resolution_failures_are_bounded` | M: every protocol/playlist/count/audio-fallback row and no exception cause. |
| 588-595 `real_ytdlp_resolves_html5_page_through_checked_download` | M: real resolver on loopback HTML5. |
| 598-610 `ytdlp_without_request_director_hook_fails_closed` | M: missing hook must never activate unrestricted networking. |
| 613-625 `invalid_url_like_inputs_never_reach_run_state_or_stderr` | M: all invalid batch inputs masked. |
| 628-647 `parser_errors_do_not_echo_url_tokens` | M: all nine parser rows, including quotes/option values. |
| 650-660 `real_ytdlp_never_follows_a_redirect_to_ftp` | M: both resolution/download routes, no listener connection. |
| 695-724 `split_video_and_audio_streams_merge_into_local_file_evidence` | M: checked two-file order, equivalence to merged local bytes. |
| 727-752 `real_ffmpeg_merges_split_streams_locally` | M: actual Matroska video+audio, local evidence equivalence. |
| 755-762 `manifest_served_as_media_is_rejected_without_fetching_segments` | M: media MIME spoof still fails before segment/network access. |
| 783-794 `real_ytdlp_prefers_progressive_then_http_split_pair` | M: all four selection rows, including unknown progressive codecs. |
| 797-801 `real_ytdlp_selects_nothing_from_fragment_protocols_only` | M: HLS/DASH-only unavailable. |
| 804-813 `real_ytdlp_hls_page_fails_bounded_without_fetching_segments` | M: no segments, no tokens. |
| 816-826 `real_ytdlp_classifies_http_auth_failures` | M: both 403 and 401 rows. |
| 829-838 `keyboard_interrupt_during_fetch_removes_media` | M: interruption cleanup. |
| 841-869 `sigterm_during_fetch_leaves_no_media` | M: child exits 143 with no scratch. |
| 872-906 `stale_scratch_sweep_removes_only_old_unlocked_own_dirs` | M: stale removal; fresh/locked/unrelated/symlink retained. |
| 909-925 `materialize_sweeps_stale_scratch_before_fetching` | M: keep name for traceability; exercise prepare-time sweep and non-POSIX no-op. |
| 928-934 `login_wall_redirect_still_accepts_media_a_site_extractor_resolves` | M: allow site-specific success on original input. |
| 937-947 `real_ytdlp_without_generic_refuses_delegation_to_generic` | M: real Generic exclusion, including explicit delegation. |
| 950-957 `login_wall_redirect_stays_login_required_when_resolution_fails` | M: both private/unsupported errors stay login-required. |
| 960-969 `real_ytdlp_never_fetches_video_embedded_in_a_login_wall` | M: no login-wall embedded-media fetch. |
| 972-984 `real_probe_accepts_self_contained_direct_audio` | M: AIFF, MP3 and WAV rows. |

Reference `tests/test_source.py` mapping:

| Lines / test identity | Disposition |
| --- | --- |
| 13-26 `test_classify_existing_local_suffixes` | K, all suffix rows. |
| 29-39 `test_local_source_as_dict_omits_runtime_locator` | K, unchanged. |
| 42-61 `test_youtube_recognition_is_preserved` | K, all existing URL/ID rows. |
| 64-82 `test_extract_video_id_stays_pure_and_rejects_malformed_values` | K: keep generic-URL rejection in pure classifier; preparation, not classification, accepts it. Replace any non-synthetic generic host in touched fixtures with `.invalid`. |
| 84-87 `test_missing_supported_path_is_not_youtube_even_with_shorts_id` | K. |
| 90-110 `test_tilde_and_symlink_normalize_without_modifying_target` | K, preserve platform skip. |
| 113-133 `test_tilde_path_uses_isolated_expanduser_environment_without_symlink` | K. |
| 136-152 `test_public_http_urls_classify_as_remote_with_origin_only` | M to `tests/test_urlpolicy.py`, rename `test_public_http_urls_prepare_as_local_with_origin_only`: keep three URL/case rows and origin/serialization/citation assertions, fake only the fetch. D only `kind is REMOTE`; replace with local kind and assert no extra enum value. |
| 155-178 `test_non_http_urls_are_rejected_without_echoing_the_url` | M to `tests/test_urlpolicy.py`, same name/all rows; exercise both classifier and preparation rejection with zero fetch calls. |
| 181-186 `test_youtube_hosts_never_become_remote_sources` | M to `tests/test_urlpolicy.py`, same name; invalid YouTube page fails and valid YouTube variants pass through without generic fetch. |
| 189-201 `test_public_source_label_keeps_local_and_youtube_and_reduces_urls` | M to `tests/test_urlpolicy.py`, import from its new owner, all assertions kept. |
| 204-208 `test_windows_drive_paths_are_not_url_schemes` | M to `tests/test_urlpolicy.py`, keep both slash variants. |

Only `test_remote.py` and `test_source.py` were changed in the reference's test delta. All other old test functions are K unchanged on the new base, except reference `tests/test_media.py:109-112::test_all_source_kinds_have_explicit_resolver_entries`: D the removed private-dict assertions because PR #48 already moved the invariant to current `tests/test_sources.py:11-15::test_every_source_kind_has_a_handler`. Do not restore old resolver dictionaries. No accepted URL behavior test is dropped.

Add regressions not sufficient in that bank: fetch called exactly once per extract/notes URL and zero times for local/YouTube/bundle/verify; output-exists zero-fetch and creation-race cleanup; origin redaction for userinfo/port/fragment/IPv6 and malformed URL-like parser values; all three credential headers dropped; safe source after post-fetch pipeline exceptions; missing package/hook CLI mapping; signal handler restoration; foreign-owner sweep rejection via fake stat; no scratch path in errors/handoff; no full-length derived audio in notes or extract bundles. Assertions must inspect stdout, stderr, failure JSON, manifest, transcript/notes handoff, returned failed results and runstate, not only check the error code.

## Verification plan (implementation stage only)

No results below are claimed. Use fresh disposable outputs and owner-held logs. Source evidence and notes equivalence compare the same bytes; normalize only timestamps/resources/output prefixes, frame paths and the deliberate origin/title difference, as reference `tests/test_remote.py:235-243,260-262,714-723` does. Do not normalize source kind/hash, fallback codes, completeness, tokens or exit codes.

### Offline and concrete CI no-skip proof

Keep the existing OS matrix command `uv run --with pytest --with numpy pytest -q`. Add markers `url_ytdlp` and `url_runtime` in `pyproject.toml` without changing `not smoke` defaults. The eight reference real-yt-dlp functions below get both markers; the real ffmpeg/manifest/direct-audio and POSIX lifecycle functions get `url_runtime`. Ordinary stubbed tests remain runnable without yt-dlp. Do not mark these as `smoke` and thereby hide them from the normal suite.

New required Ubuntu job in `.github/workflows/ci.yml`: checkout/setup-uv as the current job, `sudo apt-get update && sudo apt-get install -y ffmpeg`, then all commands in the same dependency environment:

```bash
uv run --with pytest --with numpy --with 'yt-dlp==2026.8.19' python -c \
  "import shutil, yt_dlp; assert shutil.which('ffmpeg') and shutil.which('ffprobe')"
uv run --with pytest --with numpy --with 'yt-dlp==2026.8.19' \
  pytest -q -m url_runtime tests/test_urlfetch.py --junitxml=url-runtime.xml
uv run --with pytest --with numpy --with 'yt-dlp==2026.8.19' python - <<'PY'
from collections import Counter
import xml.etree.ElementTree as ET
cases = list(ET.parse('url-runtime.xml').getroot().iter('testcase'))
assert cases and not any(c.find('skipped') is not None for c in cases)
assert not any(c.find('failure') is not None or c.find('error') is not None for c in cases)
expected = {
    'test_real_ytdlp_resolves_html5_page_through_checked_download': 1,
    'test_real_ytdlp_never_follows_a_redirect_to_ftp': 2,
    'test_real_ytdlp_prefers_progressive_then_http_split_pair': 4,
    'test_real_ytdlp_selects_nothing_from_fragment_protocols_only': 1,
    'test_real_ytdlp_hls_page_fails_bounded_without_fetching_segments': 1,
    'test_real_ytdlp_classifies_http_auth_failures': 2,
    'test_real_ytdlp_without_generic_refuses_delegation_to_generic': 1,
    'test_real_ytdlp_never_fetches_video_embedded_in_a_login_wall': 1,
    'test_real_ffmpeg_merges_split_streams_locally': 1,
    'test_manifest_served_as_media_is_rejected_without_fetching_segments': 1,
    'test_real_probe_accepts_self_contained_direct_audio': 3,
    'test_sigterm_during_fetch_leaves_no_media': 1,
    'test_stale_scratch_sweep_removes_only_old_unlocked_own_dirs': 1,
}
seen = Counter(c.attrib['name'].split('[', 1)[0] for c in cases)
assert all(seen[name] == count for name, count in expected.items()), (seen, expected)
assert len(cases) >= 20
PY
```

The expected table requires 13 real-yt-dlp parameter cases plus seven binary/POSIX cases: 20 total. Marker deletion, missing parameter rows, an empty collection or import skips fail even if pytest itself exits zero. Pin the measured minimum in this new job to exercise compatibility; the normal supported runtime remains `>=2026.8.19`, not an exact dependency pin. Keep any future marker additions visible in the expected table. Store only synthetic CI reports; no real-site artifacts.

Prove the dependency distinction locally during implementation with `PYTHONPATH=. uv run --isolated --no-project --with pytest --with numpy python -c "import importlib.util; assert importlib.util.find_spec('yt_dlp') is None"`, then `PYTHONPATH=. uv run --isolated --no-project --with pytest --with numpy pytest -q -m url_ytdlp tests/test_urlfetch.py -rs --junitxml=url-without-ytdlp.xml`. It must collect the same 13 cases and report their missing-yt-dlp skips. Inspect that JUnit report for exactly those 13 expected cases with skip entries. Then run the new installed job command: those exact cases pass, no skips. This is a controlled two-environment check, not permission to suppress failures in the installed job.

Run the full offline suite once after integration; also `git diff --check`, inspect changed Python lines for the 110-character/why-only-comment gate, and `claude plugin validate .` as required by current `CONTRIBUTING.md:78-113`. Do not broaden dependency caps to make the feature pass.

### Runtime smoke and local server

Implementation operator: install `.[run]`, run `lectural doctor`, and record tool versions; doctor may check more than this fetch path needs. Generate synthetic media outside the repo, serve only that directory with `python -m http.server 8765 --bind 127.0.0.1 --directory "$FIXTURE_ROOT"`; use a custom test server for redirect/auth/truncation cases (the existing test fixture supplies those routes).

```bash
lectural extract "http://127.0.0.1:8765/synthetic-video.mp4?tok=FAKESECRET42" \
  --out "$RUN_ROOT/url-video" --skip-ocr --json
lectural extract "$FIXTURE_ROOT/synthetic-video.mp4" \
  --out "$RUN_ROOT/local-video" --skip-ocr --json
lectural notes "http://127.0.0.1:8765/synthetic-audio.wav?tok=FAKESECRET42" \
  --out "$RUN_ROOT/notes"
lectural inspect "$RUN_ROOT/url-video" --json
lectural verify "$RUN_ROOT/url-video" --json
lectural verify "$RUN_ROOT/url-video" \
  --source "http://127.0.0.1:8765/synthetic-video.mp4?tok=FAKESECRET42" --json
```

Bind paths/environment values to disposable owner-held directories, never publish their expansions. Expect the last command's source check to fail with `SOURCE_INVALID`/exit 1 and zero refetch; inspect/verification of an otherwise valid bundle pass. Compare source hash and manifest structure to local bytes; repeat video smoke with OCR enabled and audio smoke without visuals. Exercise split streams and bad schemes/redirects/auth/truncation via the mapped fixture tests. During a slow download send SIGTERM and later simulate stale unlocked scratch; inspect cleanup and bounded messages. Check whole output/state text for synthetic path/query tokens and absence of retained full media/audio. Do not claim a successful ASR/OCR outcome from transport-only tests.

### Real-site acceptance and stage-2 provenance

Reference `.ops/plans/45-public-media-url.md:50-59` records why stage 2 added split streams, stale cleanup, updated yt-dlp and differentiated access failures. Treat its live observations as **owner-held sanitized evidence (2026-10-21)**, not guaranteed current site behavior. It records an older resolver reporting login-required while the later measured release exposed progressive/split media, and an interrupted large fetch leaving scratch behind. No raw site metadata or sizes need to be committed.

The owner-held runbook must bind `REAL_SITE_URL` to the exact requested Instagram reel, with the fake `?tok=FAKESECRET42` query. Do not replace that run with the `.invalid` fixture or a different reel. Run `lectural extract "$REAL_SITE_URL" --out "$RUN_ROOT/public-short-video-01" --skip-ocr --json`, then inspect/verify the bundle and run `notes` on the same source to cover runstate/handoff. Preserve command exit/status, actual selected format topology, current yt-dlp version, bounded failure classification and cleanup findings in owner-held evidence. A public-site outage/access block is a recorded failure/blocker, not a skipped or mocked pass. Scan stdout/stderr, error JSON, output tree and runstate for the fake token and original URL path/query; all must be absent. Compare with a local copy of the exact fetched/merged bytes within the same private verification session if source-hash equivalence is needed. Retain that comparison copy unless the owner has privately been shown its exact storage location and deletion target and explicitly approved deleting that individual item; blanket deletion authorization does not suffice. This requirement does not change the already-approved fetch scratch lifecycle.

No real-site command is run for this plan. The committed record may say only the sanitized fixture identity, exercised scenario and verdict, with the provenance label above; executable real-site input stays outside committed artifacts.

## Expected diffs and work units

Estimates are gross added/deleted lines against `3ca5b0b`, not promises or measured implementation diffs. Rewriting the behavioral test bank is most of the patch; existing pipeline edits should remain small. Review any range overrun before expanding scope.

| File | Expected + / − lines | Reason / owner |
| --- | ---: | --- |
| `lectural/urlpolicy.py` | +100–140 / −0 | One pure policy/label home, A. |
| `lectural/fetch/__init__.py` | +85–120 / −0 | Preparation and ordered fallback, B. |
| `lectural/fetch/http.py` | +115–150 / −0 | Direct transport/streaming, B. |
| `lectural/fetch/ytdlp.py` | +150–195 / −0 | Guarded resolution and selection, B. |
| `lectural/fetch/assets.py` | +95–125 / −0 | Local validation and split assembly, B. |
| `lectural/fetch/scratch.py` | +120–150 / −0 | Lifecycle/locks/sweep, C. |
| `lectural/fetch/errors.py` | +80–105 / −0 | Safe classification and fixed hint, A. |
| `lectural/source.py` | +25–45 / −15–25 | Optional origin, pure rejection/label policy; remove old host helper, A. |
| `lectural/evidence.py` | +25–45 / −8–15 | Messages, shared origin reduction, output preflight extraction and bounded message override, A. |
| `lectural/cli.py` | +85–120 / −35–55 | Two adapters to one pre-step, safe parser/state/error boundaries, D. |
| `lectural/extract.py` | +8–15 / −3–6 | `work_dir` forwarding and speech/audio fallback path only, D. |
| `lectural/doctor.py` | +1 / −1 | Minimum version only, A. |
| `pyproject.toml` | +3–5 / −1 | Minimum and two marker declarations, C integration owner. |
| `uv.lock` | +4–12 / −4–12 | Regenerate for deliberate yt-dlp minimum, C integration owner. |
| `.github/workflows/ci.yml` | +55–75 / −0 | URL-runtime job and executable no-skip proof, C. |
| `tests/test_urlfetch.py` | +1020–1160 / −0 | All reference URL tests and new boundary regressions, D integration owner. |
| `tests/test_urlpolicy.py` | +130–175 / −0 | Mapped pure-policy/prepared identity tests plus redaction edges, A. |
| `tests/test_source.py` | +10–20 / −1–3 | Prepared origin serialization and synthetic touched fixture, A. |
| `README.md` | +12–20 / −3–5 | URL support/limits/study-only use and corrected yt-dlp FAQ, E. |
| `docs/contracts/cli.md` | +22–35 / −3–6 | Exact input/error/lifetime/offline-verify contract, E. |
| `commands/notes.md` | +2–4 / −2–3 | Accept URL input in description/input gate, E. |
| `CHANGELOG.md` | +5–7 / −0 | Heading/spacing and three concise lines below, E. |
| `lectural/media.py`, `lectural/acquisition.py`, `lectural/verify.py`, `lectural/sources/*` | 0 / 0 | Existing local/YouTube behavior already suffices; no remote leakage. |
| JSON schemas, plugin metadata, unrelated tests/plans | 0 / 0 | No contract/version bump, feature-only diff. |

Parallel implementation boundaries: A owns shared policy/errors/identity plus policy tests; B owns transport/resolution/assembly/preparation; C owns scratch/CI/dependency manifest integration; D owns CLI/extraction and the single URL integration-test file; E owns user docs. Agree the interfaces above before worktrees diverge. B consumes A/C APIs; D consumes B's context. Integrate A and C before B, then D and E. No two units edit the same file. Keep full test-bank ownership with D rather than scattering partial edits. Run checks only once after integration, not against half-integrated worktrees.

Future seams, not implementations: cookies belong to preparation's resolver/transport request options; both must receive an explicit future cookie policy, never a SourceHandler change or automatic browser discovery. Keep selection separate from `download_formats(list, ...)` so #44 can later request audio-only even when the page has video; #44 also needs a pipeline visual-gating option, not merely a selector tweak. Do not add unused cookies/speech flags or abstractions now (reference `remote.py:376-381,432`; current plan `source-handlers.md:113`).

Changelog: one short bullet per user-visible change, no architecture/lock/signal internals:

- Accept public HTTP(S) media URLs without cookies; segmented HLS/DASH video is unsupported.
- Fetch separate HTTP(S) video and audio streams when needed.
- Report URL failures as `SOURCE_LOGIN_REQUIRED`, `SOURCE_ACCESS_DENIED`, `SOURCE_REDIRECT_REJECTED`, or `SOURCE_UNAVAILABLE`.

## Commit and replacement gates

Planning now: after independent review and owner-request compliance check, commit only this file as `docs(ops): plan URL fetch pre-step for #45`. No push or GitHub writes in this run.

Implementation later, after owner approval of this plan:

1. `feat(source): prepare public URLs as disposable local inputs` — A/B/C production/dependency work plus corresponding policy/fetch unit coverage; no isolated unused scaffolding commit. Integrate their worktrees before this commit.
2. `feat(cli): route URL inputs through one fetch pre-step` — D integration and complete mapped test bank, failure/redaction/output lifecycle, working-directory seam; ordinary local/YouTube/bundle behavior unchanged.
3. `ci: exercise URL runtime tests without skips` — required installed-runtime job, marker manifest and no-skip evidence. Move marker declarations here if not required for preceding test collection; otherwise keep their single definition in commit 1.
4. `docs: document public URL input and limits` — E docs and short changelog, publish only sanitized verification findings in the future PR's Validation section.

Each final commit must be reviewable and its relevant tests pass after integration; do not commit temporary adapters, duplicate implementations or compatibility aliases. Rebuild from current sources, not cherry-pick the old implementation. Do not edit the other plan to simulate source-of-truth cleanup.

Future remote actions require explicit owner approval, separate from local implementation approval: push this branch; open a new PR into `main` using the exact CONTRIBUTING template with `Closes #45`; include the old→new behavior/test mapping and actual verification outcomes. Link #47 as superseded. Only after the replacement PR exists and the owner approves closing it, close #47 with a pointer to the new PR. Do not reuse/edit the old PR or close it before its replacement exists. Merge requires maintainer approval (current `CONTRIBUTING.md:38-65`).

## Risks and owner questions

- yt-dlp request-director/network adapter APIs can drift: fail closed, test the measured minimum in CI, and record the actual version in owner-held real-site runs. Do not weaken guards to make a site pass.
- Origin-only metadata cannot remove secrets spoken or displayed in media; redaction covers source metadata/diagnostics, not arbitrary transcript/OCR content. Synthetic token tests must keep tokens out of the media payload.
- Scratch deletion after SIGKILL is delayed, POSIX-only and needs a later URL run; non-main-thread SIGTERM does not acquire a Python handler. Preserve the documented limit, not an absolute cleanup promise. Cleanup failures must not silently claim deletion.
- Direct MIME lies and split-format containers can hide manifests; preserve guarded probe before any downstream tool, plus segment-hit assertions. Verify generated merged media has the expected streams.
- Preparation/output ordering can accidentally change `OUTPUT_EXISTS` precedence or lose the null-source failure contract; dedicated tests above are required.
- The remaining implementation size reflects accepted security/lifecycle behavior and its tests. Fewer modules by recombining unrelated responsibilities, a fourth handler/kind, and extraction-level auto-fetch were rejected because they recreate the reviewed problems.
- Open verification question: the exact historical 105→114 overlong-line count was not recomputed; implementation acceptance uses the changed-line limit, not that unverified total.
- Owner approval before implementation: confirm this single-entry CLI preparation design and the explicitly local/YouTube-only low-level extraction API; no accepted CLI behavior is reduced.
- Real-site gate prerequisite: the owner-held request already supplies the exact executable Instagram input; retain and bind that value outside committed artifacts rather than asking for it again or republishing it. The implementation operator still needs an environment with the runtime/models. A failed real-site attempt is reported honestly, not waived automatically.
- Owner decisions deferred until there is a verified implementation: authorize push/new PR; separately authorize closing #47 with its replacement pointer; approve merge. No decision about cookies or #44 implementation is needed for this slice.
