# Plan: Public http(s) media URLs (#45, first slice)

## Inputs

- Issue: [#45](https://github.com/haesol-shin/lectural/issues/45) — generic media URL with an optional cookie file.
- Maintainer decision (2026-10-19): ship public `http`/`https` URLs first, without cookies. `--cookies` and #44 (speech-only/range) are out of scope and stay with later issues.
- Risk: high (widens accepted input; signed URLs and downloaded media are privacy-sensitive).

## Scope kept from #45

- `<source>` accepts a non-YouTube `http`/`https` URL. `file:`, `data:`, `ftp:` and every other scheme are rejected.
- Redirects are followed only to `http`/`https` targets.
- Downloaded media lives only in a temporary directory that is removed after success and failure.
- Evidence, stdout, error output and run state record only the URL scheme and host — never the path or query.
- Caption selection stays YouTube-only; generic URLs are transcribed (ASR).
- Docs state personal-study-only use, no redistribution, and that following source rules is the user's responsibility.
- YouTube and local-file behavior is unchanged.

## Out of scope

`--cookies`, any login flow, LMS-specific code, DRM bypass, `--keep-media`, speech-only/range extraction (#44).

## Approach

1. `lectural/source.py`: new internal `SourceKind.REMOTE` for non-YouTube `http(s)` URLs. `InputSource` gains `origin` (scheme://host). `safe_as_dict` uses the origin as `argument`. Any other scheme is rejected before the YouTube check, so a YouTube-shaped ID never exempts it. Error messages and run-state labels never echo a URL (with or without a scheme) beyond its origin or host.
2. `lectural/remote.py` (new): fetcher with a urllib opener that has only HTTP/HTTPS handlers, no cookie processor, and a redirect handler that rejects non-`http(s)` targets.
   - One preflight GET. A `video/*` or `audio/*` response is streamed directly to the temp directory.
   - Otherwise the yt-dlp Python package (`[run]` extra) runs in-process — no config, no cookie file, no playlists, silent logger — and selects a single progressive `http`/`https` format (no merge, no HLS/DASH). Its request director holds only an HTTP/HTTPS urllib handler with a guard that checks each redirect target before yt-dlp follows it; LecturAL fails closed when the installed yt-dlp lacks the `build_request_director` hook. LecturAL downloads the selected format URL itself through the same redirect-checked opener.
   - Bounded failures: `SOURCE_INVALID` (scheme), `SOURCE_REDIRECT_REJECTED`, `SOURCE_UNAUTHORIZED` (401/403/407 or login-required), `SOURCE_UNAVAILABLE` (DNS, connection, 404/5xx, no usable format).
   - `materialize(source)` context manager yields a local `InputSource` (`local_video` when the fetched format has video, else `local_audio`) plus a scratch directory; the scratch directory is removed in `finally`.
3. Evidence shape: a fetched URL produces the same manifest as a local file — `source.kind` `local_video`/`local_audio`, `source.id` `sha256:` of the downloaded bytes, `speech.fallback.code` `local_source` — except `source.argument` is `scheme://host`. The title is always the host: page titles can quote URL tokens in forms no filter reliably catches. No contract or schema version change.
4. Generated `audio.wav` for fetched sources is written to the scratch directory, not the bundle, so no full-length copy of fetched media remains.
5. CLI: `extract` maps fetch failures to exit `2` with a bounded JSON failure; `notes` materializes before reserving the output directory and stores only the origin in run state and error text. `verify --source <URL>` reports `SOURCE_INVALID` for generic URLs (no refetch).
6. Docs: README, CLI contract, `commands/notes.md`, CHANGELOG.

## Tests (offline)

- Local `http.server` fixture under a path/query containing secret tokens, processed by `lectural extract --json` into the same evidence shape as the same bytes given as a local file (same `source.id`).
- Temp directory empty after success and after a failing pipeline stage.
- Tokens absent from `evidence.json`, stdout, stderr, run state and failure JSON.
- Bounded failures: `file:`/`data:`/`ftp:`/single-letter-scheme sources (also YouTube-shaped ones), redirect to a non-`http(s)` target, unreachable host, 401/403, truncated download.
- yt-dlp path with a stubbed extractor: format/protocol filtering and error classification. With yt-dlp installed, a real HTML5 page resolves through the checked download, and a redirect to an FTP listener met during resolution or download is rejected with no connection attempt.

## Residual risk

- The guard relies on yt-dlp's `build_request_director` hook and urllib request handler, which are not a stable public API; a missing hook fails closed.
- A process killed with SIGKILL cannot remove its temp directory; stage 2 sweeps it on a later URL run (POSIX only).
- Stage 2 retries a first-request 403 through yt-dlp; the code still cannot tell private media from a site that blocks non-browser clients, so the message names both.

## Stage 2 (approved 2026-10-20)

Inputs: owner-held sanitized evidence (2026-10-20) — a public short-video page resolved with yt-dlp 2026.08.19 (formats: progressive mp4 with unknown codecs, `https` video-only and audio-only streams) but reported "login required" with yt-dlp 2026.06.09; a long page run killed by SIGTERM left a 124 MB `lectural-fetch-*` directory behind.

1. Failure classes replace `SOURCE_UNAUTHORIZED` (never released) with `SOURCE_LOGIN_REQUIRED` (401/407, a redirect to a login wall — then only a site-specific yt-dlp extractor may resolve the original URL, never generic page extraction — or yt-dlp asking for a login or cookies), `SOURCE_ACCESS_DENIED` (403 or a private notice; a 403 on LecturAL's own first request is retried once through yt-dlp page resolution before deciding; the message says it may be private or blocked), and `SOURCE_UNAVAILABLE` (everything else). For the first two, a bounded "update yt-dlp" hint is appended when the installed yt-dlp is more than 90 days old. Exit stays `2`; messages stay constant text.
2. Formats: the yt-dlp selector prefers one progressive `http(s)` file with audio and video, then the best `http(s)` video-only plus audio-only pair, then audio-only only when the page offers no video at all. Each selected stream is downloaded by LecturAL's redirect-checked opener; a pair is merged by ffmpeg in the scratch directory with `-protocol_whitelist file` and stream copy into Matroska. Downloaded files whose container is a playlist/manifest (HLS, DASH, concat) are rejected before any further ffmpeg step. HLS/DASH fragment protocols stay a bounded `SOURCE_UNAVAILABLE`: yt-dlp's native HLS/DASH downloaders hand some manifests to ffmpeg (network I/O outside the guarded request director), so the guarantee cannot be kept. The download step takes a list of selected formats so an audio-only selector (#44) can reuse it.
3. Cleanup: `materialize` turns SIGTERM into `SystemExit(143)` while a scratch directory exists, so the existing `finally` removes it (also on KeyboardInterrupt). The live run holds an exclusive `flock` on its scratch directory; the next URL run removes `lectural-fetch-*` directories that are owned by the user, older than one hour, and not locked (POSIX only).
4. `[run]` and doctor require `yt-dlp>=2026.8.19`, the release measured to resolve the public page above; it still has the `build_request_director` hook, and a missing hook still fails closed.

Tests: local HTTP fixtures per failure class and the 403 retry; the real yt-dlp selector on synthetic split formats; a split pair merged (stubbed and, with ffmpeg, real) into the same evidence shape as the merged file given locally; an HLS page that fails bounded without fetching segments; SIGTERM during a slow fetch leaves no scratch directory; stale sweep keeps fresh and locked directories; no path/query tokens anywhere.
