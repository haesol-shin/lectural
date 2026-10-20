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
- A process killed with SIGKILL cannot remove its temp directory.
- A preflight 401/403 is treated as unauthorized even when a site blocks only non-browser clients.
