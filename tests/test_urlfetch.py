"""Public http(s) media URL sources: fetch, cleanup, and redaction (offline)."""

from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date

import pytest

from lectural import acquisition, cli, evidence, media, fetch, vad, visual
from lectural.fetch import assets, errors, scratch, ytdlp

MEDIA_BYTES = b"\x00\x00\x00\x18ftypmp42synthetic-lecture-media" * 64
AUDIO_BYTES = b"ID3synthetic-lecture-audio" * 64
PATH_TOKEN = "secretpathtoken"
QUERY_TOKEN = "querysigtoken"
VIDEO_PATH = f"/{PATH_TOKEN}/lecture.mp4?sig={QUERY_TOKEN}&expires=1"
TOKENS = (PATH_TOKEN, QUERY_TOKEN, "lecture.mp4", "sig=")


class _Handler(BaseHTTPRequestHandler):
    ftp_port = 21
    hits: dict = {}
    served: dict = {}
    release = threading.Event()

    def log_message(self, *_args):  # keep test output quiet
        pass

    def _html(self, video_src: str) -> None:
        body = (
            f"<html><head><title>{PATH_TOKEN}</title></head>"
            f'<body><video src="{video_src}"></video></body></html>'
        )
        self._send(200, body.encode(), "text/html")

    def _send(
        self, status: int, body: bytes = b"", content_type: str = "text/plain", headers: dict | None = None
    ):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == f"/{PATH_TOKEN}/lecture.mp4":
            self._send(200, MEDIA_BYTES, "video/mp4")
        elif path == f"/{PATH_TOKEN}/talk.mp3":
            self._send(200, AUDIO_BYTES, "audio/mpeg")
        elif path == f"/{PATH_TOKEN}/to-media":
            self._send(302, headers={"Location": VIDEO_PATH})
        elif path == f"/{PATH_TOKEN}/to-ftp":
            self._send(302, headers={"Location": f"ftp://127.0.0.1/{PATH_TOKEN}/x.mp4"})
        elif path == f"/{PATH_TOKEN}/to-file":
            self._send(302, headers={"Location": f"file:///{PATH_TOKEN}/x.mp4"})
        elif path == f"/{PATH_TOKEN}/to-data":
            self._send(301, headers={"Location": "data:video/mp4;base64,AAAA"})
        elif path == f"/{PATH_TOKEN}/private":
            self._send(401, b"login required", headers={"WWW-Authenticate": "Basic"})
        elif path == f"/{PATH_TOKEN}/forbidden":
            self._send(403, b"forbidden")
        elif path == f"/{PATH_TOKEN}/proxy-auth":
            self._send(407, b"proxy login", headers={"Proxy-Authenticate": "Basic"})
        elif path == f"/{PATH_TOKEN}/to-login":
            self._send(302, headers={"Location": f"/accounts/login/?next=/{PATH_TOKEN}"})
        elif path == "/accounts/login/":
            # A login wall that embeds an unrelated public video.
            self._send(
                200,
                (
                    f'<html><body><form>sign in</form><video src="/{PATH_TOKEN}/intro.mp4">'
                    "</video></body></html>"
                ).encode(),
                "text/html",
            )
        elif path == f"/{PATH_TOKEN}/intro.mp4":
            self.hits[path] = self.hits.get(path, 0) + 1
            self._send(200, MEDIA_BYTES, "video/mp4")
        elif path in self.served:
            content_type, body = self.served[path]
            self._send(200, body, content_type)
        elif path == f"/{PATH_TOKEN}/slow.mp4":
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(MEDIA_BYTES) * 10))
            self.end_headers()
            self.wfile.write(MEDIA_BYTES)
            self.wfile.flush()
            self.release.wait(30)
        elif path == f"/{PATH_TOKEN}/live.m3u8":
            playlist = (
                f"#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\n/{PATH_TOKEN}/seg0.ts\n#EXT-X-ENDLIST\n"
            )
            self._send(200, playlist.encode(), "application/vnd.apple.mpegurl")
        elif path == f"/{PATH_TOKEN}/manifest-as-mp4":
            playlist = (
                f"#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\n/{PATH_TOKEN}/seg0.ts\n#EXT-X-ENDLIST\n"
            )
            self._send(200, playlist.encode(), "video/mp4")
        elif path == f"/{PATH_TOKEN}/seg0.ts":
            self.hits[path] = self.hits.get(path, 0) + 1
            self._send(200, b"\x47" * 188, "video/mp2t")
        elif path == f"/{PATH_TOKEN}/missing":
            self._send(404, b"missing")
        elif path == f"/{PATH_TOKEN}/truncated":
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(MEDIA_BYTES)))
            self.end_headers()
            self.wfile.write(MEDIA_BYTES[:32])
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
        elif path == f"/{PATH_TOKEN}/page":
            self._send(200, b"<html><body>player</body></html>", "text/html")
        elif path == f"/{PATH_TOKEN}/html5":
            self._html(f"lecture.mp4?sig={QUERY_TOKEN}")
        elif path == f"/{PATH_TOKEN}/page-to-ftp":
            # LecturAL's first request sees a page; yt-dlp's request is redirected.
            count = self.hits[path] = self.hits.get(path, 0) + 1
            if count == 1:
                self._html(f"lecture.mp4?sig={QUERY_TOKEN}")
            else:
                self._send(302, headers={"Location": f"ftp://127.0.0.1:{self.ftp_port}/{PATH_TOKEN}/x.mp4"})
        elif path == f"/{PATH_TOKEN}/html5-to-ftp":
            self._html(f"/{PATH_TOKEN}/media-to-ftp.mp4")
        elif path == f"/{PATH_TOKEN}/media-to-ftp.mp4":
            self._send(302, headers={"Location": f"ftp://127.0.0.1:{self.ftp_port}/{PATH_TOKEN}/x.mp4"})
        else:
            self._send(404)


@pytest.fixture()
def server():
    _Handler.hits = {}
    _Handler.served = {}
    _Handler.release = threading.Event()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    _Handler.release.set()
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture()
def temp_root(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "system-tmp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


@pytest.fixture()
def probe_by_suffix(monkeypatch):
    # ffprobe is not available offline; classify by the served content type.
    monkeypatch.setattr(assets, "probe", lambda path: path.endswith((".mp4", ".mkv", ".webm")))


def _closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}{VIDEO_PATH}"


def _install_fake_pipeline(monkeypatch, seen: dict, *, fail_speech: bool = False) -> None:
    def fake_acquire(source, out_dir, force_stt=False, model="medium"):
        seen["speech_source"] = source
        seen["audio_dir"] = out_dir
        if fail_speech:
            raise RuntimeError(f"speech failed for {source.locator}")
        audio = Path(out_dir) / "audio.wav"
        audio.write_bytes(b"audio")
        return acquisition.SpeechTrack(
            [
                acquisition.Segment(0.0, "First sentence", end=4.0),
                acquisition.Segment(5.0, "Second sentence", end=20.0),
            ],
            "stt",
            language="en",
            meta={
                "audio_path": str(audio),
                "duration": 20.0,
                "model": model,
                "fallback_code": "local_source",
            },
        )

    def fake_frames(video_path, frames_dir):
        seen["video_path"] = video_path
        seen["video_bytes"] = Path(video_path).read_bytes()
        root = Path(frames_dir)
        root.mkdir(parents=True, exist_ok=True)
        frames = []
        for index, stamp in enumerate((1.0, 10.0), start=1):
            path = root / f"frame_{index:05d}.png"
            path.write_bytes(f"frame-{index}".encode())
            frames.append(visual.Frame(stamp, str(path), meta={"width": 640, "height": 360}))
        return frames

    monkeypatch.setattr(acquisition, "acquire_speech", fake_acquire)
    monkeypatch.setattr(vad, "detect_speech_spans", lambda _audio, length: [(0.0, length)])
    monkeypatch.setattr(media, "probe_video_resolution", lambda _path: (640, 360))
    monkeypatch.setattr(visual, "extract_candidate_frames", fake_frames)
    monkeypatch.setattr(visual, "dedupe_frames", lambda frames: list(frames))

    def fake_ocr(frames):
        for index, frame in enumerate(frames, start=1):
            frame.ocr_text = f"Slide title {index} contains enough text"
            frame.ocr_confidence = 0.99
            frame.is_slide = True
        return frames, "paddleocr"

    monkeypatch.setattr("lectural.ocr.ocr_frames", fake_ocr)


def _run_cli(argv: list[str], capsys) -> tuple[int, str, str]:
    stream = StringIO()
    with redirect_stdout(stream):
        exit_code = cli.main(argv)
    captured = capsys.readouterr()
    return exit_code, stream.getvalue() + captured.out, captured.err


def _tree_text(root: Path) -> str:
    chunks = []
    for path in sorted(root.rglob("*")):
        chunks.append(str(path))
        if path.is_file():
            chunks.append(path.read_bytes().decode("utf-8", errors="replace"))
    return "\n".join(chunks)


def _assert_no_tokens(*texts: str) -> None:
    for text in texts:
        for token in TOKENS:
            assert token not in text


def _comparable(manifest: dict) -> dict:
    data = json.loads(json.dumps(manifest))
    data.pop("generated_at")
    data.pop("resources")
    data["source"].pop("argument")
    data["artifacts"] = sorted(data["artifacts"])
    for frame in data["frames"]:
        frame.pop("path")
    return data


def test_url_fixture_produces_local_file_evidence_shape_and_leaves_no_media(
    server,
    temp_root,
    probe_by_suffix,
    monkeypatch,
    tmp_path,
    capsys,
):
    seen: dict = {}
    _install_fake_pipeline(monkeypatch, seen)
    local_file = tmp_path / "lecture.mp4"
    local_file.write_bytes(MEDIA_BYTES)
    local_code, local_out, _ = _run_cli(
        ["extract", str(local_file), "--out", str(tmp_path / "local"), "--json"], capsys
    )
    url_out_dir = tmp_path / "remote"
    url_code, url_out, url_err = _run_cli(
        ["extract", server + VIDEO_PATH, "--out", str(url_out_dir), "--json"], capsys
    )

    assert local_code == url_code == 0
    local_manifest = json.loads(local_out)["result"]
    url_manifest = json.loads(url_out)["result"]
    local_comparable, url_comparable = _comparable(local_manifest), _comparable(url_manifest)
    local_comparable["source"]["title"] = url_comparable["source"]["title"] = "title"
    assert url_comparable == local_comparable
    assert url_manifest["source"]["kind"] == "local_video"
    assert url_manifest["source"]["id"] == "sha256:" + hashlib.sha256(MEDIA_BYTES).hexdigest()
    assert url_manifest["source"]["argument"] == "http://127.0.0.1"
    assert url_manifest["source"]["title"] == "127.0.0.1"
    assert url_manifest["speech"]["source"] == "stt"
    assert url_manifest["source"]["citation"] == {"kind": "transcript"}

    # Media was fetched into the private temp dir, and derived audio stayed there too.
    assert seen["video_bytes"] == MEDIA_BYTES
    assert Path(seen["video_path"]).parent == Path(seen["audio_dir"])
    assert Path(seen["audio_dir"]).parent == temp_root
    assert list(temp_root.iterdir()) == []
    assert not (url_out_dir / "audio.wav").exists()
    _assert_no_tokens(url_out, url_err, _tree_text(url_out_dir))


def test_audio_url_becomes_local_audio_evidence(
    server, temp_root, probe_by_suffix, monkeypatch, tmp_path, capsys
):
    seen: dict = {}
    _install_fake_pipeline(monkeypatch, seen)
    out_dir = tmp_path / "audio-bundle"
    code, out, err = _run_cli(
        ["extract", f"{server}/{PATH_TOKEN}/talk.mp3?sig={QUERY_TOKEN}", "--out", str(out_dir), "--json"],
        capsys,
    )
    manifest = json.loads(out)["result"]
    assert code == 0
    assert manifest["source"]["kind"] == "local_audio"
    assert manifest["source"]["has_video"] is False
    assert manifest["frames"] == []
    assert list(temp_root.iterdir()) == []
    _assert_no_tokens(out, err, _tree_text(out_dir))


def test_redirect_to_http_media_is_followed(
    server, temp_root, probe_by_suffix, monkeypatch, tmp_path, capsys
):
    seen: dict = {}
    _install_fake_pipeline(monkeypatch, seen)
    code, out, _ = _run_cli(
        ["extract", f"{server}/{PATH_TOKEN}/to-media", "--out", str(tmp_path / "b"), "--json"], capsys
    )
    assert code == 0
    assert seen["video_bytes"] == MEDIA_BYTES
    assert json.loads(out)["result"]["source"]["argument"] == "http://127.0.0.1"


def test_failed_extraction_still_removes_fetched_media(
    server, temp_root, probe_by_suffix, monkeypatch, tmp_path, capsys
):
    seen: dict = {}
    _install_fake_pipeline(monkeypatch, seen, fail_speech=True)
    out_dir = tmp_path / "failed"
    code, out, err = _run_cli(["extract", server + VIDEO_PATH, "--out", str(out_dir), "--json"], capsys)
    payload = json.loads(out)
    assert code == 1
    assert payload["errors"][0]["code"] == "EXTRACTION_FAILED"
    assert payload["result"]["source"] is None
    assert Path(seen["speech_source"].locator).parent.parent == temp_root
    assert list(temp_root.iterdir()) == []
    _assert_no_tokens(out, err, _tree_text(out_dir))


@pytest.mark.parametrize(
    ("suffix", "code"),
    [
        (f"/{PATH_TOKEN}/to-ftp", "SOURCE_REDIRECT_REJECTED"),
        (f"/{PATH_TOKEN}/to-file", "SOURCE_REDIRECT_REJECTED"),
        (f"/{PATH_TOKEN}/to-data", "SOURCE_REDIRECT_REJECTED"),
        (f"/{PATH_TOKEN}/private?sig={QUERY_TOKEN}", "SOURCE_LOGIN_REQUIRED"),
        (f"/{PATH_TOKEN}/proxy-auth", "SOURCE_LOGIN_REQUIRED"),
        (f"/{PATH_TOKEN}/to-login?sig={QUERY_TOKEN}", "SOURCE_LOGIN_REQUIRED"),
        (f"/{PATH_TOKEN}/forbidden?sig={QUERY_TOKEN}", "SOURCE_ACCESS_DENIED"),
        (f"/{PATH_TOKEN}/missing", "SOURCE_UNAVAILABLE"),
        (f"/{PATH_TOKEN}/truncated", "SOURCE_UNAVAILABLE"),
    ],
)
def test_remote_failures_are_bounded_and_leave_nothing(
    server,
    temp_root,
    probe_by_suffix,
    monkeypatch,
    tmp_path,
    capsys,
    suffix,
    code,
):
    # Page resolution (the 403 and login-wall retry) finds no media.
    factory, _calls = _fake_youtube_dl(RuntimeError(f"ERROR: Unsupported URL: {server}{suffix}"))
    monkeypatch.setattr(ytdlp, "http_only_ytdlp", factory)
    monkeypatch.setattr(errors, "ytdlp_outdated", lambda: False)
    out_dir = tmp_path / "bundle"
    exit_code, out, err = _run_cli(["extract", server + suffix, "--out", str(out_dir), "--json"], capsys)
    payload = json.loads(out)
    assert exit_code == 2
    assert payload["status"] == "error"
    assert [error["code"] for error in payload["errors"]] == [code]
    assert payload["errors"][0]["message"] == evidence.failure(code)["message"]
    assert payload["result"]["source"] is None
    assert payload["result"]["artifacts"]["output_dir"] is None
    assert not out_dir.exists()
    assert list(temp_root.iterdir()) == []
    _assert_no_tokens(out, err)


@pytest.mark.parametrize(
    ("ytdlp_result", "code"),
    [
        (
            RuntimeError(
                "ERROR: [Site] abc: This content is only available for registered users. Use --cookies"
            ),
            "SOURCE_LOGIN_REQUIRED",
        ),
        (RuntimeError("ERROR: [Site] abc: This video is private"), "SOURCE_ACCESS_DENIED"),
        (RuntimeError("ERROR: [Site] abc: Unable to extract video data"), "SOURCE_ACCESS_DENIED"),
    ],
)
def test_direct_403_is_decided_after_one_page_resolution(server, temp_root, monkeypatch, ytdlp_result, code):
    factory, calls = _fake_youtube_dl(ytdlp_result)
    monkeypatch.setattr(ytdlp, "http_only_ytdlp", factory)
    with pytest.raises(errors.RemoteSourceError) as excinfo:
        with fetch.prepare_source(f"{server}/{PATH_TOKEN}/forbidden?sig={QUERY_TOKEN}"):
            pass
    assert excinfo.value.code == code
    assert len(calls) == 1
    _assert_no_tokens(str(excinfo.value))
    assert list(temp_root.iterdir()) == []


def test_direct_403_is_fetched_when_page_resolution_finds_public_media(
    server, temp_root, probe_by_suffix, monkeypatch
):
    factory, calls = _fake_youtube_dl({"url": server + VIDEO_PATH, "protocol": "http", "ext": "mp4"})
    monkeypatch.setattr(ytdlp, "http_only_ytdlp", factory)
    with fetch.prepare_source(f"{server}/{PATH_TOKEN}/forbidden") as ready:
        assert Path(ready.source.locator).read_bytes() == MEDIA_BYTES
        assert ready.source.kind.value == "local_video"
    assert len(calls) == 1
    assert list(temp_root.iterdir()) == []


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (RuntimeError("ERROR: Sign in to confirm your age"), "SOURCE_LOGIN_REQUIRED"),
        (RuntimeError("ERROR: HTTP Error 401: Unauthorized"), "SOURCE_LOGIN_REQUIRED"),
        (RuntimeError("ERROR: HTTP Error 403: Forbidden"), "SOURCE_ACCESS_DENIED"),
        (RuntimeError("ERROR: Requested format is not available"), "SOURCE_UNAVAILABLE"),
        (RuntimeError("ERROR: HTTP Error 404: Not Found"), "SOURCE_UNAVAILABLE"),
        (
            RuntimeError("ERROR: Unsupported URL: https://media.example.invalid/private/login?cookies=1"),
            "SOURCE_UNAVAILABLE",
        ),
    ],
)
def test_ytdlp_errors_map_to_the_three_classes(error, code):
    assert errors.classify_ytdlp_error(error) == code


def test_ytdlp_http_status_in_the_error_chain_wins_over_text():
    class StatusError(Exception):
        status = 403

    class ExtractorError(Exception):
        def __init__(self):
            super().__init__("Unable to download webpage")
            self.cause = StatusError()

    class DownloadError(Exception):
        def __init__(self):
            super().__init__("ERROR: Unable to download webpage (caused by sign in page)")
            self.exc_info = (ExtractorError, ExtractorError(), None)

    assert errors.classify_ytdlp_error(DownloadError()) == "SOURCE_ACCESS_DENIED"


def test_outdated_ytdlp_adds_a_bounded_update_hint(server, temp_root, monkeypatch, tmp_path, capsys):
    assert errors.ytdlp_outdated("2026.06.09", today=date(2026, 10, 20)) is True
    assert errors.ytdlp_outdated("2026.08.19", today=date(2026, 10, 20)) is False
    assert errors.ytdlp_outdated("2026.10.10.233141", today=date(2026, 10, 20)) is False
    assert errors.ytdlp_outdated("not-a-version", today=date(2026, 10, 20)) is False

    monkeypatch.setattr(errors, "ytdlp_outdated", lambda: True)
    messages = {}
    for name, suffix in (("login", "private"), ("missing", "missing")):
        code, out, err = _run_cli(
            [
                "extract",
                f"{server}/{PATH_TOKEN}/{suffix}?sig={QUERY_TOKEN}",
                "--out",
                str(tmp_path / name),
                "--json",
            ],
            capsys,
        )
        assert code == 2
        payload = json.loads(out)
        messages[name] = payload["errors"][0]["message"]
        assert payload["result"]["failure"]["message"] == messages[name]
        _assert_no_tokens(out, err)
    assert (
        messages["login"]
        == f"{evidence.failure('SOURCE_LOGIN_REQUIRED')['message']} {errors.YTDLP_UPDATE_HINT}"
    )
    assert messages["missing"] == evidence.failure("SOURCE_UNAVAILABLE")["message"]


def test_unreachable_url_is_bounded(temp_root, tmp_path, capsys):
    exit_code, out, err = _run_cli(
        ["extract", _closed_port_url(), "--out", str(tmp_path / "b"), "--json"], capsys
    )
    assert exit_code == 2
    assert json.loads(out)["errors"][0]["code"] == "SOURCE_UNAVAILABLE"
    assert list(temp_root.iterdir()) == []
    _assert_no_tokens(out, err)


@pytest.mark.parametrize(
    "value",
    [
        f"file:///{PATH_TOKEN}/lecture.mp4",
        f"ftp://127.0.0.1/{PATH_TOKEN}/lecture.mp4?sig={QUERY_TOKEN}",
        f"data:video/mp4;base64,{PATH_TOKEN}",
    ],
)
def test_non_http_sources_are_rejected_before_output_creation(tmp_path, capsys, value):
    out_dir = tmp_path / "bundle"
    exit_code, out, err = _run_cli(["extract", value, "--out", str(out_dir), "--json"], capsys)
    assert exit_code == 2
    assert json.loads(out)["errors"][0]["code"] == "SOURCE_INVALID"
    assert not out_dir.exists()
    _assert_no_tokens(out, err)


def test_notes_run_redacts_url_in_run_state_and_output(
    server, temp_root, probe_by_suffix, monkeypatch, tmp_path, capsys
):
    seen: dict = {}
    _install_fake_pipeline(monkeypatch, seen)
    factory, _calls = _fake_youtube_dl(RuntimeError(f"ERROR: [Site] {PATH_TOKEN}: This video is private"))
    monkeypatch.setattr(ytdlp, "http_only_ytdlp", factory)
    runstate_path = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(runstate_path))
    out_root = tmp_path / "notes-out"
    failing = f"{server}/{PATH_TOKEN}/forbidden?sig={QUERY_TOKEN}"
    exit_code, out, err = _run_cli(["notes", server + VIDEO_PATH, failing, "--out", str(out_root)], capsys)

    state = json.loads(runstate_path.read_text(encoding="utf-8"))
    assert exit_code == 2  # the second (access-denied) input fails
    assert [run["status"] for run in state["runs"]] == ["complete", "failed"]
    assert [run["source"] for run in state["runs"]] == ["http://127.0.0.1", "http://127.0.0.1"]
    assert "only public URLs are supported" in err
    bundle = Path(state["runs"][0]["output_dir"])
    assert (bundle / "notes.md").is_file()
    assert (
        json.loads((bundle / "synthesis_input.json").read_text(encoding="utf-8"))["video"]["input_source"][
            "argument"
        ]
        == "http://127.0.0.1"
    )
    assert list(temp_root.iterdir()) == []
    _assert_no_tokens(out, err, runstate_path.read_text(encoding="utf-8"), _tree_text(out_root))


def _fake_youtube_dl(result):
    """A stand-in for the HTTP-only YoutubeDL class (offline, no yt_dlp)."""
    calls: list = []

    class FakeYoutubeDL:
        def __init__(self, params):
            calls.append(params)

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def extract_info(self, url, download):
            assert download is False
            if isinstance(result, Exception):
                raise result
            return result

        def sanitize_info(self, info):
            return info

    return (lambda _rejected: FakeYoutubeDL), calls


def test_page_url_downloads_the_single_progressive_format_ytdlp_selects(
    server, temp_root, probe_by_suffix, monkeypatch
):
    info = {
        "extractor_key": "SomeSite",
        "title": f"Week 3 lecture {PATH_TOKEN}",
        "url": server + VIDEO_PATH,
        "protocol": "http",
        "ext": "mp4",
        "http_headers": {"User-Agent": "test-agent", "Cookie": "session=leak"},
    }
    factory, calls = _fake_youtube_dl(info)
    monkeypatch.setattr(ytdlp, "http_only_ytdlp", factory)
    page = f"{server}/{PATH_TOKEN}/page?sig={QUERY_TOKEN}"
    with fetch.prepare_source(page) as ready:
        assert Path(ready.source.locator).read_bytes() == MEDIA_BYTES
        # Extractor titles can quote the URL; a fetched source is titled by host.
        assert ready.source.title_hint == "127.0.0.1"
        assert ready.source.safe_as_dict()["argument"] == "http://127.0.0.1"
        scratch = ready.work_dir
    assert not os.path.exists(scratch)
    params = calls[0]
    assert params["noplaylist"] is True
    assert params["cookiefile"] is None and params["cookiesfrombrowser"] is None


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (
            RuntimeError(f"ERROR: [Site] {PATH_TOKEN}: This video is private. Use --cookies"),
            "SOURCE_LOGIN_REQUIRED",
        ),
        (RuntimeError(f"ERROR: Unsupported URL: https://x.invalid/{PATH_TOKEN}"), "SOURCE_UNAVAILABLE"),
        ({"url": "rtmp://cdn.invalid/live", "protocol": "rtmp"}, "SOURCE_UNAVAILABLE"),
        ({"url": "https://cdn.invalid/v.m3u8", "protocol": "m3u8_native"}, "SOURCE_UNAVAILABLE"),
        ({"url": "ftp://cdn.invalid/v.mp4", "protocol": "https"}, "SOURCE_UNAVAILABLE"),
        ({"_type": "playlist", "entries": []}, "SOURCE_UNAVAILABLE"),
        (
            {"requested_formats": [{"url": "https://cdn.invalid/v", "protocol": "https"}] * 3},
            "SOURCE_UNAVAILABLE",
        ),
        (
            {
                "requested_formats": [
                    {
                        "url": "https://cdn.invalid/v.m3u8",
                        "protocol": "m3u8_native",
                        "vcodec": "avc1",
                        "acodec": "none",
                    },
                    {
                        "url": "https://cdn.invalid/a.m4a",
                        "protocol": "https",
                        "vcodec": "none",
                        "acodec": "mp4a",
                    },
                ]
            },
            "SOURCE_UNAVAILABLE",
        ),
        (
            # Audio alone is refused when the page's video exists only as fragments.
            {
                "url": "https://cdn.invalid/a.m4a",
                "protocol": "https",
                "vcodec": "none",
                "acodec": "mp4a",
                "formats": [
                    {"url": "https://cdn.invalid/v.m3u8", "protocol": "m3u8_native", "vcodec": "avc1"}
                ],
            },
            "SOURCE_UNAVAILABLE",
        ),
    ],
)
def test_page_url_resolution_failures_are_bounded(server, temp_root, monkeypatch, result, code):
    factory, _calls = _fake_youtube_dl(result)
    monkeypatch.setattr(ytdlp, "http_only_ytdlp", factory)
    with pytest.raises(errors.RemoteSourceError) as excinfo:
        with fetch.prepare_source(f"{server}/{PATH_TOKEN}/page"):
            pass
    assert excinfo.value.code == code
    assert excinfo.value.__cause__ is None
    _assert_no_tokens(str(excinfo.value))
    assert list(temp_root.iterdir()) == []


@pytest.fixture()
def ftp_listener():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        sock.settimeout(0.5)
        _Handler.ftp_port = sock.getsockname()[1]
        yield sock


def _connection_attempted(sock: socket.socket) -> bool:
    try:
        conn, _addr = sock.accept()
    except (socket.timeout, TimeoutError):
        return False
    conn.close()
    return True


@pytest.mark.url_runtime
@pytest.mark.url_ytdlp
def test_real_ytdlp_resolves_html5_page_through_checked_download(server, temp_root, probe_by_suffix, capfd):
    pytest.importorskip("yt_dlp")
    with fetch.prepare_source(f"{server}/{PATH_TOKEN}/html5?ref={QUERY_TOKEN}") as ready:
        assert Path(ready.source.locator).read_bytes() == MEDIA_BYTES
        assert ready.source.title_hint == "127.0.0.1"
    assert list(temp_root.iterdir()) == []
    captured = capfd.readouterr()
    _assert_no_tokens(captured.out, captured.err)


def test_ytdlp_without_request_director_hook_fails_closed(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = type("YoutubeDL", (), {})
    networking = types.ModuleType("yt_dlp.networking")
    urllib_module = types.ModuleType("yt_dlp.networking._urllib")
    urllib_module.UrllibRH = type("UrllibRH", (), {})
    for name, module in (
        ("yt_dlp", fake),
        ("yt_dlp.networking", networking),
        ("yt_dlp.networking._urllib", urllib_module),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    with pytest.raises(errors.DependencyError):
        ytdlp.http_only_ytdlp([])


def test_invalid_url_like_inputs_never_reach_run_state_or_stderr(tmp_path, monkeypatch, capsys):
    runstate_path = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(runstate_path))
    inputs = [
        f"media.example.invalid/{PATH_TOKEN}/lecture.mp4",
        f"x:{PATH_TOKEN}",
        f"ftp://media.example.invalid/{PATH_TOKEN}?sig={QUERY_TOKEN}",
    ]
    exit_code, out, err = _run_cli(["notes", *inputs, "--out", str(tmp_path / "out")], capsys)
    assert exit_code == 2
    state = runstate_path.read_text(encoding="utf-8")
    assert [run["status"] for run in json.loads(state)["runs"]] == ["failed"] * 3
    _assert_no_tokens(out, err, state)


@pytest.mark.parametrize(
    "argv",
    [
        [f"https://media.example.invalid/{PATH_TOKEN}?sig={QUERY_TOKEN}"],
        [f"ftp://media.example.invalid/{PATH_TOKEN}?sig={QUERY_TOKEN}"],
        [
            "extract",
            "https://a.example.invalid/x",
            f"https://b.example.invalid/{PATH_TOKEN}?sig={QUERY_TOKEN}",
            "--out",
            "x",
        ],
        [
            "extract",
            "https://a.example.invalid",
            "--out",
            "x",
            f"--skip-ocr=https://b.example.invalid/{PATH_TOKEN}?sig={QUERY_TOKEN}",
        ],
        [
            "notes",
            "https://a.example.invalid",
            f"--keep-frames=https://b.example.invalid/{PATH_TOKEN}?sig={QUERY_TOKEN}",
        ],
        ["verify", "bundle", "--json", f"https://b.example.invalid/{PATH_TOKEN}?sig={QUERY_TOKEN}"],
        ["inspect", f"--bogus=https://b.example.invalid/{PATH_TOKEN}?sig={QUERY_TOKEN}", "bundle"],
        ["extract", f"https://b.example.invalid/{PATH_TOKEN}?sig={QUERY_TOKEN}"],
        [
            "extract",
            "https://a.example.invalid",
            "--out",
            "x",
            f"--skip-ocr=https://b.example.invalid/{PATH_TOKEN}/a'b\"c?sig={QUERY_TOKEN}",
        ],
    ],
)
def test_parser_errors_do_not_echo_url_tokens(capsys, argv):
    with pytest.raises(SystemExit):
        cli.main(argv)
    captured = capsys.readouterr()
    assert "error:" in captured.err
    _assert_no_tokens(captured.out, captured.err)


@pytest.mark.parametrize("route", ["page-to-ftp", "html5-to-ftp"])
@pytest.mark.url_runtime
@pytest.mark.url_ytdlp
def test_real_ytdlp_never_follows_a_redirect_to_ftp(
    server, temp_root, probe_by_suffix, ftp_listener, capsys, route
):
    pytest.importorskip("yt_dlp")
    with pytest.raises(errors.RemoteSourceError) as excinfo:
        with fetch.prepare_source(f"{server}/{PATH_TOKEN}/{route}"):
            pass
    assert excinfo.value.code == "SOURCE_REDIRECT_REJECTED"
    assert not _connection_attempted(ftp_listener)
    assert list(temp_root.iterdir()) == []
    captured = capsys.readouterr()
    _assert_no_tokens(captured.out, captured.err)


def _split_page(server: str, video: tuple[str, bytes], audio: tuple[str, bytes]) -> dict:
    """Serve a video-only and an audio-only stream and describe them like yt-dlp."""
    _Handler.served = {
        f"/{PATH_TOKEN}/dash-v": video,
        f"/{PATH_TOKEN}/dash-a": audio,
    }
    return {
        "requested_formats": [
            {
                "url": f"{server}/{PATH_TOKEN}/dash-v?sig={QUERY_TOKEN}",
                "protocol": "https" if server.startswith("https") else "http",
                "ext": "webm",
                "vcodec": "vp09",
                "acodec": "none",
                "http_headers": {"Cookie": "session=leak"},
            },
            {
                "url": f"{server}/{PATH_TOKEN}/dash-a?sig={QUERY_TOKEN}",
                "protocol": "http",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
            },
        ],
    }


def _url_and_local_evidence(
    server, monkeypatch, tmp_path, capsys, merged_suffix: str
) -> tuple[dict, dict, dict]:
    seen: dict = {}
    _install_fake_pipeline(monkeypatch, seen)
    url_code, url_out, url_err = _run_cli(
        [
            "extract",
            f"{server}/{PATH_TOKEN}/page?sig={QUERY_TOKEN}",
            "--out",
            str(tmp_path / "remote"),
            "--json",
        ],
        capsys,
    )
    assert url_code == 0, url_out
    remote_seen = dict(seen)
    local_file = tmp_path / f"lecture{merged_suffix}"
    local_file.write_bytes(seen["video_bytes"])
    local_code, local_out, _ = _run_cli(
        ["extract", str(local_file), "--out", str(tmp_path / "local"), "--json"], capsys
    )
    assert local_code == 0
    _assert_no_tokens(url_out, url_err, _tree_text(tmp_path / "remote"))
    return json.loads(url_out)["result"], json.loads(local_out)["result"], remote_seen


def test_split_video_and_audio_streams_merge_into_local_file_evidence(
    server, temp_root, monkeypatch, tmp_path, capsys
):
    info = _split_page(server, ("video/webm", b"VIDEO-ONLY" * 50), ("audio/mp4", b"AUDIO-ONLY" * 50))
    factory, _calls = _fake_youtube_dl(info)
    monkeypatch.setattr(ytdlp, "http_only_ytdlp", factory)
    probed: list[str] = []

    def fake_probe(path):
        probed.append(Path(path).name)
        return "stream0" in path or path.endswith(".mkv")

    def fake_merge(video_path, audio_path, dest_dir):
        merged = Path(dest_dir) / "media.mkv"
        merged.write_bytes(Path(video_path).read_bytes() + Path(audio_path).read_bytes())
        os.remove(video_path)
        os.remove(audio_path)
        return str(merged)

    monkeypatch.setattr(assets, "probe", fake_probe)
    monkeypatch.setattr(assets, "merge", fake_merge)
    url_manifest, local_manifest, seen = _url_and_local_evidence(
        server, monkeypatch, tmp_path, capsys, ".mkv"
    )

    assert seen["video_bytes"] == b"VIDEO-ONLY" * 50 + b"AUDIO-ONLY" * 50
    assert probed == ["stream0.webm", "stream1.m4a"]
    assert Path(seen["video_path"]).parent.parent == temp_root
    local_comparable, url_comparable = _comparable(local_manifest), _comparable(url_manifest)
    local_comparable["source"]["title"] = url_comparable["source"]["title"] = "title"
    assert url_comparable == local_comparable
    assert url_manifest["source"]["kind"] == "local_video"
    assert url_manifest["source"]["argument"] == "http://127.0.0.1"
    assert list(temp_root.iterdir()) == []


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="needs ffmpeg")
@pytest.mark.url_runtime
def test_real_ffmpeg_merges_split_streams_locally(server, temp_root, monkeypatch, tmp_path, capsys):
    sources = tmp_path / "sources"
    sources.mkdir()
    video, audio = sources / "v.webm", sources / "a.m4a"
    for args in (
        ["-f", "lavfi", "-i", "testsrc=size=64x64:rate=5", "-t", "1", "-c:v", "libvpx-vp9", str(video)],
        ["-f", "lavfi", "-i", "sine=d=1", "-c:a", "aac", str(audio)],
    ):
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", *args], check=True)
    info = _split_page(server, ("video/webm", video.read_bytes()), ("audio/mp4", audio.read_bytes()))
    factory, _calls = _fake_youtube_dl(info)
    monkeypatch.setattr(ytdlp, "http_only_ytdlp", factory)
    url_manifest, local_manifest, seen = _url_and_local_evidence(
        server, monkeypatch, tmp_path, capsys, ".mkv"
    )

    streams = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(tmp_path / "lecture.mkv"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert sorted(streams) == ["audio", "video"]
    assert Path(seen["video_path"]).name == "media.mkv"
    local_comparable, url_comparable = _comparable(local_manifest), _comparable(url_manifest)
    local_comparable["source"]["title"] = url_comparable["source"]["title"] = "title"
    assert url_comparable == local_comparable
    assert url_manifest["source"]["has_video"] is True
    assert list(temp_root.iterdir()) == []


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="needs ffprobe")
@pytest.mark.url_runtime
def test_manifest_served_as_media_is_rejected_without_fetching_segments(server, temp_root, capsys):
    with pytest.raises(errors.RemoteSourceError) as excinfo:
        with fetch.prepare_source(f"{server}/{PATH_TOKEN}/manifest-as-mp4?sig={QUERY_TOKEN}"):
            pass
    assert excinfo.value.code == "SOURCE_UNAVAILABLE"
    assert _Handler.hits.get(f"/{PATH_TOKEN}/seg0.ts") is None
    assert list(temp_root.iterdir()) == []


def _real_selection(formats: list[dict]) -> list[str]:
    """Run real yt-dlp format selection with LecturAL's selector (no network)."""
    youtube_dl = ytdlp.http_only_ytdlp([])
    params = {"quiet": True, "logger": ytdlp.SilentLogger(), "format": ytdlp.FORMAT_SELECTOR}
    info = {
        "id": "x",
        "title": "t",
        "formats": formats,
        "extractor": "generic",
        "extractor_key": "Generic",
        "webpage_url": "https://media.example.invalid/",
    }
    with youtube_dl(params) as ydl:
        result = ydl.process_ie_result(info, download=False)
    return [fmt["format_id"] for fmt in result.get("requested_formats") or [result]]


_AUDIO = {
    "format_id": "dash-a",
    "url": "https://cdn.invalid/a.m4a",
    "ext": "m4a",
    "vcodec": "none",
    "acodec": "mp4a.40.2",
    "protocol": "https",
}
_VIDEO = {
    "format_id": "dash-v",
    "url": "https://cdn.invalid/v.mp4",
    "ext": "mp4",
    "vcodec": "vp09",
    "acodec": "none",
    "protocol": "https",
    "height": 1920,
}
_PROGRESSIVE = {
    "format_id": "mp4",
    "url": "https://cdn.invalid/p.mp4",
    "ext": "mp4",
    "protocol": "https",
    "height": 1136,
}
_HLS = {
    "format_id": "hls",
    "url": "https://cdn.invalid/p.m3u8",
    "ext": "mp4",
    "vcodec": "avc1",
    "acodec": "mp4a",
    "protocol": "m3u8_native",
    "height": 2160,
}
_DASH = {
    "format_id": "dash-seg",
    "url": "https://cdn.invalid/m.mpd",
    "ext": "mp4",
    "vcodec": "avc1",
    "acodec": "none",
    "protocol": "http_dash_segments",
    "height": 2160,
}


@pytest.mark.parametrize(
    ("formats", "expected"),
    [
        ([_AUDIO, _PROGRESSIVE, _VIDEO], ["mp4"]),
        ([_AUDIO, _VIDEO], ["dash-v", "dash-a"]),
        ([_AUDIO, _VIDEO, _HLS, _DASH], ["dash-v", "dash-a"]),
        ([_AUDIO], ["dash-a"]),
    ],
)
@pytest.mark.url_runtime
@pytest.mark.url_ytdlp
def test_real_ytdlp_prefers_progressive_then_http_split_pair(formats, expected):
    pytest.importorskip("yt_dlp")
    assert _real_selection([dict(fmt) for fmt in formats]) == expected


@pytest.mark.url_runtime
@pytest.mark.url_ytdlp
def test_real_ytdlp_selects_nothing_from_fragment_protocols_only():
    pytest.importorskip("yt_dlp")
    with pytest.raises(Exception) as excinfo:
        _real_selection([dict(_HLS), dict(_DASH)])
    assert errors.classify_ytdlp_error(excinfo.value) == "SOURCE_UNAVAILABLE"


@pytest.mark.url_runtime
@pytest.mark.url_ytdlp
def test_real_ytdlp_hls_page_fails_bounded_without_fetching_segments(server, temp_root, capfd):
    pytest.importorskip("yt_dlp")
    with pytest.raises(errors.RemoteSourceError) as excinfo:
        with fetch.prepare_source(f"{server}/{PATH_TOKEN}/live.m3u8?sig={QUERY_TOKEN}"):
            pass
    assert excinfo.value.code == "SOURCE_UNAVAILABLE"
    assert _Handler.hits.get(f"/{PATH_TOKEN}/seg0.ts") is None
    assert list(temp_root.iterdir()) == []
    captured = capfd.readouterr()
    _assert_no_tokens(captured.out, captured.err, str(excinfo.value))


@pytest.mark.parametrize(
    ("route", "code"), [("forbidden", "SOURCE_ACCESS_DENIED"), ("private", "SOURCE_LOGIN_REQUIRED")]
)
@pytest.mark.url_runtime
@pytest.mark.url_ytdlp
def test_real_ytdlp_classifies_http_auth_failures(server, temp_root, monkeypatch, capfd, route, code):
    pytest.importorskip("yt_dlp")
    monkeypatch.setattr(errors, "ytdlp_outdated", lambda: False)
    with pytest.raises(errors.RemoteSourceError) as excinfo:
        with fetch.prepare_source(f"{server}/{PATH_TOKEN}/{route}?sig={QUERY_TOKEN}"):
            pass
    assert excinfo.value.code == code
    assert list(temp_root.iterdir()) == []
    captured = capfd.readouterr()
    _assert_no_tokens(captured.out, captured.err, str(excinfo.value))


def test_keyboard_interrupt_during_fetch_removes_media(temp_root, monkeypatch):
    def interrupted_fetch(_url, dest_dir):
        (Path(dest_dir) / "media.mp4").write_bytes(MEDIA_BYTES)
        raise KeyboardInterrupt

    monkeypatch.setattr(fetch, "fetch_url", interrupted_fetch)
    with pytest.raises(KeyboardInterrupt):
        with fetch.prepare_source(f"https://media.example.invalid/{PATH_TOKEN}"):
            pass
    assert list(temp_root.iterdir()) == []


@pytest.mark.skipif(not hasattr(signal, "SIGTERM") or os.name != "posix", reason="POSIX signals")
@pytest.mark.url_runtime
def test_sigterm_during_fetch_leaves_no_media(server, tmp_path):
    temp_root = tmp_path / "child-tmp"
    temp_root.mkdir()
    out_dir = tmp_path / "bundle"
    url = f"{server}/{PATH_TOKEN}/slow.mp4?sig={QUERY_TOKEN}"
    code = (
        "import sys; from lectural import cli; "
        f"sys.exit(cli.main(['extract', {url!r}, '--out', {str(out_dir)!r}, '--json']))"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        env={**os.environ, "TMPDIR": str(temp_root)},
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 30
        # The media file exists once the download has started (its bytes may still be buffered).
        while not list(temp_root.glob("lectural-fetch-*/media*")):
            assert proc.poll() is None, proc.communicate()
            assert time.monotonic() < deadline, "fetch never started"
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 128 + signal.SIGTERM
    assert list(temp_root.glob("lectural-fetch-*")) == []
    _assert_no_tokens(out.decode(), err.decode())


@pytest.mark.skipif(scratch.fcntl is None, reason="POSIX advisory locks")
@pytest.mark.url_runtime
def test_stale_scratch_sweep_removes_only_old_unlocked_own_dirs(tmp_path):
    import fcntl

    root = tmp_path / "tmp"
    root.mkdir()
    old = time.time() - 2 * 60 * 60

    def make_scratch(name: str, *, age: float | None = old) -> Path:
        path = root / name
        path.mkdir()
        (path / "media.mp4").write_bytes(MEDIA_BYTES)
        if age is not None:
            os.utime(path, (age, age))
        return path

    stale = make_scratch("lectural-fetch-stale")
    fresh = make_scratch("lectural-fetch-fresh", age=None)
    live = make_scratch("lectural-fetch-live")
    other = make_scratch("unrelated-old")
    target = make_scratch("symlink-target")
    link = root / "lectural-fetch-link"
    link.symlink_to(target)
    os.utime(link, (old, old), follow_symlinks=False)
    live_fd = os.open(live, os.O_RDONLY)
    fcntl.flock(live_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        removed = scratch.sweep_stale_scratch(str(root))
    finally:
        os.close(live_fd)
    assert removed == [str(stale)]
    assert not stale.exists()
    for kept in (fresh, live, other, target):
        assert (kept / "media.mp4").is_file()
    assert link.is_symlink()


def test_materialize_sweeps_stale_scratch_before_fetching(temp_root, monkeypatch):
    stale = temp_root / "lectural-fetch-killed"
    stale.mkdir()
    (stale / "media.webm").write_bytes(MEDIA_BYTES)
    old = time.time() - 2 * 60 * 60
    os.utime(stale, (old, old))

    def fake_fetch(_url, dest_dir):
        path = Path(dest_dir) / "media.mp3"
        path.write_bytes(AUDIO_BYTES)
        return assets.FetchedMedia(str(path), has_video=False)

    monkeypatch.setattr(fetch, "fetch_url", fake_fetch)
    with fetch.prepare_source(f"https://media.example.invalid/{PATH_TOKEN}") as ready:
        expected = [Path(ready.work_dir).name] + ([] if scratch.fcntl else [stale.name])
        assert sorted(path.name for path in temp_root.iterdir()) == sorted(expected)
    assert list(temp_root.iterdir()) == ([] if scratch.fcntl else [stale])


def test_login_wall_redirect_still_accepts_media_a_site_extractor_resolves(
    server, temp_root, probe_by_suffix, monkeypatch
):
    factory, calls = _fake_youtube_dl({"url": server + VIDEO_PATH, "protocol": "http", "ext": "mp4"})
    monkeypatch.setattr(ytdlp, "http_only_ytdlp", factory)
    with fetch.prepare_source(f"{server}/{PATH_TOKEN}/to-login?sig={QUERY_TOKEN}") as ready:
        assert Path(ready.source.locator).read_bytes() == MEDIA_BYTES
    assert len(calls) == 1
    assert list(temp_root.iterdir()) == []


@pytest.mark.url_runtime
@pytest.mark.url_ytdlp
def test_real_ytdlp_without_generic_refuses_delegation_to_generic(server, temp_root):
    pytest.importorskip("yt_dlp")
    # A site extractor's fallback is url_result(url, "Generic"), i.e. extract_info(ie_key="Generic").
    youtube_dl = ytdlp.http_only_ytdlp([])
    page = f"{server}/accounts/login/"
    with youtube_dl(
        {"quiet": True, "logger": ytdlp.SilentLogger(), "allowed_extractors": ["default", "-generic"]}
    ) as ydl:
        with pytest.raises(Exception, match="No suitable extractor"):
            ydl.extract_info(page, download=False, ie_key="Generic")
    with youtube_dl({"quiet": True, "logger": ytdlp.SilentLogger()}) as ydl:
        assert ydl.extract_info(page, download=False, ie_key="Generic")
    assert _Handler.hits.get(f"/{PATH_TOKEN}/intro.mp4") is None


@pytest.mark.parametrize(
    "ytdlp_error", ["ERROR: [Site] abc: This video is private", "ERROR: Unsupported URL"]
)
def test_login_wall_redirect_stays_login_required_when_resolution_fails(
    server, temp_root, monkeypatch, ytdlp_error
):
    factory, _calls = _fake_youtube_dl(RuntimeError(ytdlp_error))
    monkeypatch.setattr(ytdlp, "http_only_ytdlp", factory)
    with pytest.raises(errors.RemoteSourceError) as excinfo:
        with fetch.prepare_source(f"{server}/{PATH_TOKEN}/to-login"):
            pass
    assert excinfo.value.code == "SOURCE_LOGIN_REQUIRED"


@pytest.mark.url_runtime
@pytest.mark.url_ytdlp
def test_real_ytdlp_never_fetches_video_embedded_in_a_login_wall(server, temp_root, probe_by_suffix, capfd):
    pytest.importorskip("yt_dlp")
    with pytest.raises(errors.RemoteSourceError) as excinfo:
        with fetch.prepare_source(f"{server}/{PATH_TOKEN}/to-login?sig={QUERY_TOKEN}"):
            pass
    assert excinfo.value.code == "SOURCE_LOGIN_REQUIRED"
    assert _Handler.hits.get(f"/{PATH_TOKEN}/intro.mp4") is None
    assert list(temp_root.iterdir()) == []
    captured = capfd.readouterr()
    _assert_no_tokens(captured.out, captured.err)


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="needs ffmpeg")
@pytest.mark.parametrize(
    ("suffix", "content_type", "codec"),
    [
        (".aiff", "audio/aiff", "pcm_s16be"),
        (".mp3", "audio/mpeg", "libmp3lame"),
        (".wav", "audio/wav", "pcm_s16le"),
    ],
)
@pytest.mark.url_runtime
def test_real_probe_accepts_self_contained_direct_audio(
    server, temp_root, tmp_path, suffix, content_type, codec
):
    audio = tmp_path / f"talk{suffix}"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=d=1",
            "-c:a",
            codec,
            str(audio),
        ],
        check=True,
    )
    _Handler.served = {f"/{PATH_TOKEN}/talk-real": (content_type, audio.read_bytes())}
    with fetch.prepare_source(f"{server}/{PATH_TOKEN}/talk-real?sig={QUERY_TOKEN}") as ready:
        assert ready.source.kind.value == "local_audio"
        assert Path(ready.source.locator).read_bytes() == audio.read_bytes()
    assert list(temp_root.iterdir()) == []


def test_output_exists_precedes_fetch_and_creation_race_cleans_scratch(
    server,
    temp_root,
    probe_by_suffix,
    monkeypatch,
    tmp_path,
    capsys,
):
    calls = []
    original = fetch.fetch_url

    def counted(url, dest):
        calls.append(url)
        return original(url, dest)

    monkeypatch.setattr(fetch, "fetch_url", counted)
    out_dir = tmp_path / "occupied"
    out_dir.mkdir()
    code, out, err = _run_cli(
        ["extract", server + VIDEO_PATH, "--out", str(out_dir), "--json"],
        capsys,
    )
    assert code == 2 and json.loads(out)["errors"][0]["code"] == "OUTPUT_EXISTS"
    assert calls == []
    race = tmp_path / "race"
    original_prepare = evidence.prepare_empty_output

    def raced(path):
        Path(path).mkdir()
        return original_prepare(path)

    monkeypatch.setattr(evidence, "prepare_empty_output", raced)
    code, out, err = _run_cli(["extract", server + VIDEO_PATH, "--out", str(race)], capsys)
    assert code == 2 and json.loads(out)["errors"][0]["code"] == "OUTPUT_EXISTS"
    assert calls == [server + VIDEO_PATH]
    assert list(temp_root.iterdir()) == []
    _assert_no_tokens(out, err)


def test_extract_and_notes_fetch_once_and_verify_never_refetches(
    server,
    temp_root,
    probe_by_suffix,
    monkeypatch,
    tmp_path,
    capsys,
):
    seen = {}
    _install_fake_pipeline(monkeypatch, seen)
    calls = []
    original = fetch.fetch_url

    def counted(url, dest):
        calls.append(url)
        return original(url, dest)

    monkeypatch.setattr(fetch, "fetch_url", counted)
    bundle = tmp_path / "bundle"
    code, out, err = _run_cli(["extract", server + VIDEO_PATH, "--out", str(bundle)], capsys)
    assert code == 0
    assert len(calls) == 1
    code, out, err = _run_cli(["notes", server + VIDEO_PATH, "--out", str(tmp_path / "notes")], capsys)
    assert code == 0
    assert len(calls) == 2
    assert not list((tmp_path / "notes").rglob("audio.wav"))
    assert "lectural-fetch-" not in _tree_text(tmp_path / "notes")
    code, out, err = _run_cli(["notes", str(bundle)], capsys)
    assert code == 0 and len(calls) == 2
    code, out, err = _run_cli(["verify", str(bundle), "--source", server + VIDEO_PATH, "--json"], capsys)
    assert code == 1 and len(calls) == 2
    assert "SOURCE_INVALID" in out
    for value in ("https://youtu.be/dQw4w9WgXcQ", str(tmp_path / "copy.wav")):
        if value.endswith(".wav"):
            Path(value).write_bytes(AUDIO_BYTES)
        with fetch.prepare_source(value) as ready:
            assert ready.work_dir is None
    assert len(calls) == 2
    assert list(temp_root.iterdir()) == []
    _assert_no_tokens(out, err)


@pytest.mark.parametrize("missing", ["package", "hook"])
def test_resolver_dependency_failures_have_null_identity_and_no_output(
    server,
    temp_root,
    monkeypatch,
    tmp_path,
    capsys,
    missing,
):
    if missing == "package":
        monkeypatch.setitem(sys.modules, "yt_dlp", None)
    else:
        import types

        fake = types.ModuleType("yt_dlp")
        fake.YoutubeDL = type("YoutubeDL", (), {})
        networking = types.ModuleType("yt_dlp.networking")
        adapter = types.ModuleType("yt_dlp.networking._urllib")
        adapter.UrllibRH = type("UrllibRH", (), {})
        for name, module in (
            ("yt_dlp", fake),
            ("yt_dlp.networking", networking),
            ("yt_dlp.networking._urllib", adapter),
        ):
            monkeypatch.setitem(sys.modules, name, module)
    bundle = tmp_path / "bundle"
    code, out, err = _run_cli(
        ["extract", f"{server}/{PATH_TOKEN}/page?sig={QUERY_TOKEN}", "--out", str(bundle)],
        capsys,
    )
    payload = json.loads(out)
    assert code == 1
    assert payload["result"]["source"] is None
    assert payload["errors"] == [evidence.failure("EXTRACTION_FAILED")]
    assert all(value is None for value in payload["result"]["artifacts"].values())
    assert not bundle.exists() and list(temp_root.iterdir()) == []
    _assert_no_tokens(out, err)


def test_resolver_credentials_never_reach_checked_stream_requests(
    server,
    temp_root,
    probe_by_suffix,
    monkeypatch,
):
    from lectural.fetch import http

    factory, _ = _fake_youtube_dl(
        {
            "url": server + VIDEO_PATH,
            "protocol": "http",
            "ext": "mp4",
            "http_headers": {
                "cOoKiE": "secret",
                "AUTHORIZATION": "secret",
                "Proxy-Authorization": "secret",
                "User-Agent": "required-agent",
            },
        }
    )
    monkeypatch.setattr(ytdlp, "http_only_ytdlp", factory)
    original = http.open_url
    requests = []

    def checked(url, headers=None):
        requests.append(headers)
        return original(url, headers)

    monkeypatch.setattr(http, "open_url", checked)
    with fetch.prepare_source(f"{server}/{PATH_TOKEN}/page") as ready:
        assert Path(ready.source.locator).read_bytes() == MEDIA_BYTES
    assert requests == [None, {"User-Agent": "required-agent"}]


@pytest.mark.parametrize("failure", ["contract", "unexpected"])
def test_pipeline_diagnostics_and_failed_notes_results_never_expose_scratch(
    server,
    temp_root,
    probe_by_suffix,
    monkeypatch,
    tmp_path,
    capsys,
    failure,
):
    from lectural import extract

    def broken(*args, source, **kwargs):
        print(source.locator)
        print(source.locator, file=sys.stderr)
        if failure == "contract":
            raise evidence.ContractError("SPEECH_INCOMPLETE", source.locator)
        raise RuntimeError(source.locator)

    monkeypatch.setattr(extract, "extract_source", broken)
    code, out, err = _run_cli(
        ["extract", server + VIDEO_PATH, "--out", str(tmp_path / "bundle")],
        capsys,
    )
    assert code == 1
    assert json.loads(out)["result"]["source"] is None
    assert "lectural-fetch-" not in out + err
    results = cli.run(
        [server + VIDEO_PATH],
        str(tmp_path / "notes"),
        runstate_file=str(tmp_path / "state.json"),
    )
    captured = capsys.readouterr()
    assert results[0]["source"] == "http://127.0.0.1"
    assert results[0]["overall_pass"] is False
    assert "lectural-fetch-" not in json.dumps(results) + _tree_text(tmp_path)
    _assert_no_tokens(out, err, captured.out, captured.err, _tree_text(tmp_path))
    assert list(temp_root.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal and permission semantics")
def test_scratch_restores_previous_signal_handler_on_success_and_interrupt(temp_root):
    before = signal.getsignal(signal.SIGTERM)
    with scratch.scratch_space() as path:
        assert Path(path).stat().st_mode & 0o777 == 0o700
        assert signal.getsignal(signal.SIGTERM) is not before
    assert signal.getsignal(signal.SIGTERM) is before
    with pytest.raises(KeyboardInterrupt):
        with scratch.scratch_space():
            raise KeyboardInterrupt
    assert signal.getsignal(signal.SIGTERM) is before
    assert list(temp_root.iterdir()) == []


@pytest.mark.skipif(scratch.fcntl is None, reason="POSIX advisory locks")
def test_stale_scratch_keeps_foreign_owned_directories(tmp_path, monkeypatch):
    import types

    stale = tmp_path / "lectural-fetch-foreign"
    stale.mkdir()
    media_path = stale / "media.mp4"
    media_path.write_bytes(MEDIA_BYTES)
    old = time.time() - 7200
    os.utime(stale, (old, old))
    original = os.lstat

    def foreign(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if str(path) == str(stale):
            return types.SimpleNamespace(
                st_uid=os.getuid() + 1,
                st_mode=value.st_mode,
                st_mtime=value.st_mtime,
            )
        return value

    monkeypatch.setattr(os, "lstat", foreign)
    assert scratch.sweep_stale_scratch(str(tmp_path)) == []
    assert media_path.read_bytes() == MEDIA_BYTES


def test_low_level_extraction_rejects_generic_urls_without_preparation(monkeypatch, tmp_path):
    from lectural import extract

    monkeypatch.setattr(fetch, "fetch_url", lambda *args: pytest.fail("unexpected fetch"))
    with pytest.raises(ValueError):
        extract.extract_source("https://media.example.invalid/private?sig=secret", str(tmp_path / "out"))
    assert not (tmp_path / "out").exists()


def test_notes_consumer_exception_is_bounded_after_scratch_closes(
    server,
    temp_root,
    probe_by_suffix,
    monkeypatch,
    tmp_path,
    capsys,
):
    from lectural import notes

    seen = {}
    _install_fake_pipeline(monkeypatch, seen)

    def broken(_out):
        assert list(temp_root.iterdir()) == []
        raise RuntimeError(seen["speech_source"].locator + QUERY_TOKEN)

    monkeypatch.setattr(notes, "generate_notes", broken)
    state = tmp_path / "state.json"
    results = cli.run(
        [server + VIDEO_PATH],
        str(tmp_path / "notes"),
        runstate_file=str(state),
    )
    captured = capsys.readouterr()
    assert results[0]["overall_pass"] is False
    assert results[0]["error"] == evidence.failure("EXTRACTION_FAILED")["message"]
    assert json.loads(state.read_text())["runs"][0]["status"] == "failed"
    text = captured.out + captured.err + json.dumps(results) + _tree_text(tmp_path)
    _assert_no_tokens(text)
    assert "lectural-fetch-" not in text
