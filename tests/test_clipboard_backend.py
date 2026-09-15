from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from key_cli.clipboard import backend
from key_cli.clipboard.backend import (
    file_metadata,
    image_info,
    inspect_payload,
    lightweight,
    parse_uri_list,
    run_wl_copy,
    select_mime,
)


@pytest.fixture(autouse=True)
def isolated_clipboard_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))


def test_png_metadata_and_safe_preview_shape() -> None:
    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (16).to_bytes(4, "big") + (8).to_bytes(4, "big")
    info = image_info(data)
    assert info == ("image/png", 16, 8)
    payload, error = inspect_payload("1", data, False)
    assert error is None
    assert payload["payloadKind"] == "image"
    assert payload["width"] == 16


def test_cliphist_binary_marker_is_image() -> None:
    entry = lightweight("7", "[[ binary data 12 KB png 32x20 ]]")
    assert entry["id"] == "7"
    assert entry["payloadKind"] == "image"


def test_html_source_is_preserved_as_plain_text() -> None:
    html = b'<html><body><img src="data:image/png;base64,AAAA"></body></html>'
    payload, error = inspect_payload("8", html, False)
    assert error is None
    assert payload["payloadKind"] == "text"
    assert payload["textSubtype"] == "plain"
    assert payload["mimeType"] == "text/plain;charset=utf-8"
    assert payload["preview"] == html.decode()


def test_html_markup_and_angle_bracket_text_keep_their_original_source() -> None:
    html_payload, html_error = inspect_payload("html", b"<p>Hello</p>", False)
    plain_payload, plain_error = inspect_payload("plain", b"<not-a-tag>", False)
    assert html_error is None
    assert plain_error is None
    assert html_payload["textSubtype"] == "plain"
    assert html_payload["preview"] == "<p>Hello</p>"
    assert plain_payload["textSubtype"] == "plain"


def test_restore_keeps_html_source_bytes_and_publishes_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = b"<p>literal &amp; source</p>"
    copied: dict[str, object] = {}

    monkeypatch.setattr(backend, "executable", lambda name: name)
    monkeypatch.setattr(
        backend,
        "run",
        lambda program, arguments, *args, **kwargs: subprocess.CompletedProcess(
            [program, *arguments],
            0,
            stdout=source if program == "cliphist" else b"",
            stderr=b"",
        ),
    )

    def fake_wl_copy(program: str, arguments: list[str], input_data: bytes):
        copied.update(program=program, arguments=arguments, input_data=input_data)
        return subprocess.CompletedProcess([program, *arguments], 0)

    monkeypatch.setattr(backend, "run_wl_copy", fake_wl_copy)

    result = backend.run_command(SimpleNamespace(action="restore", id="12"))

    assert result.exit_code == 0
    assert result.json()["mimeType"] == "text/plain;charset=utf-8"
    assert copied == {
        "program": "wl-copy",
        "arguments": ["--type", "text/plain;charset=utf-8"],
        "input_data": source,
    }


def test_store_preserves_file_manager_mime_before_text(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[str], bytes | None]] = []

    monkeypatch.setattr(backend, "executable", lambda name: name)

    def fake_run(program: str, arguments: list[str], input_data: bytes | None = None, **_: object):
        calls.append((program, arguments, input_data))
        if program == "wl-paste" and arguments == ["--list-types"]:
            return subprocess.CompletedProcess(
                [program, *arguments],
                0,
                stdout=(b"text/plain\ntext/uri-list\nx-special/gnome-copied-files\n"),
                stderr=b"",
            )
        if program == "wl-paste":
            assert arguments == ["--no-newline", "--type", "x-special/gnome-copied-files"]
            return subprocess.CompletedProcess(
                [program, *arguments],
                0,
                stdout=b"copy\nfile:///tmp/report.pdf\n",
                stderr=b"",
            )
        return subprocess.CompletedProcess([program, *arguments], 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(backend, "run", fake_run)
    result = backend.store("clipboard.store", "cliphist", {})

    assert result.exit_code == 0
    assert result.json()["selectedMime"] == "x-special/gnome-copied-files"
    assert calls[-1][2] == b"copy\nfile:///tmp/report.pdf\n"


def test_mime_priority_prefers_plain_text_over_html() -> None:
    assert select_mime(["text/plain", "text/html", "image/png"]) == "image/png"
    assert select_mime(["text/plain", "text/html"]) == "text/plain"
    assert select_mime(["text/html;charset=utf-8"]) == "text/html;charset=utf-8"
    assert select_mime(["text/plain;charset=utf-8", "text/plain"]) == "text/plain;charset=utf-8"


def test_watcher_store_uses_supplied_payload_without_rereading_clipboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str], bytes | None]] = []

    monkeypatch.setattr(backend, "executable", lambda name: name)

    def fake_run(program: str, arguments: list[str], input_data: bytes | None = None, **_: object):
        calls.append((program, arguments, input_data))
        return subprocess.CompletedProcess([program, *arguments], 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(backend, "run", fake_run)
    result = backend.store(
        "clipboard.store",
        "cliphist",
        {},
        b"<p>literal</p>",
        "text/plain;charset=utf-8",
    )

    assert result.exit_code == 0
    assert result.json()["selectedMime"] == "text/plain;charset=utf-8"
    assert calls == [
        ("wl-paste", ["--list-types"], None),
        ("cliphist", ["-max-items", "500", "store"], b"<p>literal</p>"),
    ]


def test_watcher_store_skips_an_empty_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend, "executable", lambda name: name)
    monkeypatch.setattr(
        backend,
        "run",
        lambda *args, **kwargs: pytest.fail("empty selection must not reach cliphist"),
    )

    result = backend.store("clipboard.store", "cliphist", {}, b"")

    assert result.exit_code == 0
    assert result.json()["stored"] is False


def test_gnome_uri_payload_has_operation_and_never_uses_operation_as_filename() -> None:
    operation, uris = parse_uri_list("copy\nfile:///tmp/one\nfile:///tmp/two\n")
    assert operation == "copy"
    assert uris == ["file:///tmp/one", "file:///tmp/two"]

    payload, error = inspect_payload("9", b"cut\nfile:///tmp/one\nfile:///tmp/two\n", False)
    assert error is None
    assert payload["payloadKind"] == "file-list"
    assert payload["mimeType"] == "x-special/gnome-copied-files"
    assert payload["fileOperation"] == "cut"
    assert payload["icon"] == "file_copy"
    assert [item["name"] for item in payload["files"]] == ["one", "two"]


def test_file_uri_metadata_is_local_but_recent_uri_is_not_a_path(tmp_path) -> None:
    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"not-an-image")
    metadata = file_metadata(image_path.as_uri())
    assert metadata["local"] is True
    assert metadata["exists"] is True
    assert metadata["category"] == "image"
    assert metadata["name"] == "photo.png"

    recent = file_metadata("recent:///abcdef")
    assert recent["local"] is False
    assert recent["exists"] is False
    assert recent["name"] == "abcdef"


@pytest.mark.parametrize(
    ("name", "category", "icon"),
    [
        ("directory", "folder", "folder"),
        ("photo.png", "image", "image"),
        ("movie.mp4", "video", "video_file"),
        ("sound.flac", "audio", "audio_file"),
        ("document.pdf", "pdf", "picture_as_pdf"),
        ("notes.txt", "document", "description"),
    ],
)
def test_file_metadata_keeps_file_type_icons(tmp_path, name: str, category: str, icon: str) -> None:
    path = tmp_path / name
    if category == "folder":
        path.mkdir()
    else:
        path.write_bytes(b"file payload")
    metadata = file_metadata(path.as_uri())
    assert metadata["category"] == category
    assert metadata["icon"] == icon


@pytest.mark.parametrize(
    "name",
    ["else_if.cpp", "generate_cookie.py", "test_wavy.js", "widget.qml", "run.sh"],
)
def test_file_metadata_classifies_source_and_script_files_as_code(tmp_path, name: str) -> None:
    path = tmp_path / name
    path.write_text("source", encoding="utf-8")

    metadata = file_metadata(path.as_uri())

    assert metadata["category"] == "code"
    assert metadata["icon"] == "code"


def test_file_metadata_keeps_plain_documents_out_of_code_category(tmp_path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("notes", encoding="utf-8")

    metadata = file_metadata(path.as_uri())

    assert metadata["category"] == "document"
    assert metadata["icon"] == "description"


def test_plain_path_text_is_not_promoted_to_file(tmp_path) -> None:
    existing_path = tmp_path / "existing-folder"
    existing_path.mkdir()
    payload, error = inspect_payload("10", (str(existing_path) + "\n").encode(), False)
    assert error is None
    assert payload["payloadKind"] == "text"
    assert payload["files"] == []


def test_wl_copy_does_not_capture_forked_selection_owner_pipes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeStdin:
        def write(self, value: bytes) -> None:
            captured["written"] = value

        def close(self) -> None:
            captured["stdin_closed"] = True

    class FakeProcess:
        stdin = FakeStdin()
        returncode = None

        def poll(self):
            return self.returncode

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(backend.subprocess, "Popen", fake_popen)
    result = run_wl_copy("wl-copy", ["--type", "text/plain"], b"hello")

    assert result is not None
    assert captured["argv"] == ["wl-copy", "--foreground", "--type", "text/plain"]
    assert captured["written"] == b"hello"
    assert captured["stdin_closed"] is True
    assert captured["stdin"] is subprocess.PIPE
    assert captured["stdout"] is subprocess.DEVNULL
    assert captured["stderr"] is subprocess.DEVNULL
    assert captured["start_new_session"] is True


def test_wl_copy_reports_owner_start_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingStdin:
        def write(self, value: bytes) -> None:
            return None

        def close(self) -> None:
            return None

    class FailingProcess:
        stdin = FailingStdin()
        returncode = 7

        def poll(self):
            return self.returncode

    monkeypatch.setattr(
        backend.subprocess,
        "Popen",
        lambda *args, **kwargs: FailingProcess(),
    )
    result = run_wl_copy("wl-copy", [], b"payload")
    assert result is not None
    assert result.returncode == 7


@pytest.mark.parametrize(
    ("offered", "expected"),
    [
        (["text/html", "text/markdown", "text/plain; charset=UTF-8"], "text/plain; charset=UTF-8"),
        (["text/html", "text/markdown"], "text/markdown"),
        (["application/json", "text/csv"], "text/csv"),
        (["text/plain", 'Text/Plain; charset="UTF-8"'], 'Text/Plain; charset="UTF-8"'),
        (["application/octet-stream", "application/rtf"], ""),
    ],
)
def test_literal_mime_fallback_priority(offered, expected):
    assert select_mime(offered) == expected


def test_list_can_return_750_valid_entries_without_inspection(monkeypatch):
    monkeypatch.setattr(backend, "executable", lambda name: name)
    calls = []

    def listing(program, arguments, *args):
        calls.append((program, arguments))
        rows = [b"invalid", b"no-id\tignored", b"0\tignored"]
        rows.extend(f"{i}\tentry {i}".encode() for i in range(800, 0, -1))
        return subprocess.CompletedProcess([program, *arguments], 0, stdout=b"\n".join(rows))

    monkeypatch.setattr(backend, "run", listing)
    result = backend.run_command(SimpleNamespace(action="list", limit=750))
    assert result.exit_code == 0
    assert len(result.json()["entries"]) == 750
    assert result.json()["entries"][-1]["id"] == "51"
    assert calls == [("cliphist", ["list"])]


def test_inspection_retains_search_text_beyond_preview():
    text = "a" * 5000 + " searchable suffix"
    payload, failure = inspect_payload("1", text.encode(), False)
    assert failure is None
    assert "searchable suffix" not in payload["preview"]
    assert "searchable suffix" in payload["searchText"]


@pytest.mark.parametrize(
    ("text", "lines"),
    [("", 0), ("a", 1), ("a\n", 2), ("a\n\nb", 3), ("a\r\nb", 2), (" \t中文😀\r\n\r x \n", 4)],
)
def test_detail_statistics_preserve_literal_text(text, lines):
    data = text.encode("utf-8")
    payload, failure = inspect_payload("1", data, False)
    assert failure is None
    assert payload["payloadKind"] == "text"
    assert payload["searchText"] == text
    assert payload["characterCount"] == len(text)
    assert payload["textLineCount"] == lines
    assert payload["byteSize"] == len(data)
    assert payload["textTruncated"] is False
    assert "characterCount" not in lightweight("1", "summary")
    assert "textLineCount" not in lightweight("1", "summary")


@pytest.mark.parametrize("length", [262143, 262144, 262145])
def test_detail_limit_is_unicode_codepoints(length):
    text = "😀" * (length - 1) + "末"
    payload, failure = inspect_payload("1", text.encode(), False)
    assert failure is None
    assert payload["characterCount"] == length
    assert payload["searchText"] == text[:262144]
    assert payload["textTruncated"] is (length > 262144)
    assert payload["detailTextLimit"] == 262144
    assert payload["byteSize"] == len(text.encode())


@pytest.mark.parametrize(
    "data",
    [
        ("中😀\n" * 100000 + " final tail ").encode(),
        b"GIF89a" + b"\x10\x00\x08\x00" + b"animation frame bytes",
        b"RIFF" + b"\0" * 4 + b"WEBPVP8X" + b"\0" * 4 + b"\x02" + b"\0" * 9 + b"ANIM frame bytes",
    ],
)
def test_inspect_and_restore_keep_entire_saved_payload(monkeypatch, data):
    from pathlib import Path
    from urllib.parse import unquote, urlparse

    copied = []
    monkeypatch.setattr(backend, "executable", lambda name: name)
    monkeypatch.setattr(
        backend,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, stdout=data, stderr=b""),
    )
    monkeypatch.setattr(
        backend,
        "run_wl_copy",
        lambda program, args, input_data: (
            copied.append(input_data) or subprocess.CompletedProcess([], 0)
        ),
    )
    inspected = backend.run_command(SimpleNamespace(action="inspect", id="12"))
    assert inspected.exit_code == 0
    info = inspected.json()
    assert info["schemaVersion"] == 1
    assert info["command"] == "clipboard.inspect"
    if info["payloadKind"] == "image":
        assert Path(unquote(urlparse(info["previewUrl"]).path)).read_bytes() == data
    else:
        assert info["textTruncated"] is True
        assert not info["searchText"].endswith(" final tail ")
    restored = backend.run_command(SimpleNamespace(action="restore", id="12"))
    assert restored.exit_code == 0
    assert copied == [data]


def test_file_reference_sizes_states_and_timestamp(tmp_path, monkeypatch):
    import os

    path = tmp_path / "empty.txt"
    path.touch()
    os.utime(path, (1700000000, 1700000000.5))
    uri_bytes = (path.as_uri() + "\n").encode()
    payload, failure = inspect_payload("1", uri_bytes, False)
    assert failure is None
    item = payload["files"][0]
    assert payload["byteSize"] == len(uri_bytes)
    assert item["byteSize"] == 0 and item["sizeKnown"] is True
    assert item["modifiedTime"] == 1700000000.5
    assert item["metadataAvailable"] is True
    directory = file_metadata(tmp_path.as_uri())
    assert directory["directory"] is True and directory["sizeKnown"] is False
    assert directory["byteSize"] == 0
    path.write_bytes(b"changed")
    assert file_metadata(path.as_uri())["byteSize"] == 7
    monkeypatch.setattr(backend.os, "access", lambda *args: False)
    unreadable = file_metadata(path.as_uri())
    assert unreadable["metadataStatus"] == "unreadable"
    assert unreadable["sizeKnown"] is False
    path.unlink()
    missing = file_metadata(path.as_uri())
    assert missing["metadataStatus"] == "missing"
    assert missing["modifiedTime"] is None and missing["sizeKnown"] is False
    remote = file_metadata("smb://host/share/photo.png")
    assert remote["metadataStatus"] == "remote"
    assert remote["previewUrl"] == "" and remote["metadataAvailable"] is False


def test_file_preview_excludes_svg_and_unsafe_or_damaged_images(tmp_path):
    for name, data in [
        ("photo.svg", b'<svg><image href="https://example.test/image"/></svg>'),
        ("broken.png", b"broken"),
        (
            "huge.png",
            b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + (20000).to_bytes(4, "big") + (1).to_bytes(4, "big"),
        ),
    ]:
        path = tmp_path / name
        path.write_bytes(data)
        assert file_metadata(path.as_uri())["previewUrl"] == ""


def test_image_reference_read_failure_does_not_claim_readable_size(tmp_path, monkeypatch):
    from pathlib import Path

    path = tmp_path / "locked.png"
    path.write_bytes(b"image bytes")

    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "open", denied)
    item = file_metadata(path.as_uri())
    assert item["metadataAvailable"] is True
    assert item["metadataStatus"] == "unreadable"
    assert item["sizeKnown"] is False and item["previewUrl"] == ""
    # Lightweight listings must not attempt to read image data.
    row = lightweight("1", path.as_uri())
    assert row["files"][0]["metadataStatus"] == "available"
