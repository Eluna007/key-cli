from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from key_cli import main
from key_cli.clipboard import config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    for name in tuple(os.environ):
        if name.startswith("CLIPHIST_") or name in {"CLIPBOARD_STATE", "CLIPBOARD_TYPE"}:
            monkeypatch.delenv(name)


def invoke(capsys, *arguments):
    code = main(["clipboard", "config", *arguments, "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["schemaVersion"] == 1
    assert payload["command"] == "clipboard.config"
    assert payload["ok"] is (code == 0)
    return code, payload


def test_missing_config_is_read_only_and_needs_no_clipboard_tools(capsys, monkeypatch):
    monkeypatch.setenv("PATH", "")
    code, payload = invoke(capsys)
    assert code == 0
    assert payload["maxItems"] == 500
    assert payload["error"] is None
    assert not config.config_path().exists()


@pytest.mark.parametrize("limit", [50, 500, 750])
def test_config_persists_across_processes(limit, capsys):
    code, payload = invoke(capsys, "--max-items", str(limit))
    assert code == 0
    assert payload["maxItems"] == limit
    assert json.loads(config.config_path().read_text())["maxItems"] == limit
    result = subprocess.run(
        [sys.executable, "-m", "key_cli", "clipboard", "config", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["maxItems"] == limit


@pytest.mark.parametrize(
    "value", ["0", "49", "751", "800", "75", "499", "500.0", "50.5", "abc", "-50"]
)
def test_invalid_limit_does_not_write(value, capsys):
    invoke(capsys, "--max-items", "500")
    previous = config.config_path().read_bytes()
    code, payload = invoke(capsys, "--max-items", value)
    assert code == 2
    assert payload["error"]["code"] == "invalid_clipboard_limit"
    assert config.config_path().read_bytes() == previous


@pytest.mark.parametrize(
    "data",
    [b"{", b"{}", b"[]", b'{"maxItems":true}', b'{"maxItems":75}', b'{"maxItems":500.0}', b"\xff"],
)
def test_corrupt_config_is_reported_and_never_overwritten(data, capsys):
    path = config.config_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    for args in [(), ("--max-items", "500")]:
        code, payload = invoke(capsys, *args)
        assert code == 1
        assert payload["error"]["code"] == "clipboard_config_read_failed"
        assert path.read_bytes() == data


def test_atomic_replace_failure_preserves_old_config(capsys, monkeypatch):
    invoke(capsys, "--max-items", "750")
    previous = config.config_path().read_bytes()

    def denied(*args):
        raise PermissionError("write denied")

    monkeypatch.setattr(config.os, "replace", denied)
    code, payload = invoke(capsys, "--max-items", "50")
    assert code == 1
    assert payload["error"]["code"] == "clipboard_config_write_failed"
    assert config.config_path().read_bytes() == previous
    assert list(config.config_path().parent.iterdir()) == [config.config_path()]


def test_xdg_fallback(monkeypatch, capsys):
    for value in [None, ""]:
        if value is None:
            monkeypatch.delenv("XDG_CONFIG_HOME")
        else:
            monkeypatch.setenv("XDG_CONFIG_HOME", value)
        code, payload = invoke(capsys, "--max-items", "50")
        assert code == 0
        assert payload["maxItems"] == 50
        assert (Path.home() / ".config/key/clipboard.json").is_file()


@pytest.mark.parametrize("limit", [50, 500, 750])
def test_real_cliphist_trims_only_on_accepted_store(limit, tmp_path, monkeypatch, capsys):
    cliphist = shutil.which("cliphist")
    if not cliphist:
        pytest.skip("cliphist is required for native retention integration")
    tools = tmp_path / "bin"
    tools.mkdir()
    paste = tools / "wl-paste"
    paste.write_text(f'#!{sys.executable}\nprint("text/plain")\n')
    paste.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    # Deliberately conflicting limits: the explicit CLI flag must win, while
    # the non-default database, preview width and minimum length remain in force.
    clip_config = Path(os.environ["XDG_CONFIG_HOME"]) / "cliphist/config"
    clip_config.parent.mkdir(parents=True)
    database = tmp_path / "custom.db"
    clip_config.write_text(
        f"db-path {database}\nmax-items 700\npreview-width 20\nmin-store-length 5\nmax-dedupe-search 3\n"
    )
    monkeypatch.setenv("CLIPHIST_MAX_ITEMS", "650")
    for index in range(limit + 3):
        subprocess.run(
            [cliphist, "-max-items", "1000", "store"],
            input=f"entry-{index:04}".encode(),
            check=True,
            capture_output=True,
        )

    def listing():
        result = subprocess.run(
            [sys.executable, "-m", "key_cli", "clipboard", "list", "--limit", "750", "--json"],
            check=True,
            capture_output=True,
        )
        return json.loads(result.stdout)["entries"]

    def store(data, state="data"):
        env = dict(os.environ, CLIPBOARD_TYPE="text/plain", CLIPBOARD_STATE=state)
        return subprocess.run(
            [sys.executable, "-m", "key_cli", "clipboard", "store", "--stdin", "--json"],
            input=data,
            env=env,
            check=True,
            capture_output=True,
        )

    before = subprocess.check_output([cliphist, "list"])
    assert invoke(capsys, "--max-items", str(limit))[0] == 0
    assert invoke(capsys)[1]["maxItems"] == limit
    assert len(listing()) == min(limit + 3, 750)
    for data, state in [
        (b"secret", "sensitive"),
        (b"", "data"),
        (b"ignored", "clear"),
        (b"abc", "data"),
    ]:
        store(data, state)
        assert subprocess.check_output([cliphist, "list"]) == before
    store(b"newest accepted record with a searchable suffix")
    entries = listing()
    assert len(entries) == limit
    assert entries[0]["preview"].startswith("newest accepted")
    assert entries[-1]["preview"] == "entry-0004"
    assert database.exists()
    assert not (Path(os.environ["XDG_CACHE_HOME"]) / "cliphist/db").exists()
    assert invoke(capsys, "--max-items", "750")[0] == 0
    assert len(listing()) == limit  # increasing the limit cannot recover old records


def test_unreadable_config_reports_read_error(capsys, monkeypatch):
    def denied():
        raise PermissionError("read denied")

    monkeypatch.setattr(config, "load", denied)
    for args in [(), ("--max-items", "50")]:
        code, payload = invoke(capsys, *args)
        assert code == 1
        assert payload["error"]["code"] == "clipboard_config_read_failed"


def test_corrupt_config_aborts_store_without_cliphist_calls(monkeypatch):
    from key_cli.clipboard import backend

    path = config.config_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(b"broken")
    monkeypatch.setattr(backend, "executable", lambda name: name)
    calls = []

    def run(program, arguments, *args):
        calls.append((program, arguments))
        return subprocess.CompletedProcess([program, *arguments], 0, stdout=b"text/plain\n")

    monkeypatch.setattr(backend, "run", run)
    result = backend.store("clipboard.store", "cliphist", {}, b"payload", "text/plain")
    assert result.exit_code == 1
    assert result.json()["error"]["code"] == "clipboard_config_read_failed"
    assert calls == [("wl-paste", ["--list-types"])]
    assert path.read_bytes() == b"broken"
