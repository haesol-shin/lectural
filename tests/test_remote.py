"""Public http(s) media URL sources: fetch, cleanup, and redaction (offline)."""

from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
import os
from pathlib import Path
import socket
import tempfile
import threading

import pytest

from lectural import acquisition, cli, media, remote, vad, visual

MEDIA_BYTES = b"\x00\x00\x00\x18ftypmp42synthetic-lecture-media" * 64
AUDIO_BYTES = b"ID3synthetic-lecture-audio" * 64
PATH_TOKEN = "secretpathtoken"
QUERY_TOKEN = "querysigtoken"
VIDEO_PATH = f"/{PATH_TOKEN}/lecture.mp4?sig={QUERY_TOKEN}&expires=1"
TOKENS = (PATH_TOKEN, QUERY_TOKEN, "lecture.mp4", "sig=")


class _Handler(BaseHTTPRequestHandler):
    ftp_port = 21
    hits: dict = {}

    def log_message(self, *_args):  # keep test output quiet
        pass

    def _html(self, video_src: str) -> None:
        body = f'<html><head><title>{PATH_TOKEN}</title></head><body><video src="{video_src}"></video></body></html>'
        self._send(200, body.encode(), "text/html")

    def _send(self, status: int, body: bytes = b"", content_type: str = "text/plain", headers: dict | None = None):
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
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
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
    monkeypatch.setattr(remote, "_has_video_stream", lambda path: path.endswith(".mp4"))


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
            [acquisition.Segment(0.0, "First sentence", end=4.0), acquisition.Segment(5.0, "Second sentence", end=20.0)],
            "stt",
            language="en",
            meta={"audio_path": str(audio), "duration": 20.0, "model": model, "fallback_code": "local_source"},
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
    server, temp_root, probe_by_suffix, monkeypatch, tmp_path, capsys,
):
    seen: dict = {}
    _install_fake_pipeline(monkeypatch, seen)
    local_file = tmp_path / "lecture.mp4"
    local_file.write_bytes(MEDIA_BYTES)
    local_code, local_out, _ = _run_cli(["extract", str(local_file), "--out", str(tmp_path / "local"), "--json"], capsys)
    url_out_dir = tmp_path / "remote"
    url_code, url_out, url_err = _run_cli(["extract", server + VIDEO_PATH, "--out", str(url_out_dir), "--json"], capsys)

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


def test_audio_url_becomes_local_audio_evidence(server, temp_root, probe_by_suffix, monkeypatch, tmp_path, capsys):
    seen: dict = {}
    _install_fake_pipeline(monkeypatch, seen)
    out_dir = tmp_path / "audio-bundle"
    code, out, err = _run_cli(["extract", f"{server}/{PATH_TOKEN}/talk.mp3?sig={QUERY_TOKEN}", "--out", str(out_dir), "--json"], capsys)
    manifest = json.loads(out)["result"]
    assert code == 0
    assert manifest["source"]["kind"] == "local_audio"
    assert manifest["source"]["has_video"] is False
    assert manifest["frames"] == []
    assert list(temp_root.iterdir()) == []
    _assert_no_tokens(out, err, _tree_text(out_dir))


def test_redirect_to_http_media_is_followed(server, temp_root, probe_by_suffix, monkeypatch, tmp_path, capsys):
    seen: dict = {}
    _install_fake_pipeline(monkeypatch, seen)
    code, out, _ = _run_cli(["extract", f"{server}/{PATH_TOKEN}/to-media", "--out", str(tmp_path / "b"), "--json"], capsys)
    assert code == 0
    assert seen["video_bytes"] == MEDIA_BYTES
    assert json.loads(out)["result"]["source"]["argument"] == "http://127.0.0.1"


def test_failed_extraction_still_removes_fetched_media(server, temp_root, probe_by_suffix, monkeypatch, tmp_path, capsys):
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
        (f"/{PATH_TOKEN}/private?sig={QUERY_TOKEN}", "SOURCE_UNAUTHORIZED"),
        (f"/{PATH_TOKEN}/forbidden", "SOURCE_UNAUTHORIZED"),
        (f"/{PATH_TOKEN}/missing", "SOURCE_UNAVAILABLE"),
        (f"/{PATH_TOKEN}/truncated", "SOURCE_UNAVAILABLE"),
    ],
)
def test_remote_failures_are_bounded_and_leave_nothing(server, temp_root, probe_by_suffix, tmp_path, capsys, suffix, code):
    out_dir = tmp_path / "bundle"
    exit_code, out, err = _run_cli(["extract", server + suffix, "--out", str(out_dir), "--json"], capsys)
    payload = json.loads(out)
    assert exit_code == 2
    assert payload["status"] == "error"
    assert [error["code"] for error in payload["errors"]] == [code]
    assert payload["result"]["source"] is None
    assert payload["result"]["artifacts"]["output_dir"] is None
    assert not out_dir.exists()
    assert list(temp_root.iterdir()) == []
    _assert_no_tokens(out, err)


def test_unreachable_url_is_bounded(temp_root, tmp_path, capsys):
    exit_code, out, err = _run_cli(["extract", _closed_port_url(), "--out", str(tmp_path / "b"), "--json"], capsys)
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


def test_notes_run_redacts_url_in_run_state_and_output(server, temp_root, probe_by_suffix, monkeypatch, tmp_path, capsys):
    seen: dict = {}
    _install_fake_pipeline(monkeypatch, seen)
    runstate_path = tmp_path / "runstate.json"
    monkeypatch.setenv("LECTURAL_RUNSTATE", str(runstate_path))
    out_root = tmp_path / "notes-out"
    failing = f"{server}/{PATH_TOKEN}/forbidden?sig={QUERY_TOKEN}"
    exit_code, out, err = _run_cli(["notes", server + VIDEO_PATH, failing, "--out", str(out_root)], capsys)

    state = json.loads(runstate_path.read_text(encoding="utf-8"))
    assert exit_code == 2  # the second (unauthorized) input fails
    assert [run["status"] for run in state["runs"]] == ["complete", "failed"]
    assert [run["source"] for run in state["runs"]] == ["http://127.0.0.1", "http://127.0.0.1"]
    assert "only public URLs are supported" in err
    bundle = Path(state["runs"][0]["output_dir"])
    assert (bundle / "notes.md").is_file()
    assert json.loads((bundle / "synthesis_input.json").read_text(encoding="utf-8"))["video"]["input_source"]["argument"] == "http://127.0.0.1"
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


def test_page_url_downloads_the_single_progressive_format_ytdlp_selects(server, temp_root, probe_by_suffix, monkeypatch):
    info = {
        "extractor_key": "SomeSite",
        "title": f"Week 3 lecture {PATH_TOKEN}",
        "url": server + VIDEO_PATH,
        "protocol": "http",
        "ext": "mp4",
        "http_headers": {"User-Agent": "test-agent", "Cookie": "session=leak"},
    }
    factory, calls = _fake_youtube_dl(info)
    monkeypatch.setattr(remote, "_http_only_ytdlp", factory)
    page = f"{server}/{PATH_TOKEN}/page?sig={QUERY_TOKEN}"
    with remote.materialize(cli.classify_source(page)) as ready:
        assert Path(ready.source.locator).read_bytes() == MEDIA_BYTES
        # Extractor titles can quote the URL; a fetched source is titled by host.
        assert ready.source.title_hint == "127.0.0.1"
        assert ready.source.safe_as_dict()["argument"] == "http://127.0.0.1"
        scratch = ready.scratch_dir
    assert not os.path.exists(scratch)
    params = calls[0]
    assert params["noplaylist"] is True
    assert params["cookiefile"] is None and params["cookiesfrombrowser"] is None
    assert "protocol=http" in params["format"]


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (RuntimeError(f"ERROR: [Site] {PATH_TOKEN}: This video is private. Use --cookies"), "SOURCE_UNAUTHORIZED"),
        (RuntimeError(f"ERROR: Unsupported URL: https://x.invalid/{PATH_TOKEN}"), "SOURCE_UNAVAILABLE"),
        ({"url": "rtmp://cdn.invalid/live", "protocol": "rtmp"}, "SOURCE_UNAVAILABLE"),
        ({"url": "https://cdn.invalid/v.m3u8", "protocol": "m3u8_native"}, "SOURCE_UNAVAILABLE"),
        ({"url": "ftp://cdn.invalid/v.mp4", "protocol": "https"}, "SOURCE_UNAVAILABLE"),
        ({"_type": "playlist", "entries": []}, "SOURCE_UNAVAILABLE"),
        ({"requested_formats": [{}, {}], "url": "https://cdn.invalid/v", "protocol": "https"}, "SOURCE_UNAVAILABLE"),
    ],
)
def test_page_url_resolution_failures_are_bounded(server, temp_root, monkeypatch, result, code):
    factory, _calls = _fake_youtube_dl(result)
    monkeypatch.setattr(remote, "_http_only_ytdlp", factory)
    with pytest.raises(remote.RemoteSourceError) as excinfo:
        with remote.materialize(cli.classify_source(f"{server}/{PATH_TOKEN}/page")):
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


def test_real_ytdlp_resolves_html5_page_through_checked_download(server, temp_root, probe_by_suffix, capfd):
    pytest.importorskip("yt_dlp")
    with remote.materialize(cli.classify_source(f"{server}/{PATH_TOKEN}/html5?ref={QUERY_TOKEN}")) as ready:
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
    for name, module in (("yt_dlp", fake), ("yt_dlp.networking", networking), ("yt_dlp.networking._urllib", urllib_module)):
        monkeypatch.setitem(sys.modules, name, module)
    with pytest.raises(remote.DependencyError):
        remote._http_only_ytdlp([])


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


def test_unknown_command_hint_does_not_echo_url_tokens(capsys):
    with pytest.raises(SystemExit):
        cli.main([f"https://media.example.invalid/{PATH_TOKEN}?sig={QUERY_TOKEN}"])
    captured = capsys.readouterr()
    assert "lectural notes" in captured.err
    _assert_no_tokens(captured.out, captured.err)


@pytest.mark.parametrize("route", ["page-to-ftp", "html5-to-ftp"])
def test_real_ytdlp_never_follows_a_redirect_to_ftp(server, temp_root, probe_by_suffix, ftp_listener, capsys, route):
    pytest.importorskip("yt_dlp")
    with pytest.raises(remote.RemoteSourceError) as excinfo:
        with remote.materialize(cli.classify_source(f"{server}/{PATH_TOKEN}/{route}")):
            pass
    assert excinfo.value.code == "SOURCE_REDIRECT_REJECTED"
    assert not _connection_attempted(ftp_listener)
    assert list(temp_root.iterdir()) == []
    captured = capsys.readouterr()
    _assert_no_tokens(captured.out, captured.err)
