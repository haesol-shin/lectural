"""Pure URL policy and prepared source identity contracts."""

from pathlib import Path

import pytest

from lectural import fetch
from lectural.fetch.assets import FetchedMedia
from lectural.source import CitationKind, SourceKind, classify_source
from lectural.urlpolicy import public_source_label, url_origin


@pytest.mark.parametrize(
    "value",
    [
        "https://media.example.invalid/secret-path-token/lecture.mp4?sig=query-token-value",
        "http://media.example.invalid/watch?v=dQw4w9WgXcQ",
        "HTTPS://Media.Example.Invalid./clip",
    ],
)
def test_public_http_urls_prepare_as_local_with_origin_only(value: str, monkeypatch):
    monkeypatch.setattr(fetch, "fetch_url", lambda url, dest: FetchedMedia(str(Path(dest) / "media.mp4"), True))
    with fetch.prepare_source(value) as ready:
        source = ready.source
    assert source.kind is SourceKind.LOCAL_VIDEO
    assert {kind.value for kind in SourceKind} == {"youtube", "local_video", "local_audio"}
    assert source.origin == f"{value.split(':', 1)[0].lower()}://media.example.invalid"
    assert source.caption_capable is False
    assert source.citation_kind is CitationKind.TRANSCRIPT
    for descriptor in (source.as_dict(), source.safe_as_dict()):
        assert descriptor["argument"] == source.origin
        assert "token" not in str(descriptor) and "watch" not in str(descriptor)


@pytest.mark.parametrize(
    "value",
    [
        "file:///private/secret-path-token/lecture.mp4",
        "data:video/mp4;base64,c2VjcmV0LXBhdGgtdG9rZW4=",
        "ftp://media.example.invalid/secret-path-token/lecture.mp4",
        "javascript:secret-path-token",
        "https:///secret-path-token/lecture.mp4",
        # A YouTube-shaped ID never exempts a disallowed scheme.
        "ftp://youtu.be/dQw4w9WgXcQ?secret-path-token",
        "file://youtube.com/watch?v=dQw4w9WgXcQ&secret-path-token",
        "data:v=dQw4w9WgXcQ&secret-path-token",
        "x://media.example.invalid/secret-path-token?sig=1",
        "x:v=dQw4w9WgXcQ&secret-path-token",
        # A URL typed without a scheme is invalid and not echoed either.
        "media.example.invalid/secret-path-token?sig=1",
        "media.example.invalid/secret-path-token/lecture.mp4",
    ],
)
def test_non_http_urls_are_rejected_without_echoing_the_url(value: str, monkeypatch):
    monkeypatch.setattr(fetch, "fetch_url", lambda *args: pytest.fail("unexpected fetch"))
    with pytest.raises((ValueError, FileNotFoundError)) as excinfo:
        classify_source(value)
    assert "secret-path-token" not in str(excinfo.value)
    assert "c2VjcmV0" not in str(excinfo.value)
    with pytest.raises((ValueError, FileNotFoundError)) as prepared_error, fetch.prepare_source(value):
        pass
    assert "secret-path-token" not in str(prepared_error.value)
    assert "c2VjcmV0" not in str(prepared_error.value)


def test_youtube_hosts_never_become_remote_sources(monkeypatch):
    monkeypatch.setattr(fetch, "fetch_url", lambda *args: pytest.fail("unexpected fetch"))
    with pytest.raises(ValueError), fetch.prepare_source("https://www.youtube.com/playlist?list=secret-list-token"):
        pass
    with fetch.prepare_source("https://youtu.be/dQw4w9WgXcQ") as ready:
        assert ready.source.kind is SourceKind.YOUTUBE
        assert ready.work_dir is None
    with pytest.raises(ValueError, match="YouTube URL/ID"):
        classify_source("https://www.youtube.com/playlist?list=secret-list-token")
    assert classify_source("https://youtu.be/dQw4w9WgXcQ?si=token").kind is SourceKind.YOUTUBE
    assert classify_source("www.youtube.com/watch?v=dQw4w9WgXcQ").kind is SourceKind.YOUTUBE
    assert classify_source("www.youtube.com:443/watch?v=dQw4w9WgXcQ").kind is SourceKind.YOUTUBE


def test_public_source_label_keeps_local_and_youtube_and_reduces_urls(tmp_path: Path):
    local = tmp_path / "lecture.mp4"
    local.write_bytes(b"x")
    assert public_source_label(str(local)) == str(local)
    assert public_source_label("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    youtube = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert public_source_label(youtube) == youtube
    assert public_source_label("https://cdn.example.invalid/a/secret?sig=token") == "https://cdn.example.invalid"
    assert public_source_label("data:video/mp4;base64,AAAA") == "data:"
    assert public_source_label("ftp://youtu.be/dQw4w9WgXcQ") == "ftp://youtu.be"
    assert public_source_label("x://media.example.invalid/secret?sig=1") == "x://media.example.invalid"
    assert public_source_label("media.example.invalid/secret?sig=1") == "media.example.invalid"
    assert public_source_label("x:secret-path-token") == "x:"


def test_windows_drive_paths_are_not_url_schemes():
    with pytest.raises(FileNotFoundError, match="missing.mp4"):
        classify_source("C:/missing/missing.mp4")
    with pytest.raises(FileNotFoundError, match="missing.wav"):
        classify_source("C:\\missing\\missing.wav")


# fmt: off
@pytest.mark.parametrize(
    ("value", "origin"),
    [
        (
            "HTTPS://user:secret@" "Media.Example.Invalid.:8443/private?tok=secret#secret",
            "https://media.example.invalid",
        ),
        ("http://user:secret@[2001:db8::1]:8765/private?tok=secret#secret", "http://[2001:db8::1]"),
    ],
)
# fmt: on
def test_origin_omits_credentials_port_path_query_and_fragment(value, origin, monkeypatch):
    monkeypatch.setattr(fetch, "fetch_url", lambda url, dest: FetchedMedia(str(Path(dest) / "media"), False))
    assert url_origin(value) == public_source_label(value) == origin
    with fetch.prepare_source(value) as ready:
        assert ready.source.argument == ready.source.origin == origin
        assert ready.source.title_hint == origin.split("://", 1)[1]
        for descriptor in (ready.source.as_dict(), ready.source.safe_as_dict()):
            assert descriptor["argument"] == origin
            assert "secret" not in str(descriptor)


@pytest.mark.parametrize(
    "value",
    [
        "https://[secret/path?tok=secret",
        "https://host.invalid:secret/private",
        "https:///secret/path?tok=secret",
        "x:secret",
    ],
)
def test_malformed_url_parser_values_are_masked(value, capsys):
    from lectural import cli

    with pytest.raises(SystemExit):
        cli.main(["inspect", "--bogus=" + value, "bundle"])
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "secret" not in captured.out + captured.err


@pytest.mark.parametrize(
    "value",
    [
        "https:///private/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com:secret/watch?v=dQw4w9WgXcQ",
        "ftp://youtu.be/dQw4w9WgXcQ",
    ],
)
def test_youtube_shaped_ids_cannot_bypass_url_syntax(value, monkeypatch):
    monkeypatch.setattr(fetch, "fetch_url", lambda *args: pytest.fail("unexpected fetch"))
    with pytest.raises(ValueError) as excinfo, fetch.prepare_source(value):
        pass
    assert "private" not in str(excinfo.value) and "secret" not in str(excinfo.value)
