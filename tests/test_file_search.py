"""CLI/backend contracts with a bounded fake fd and isolated filesystem."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from key_cli import main
from key_cli.files import backend


@pytest.fixture
def fake_fd(tmp_path, monkeypatch):
    tool = tmp_path / "fd"
    tool.write_text(
        f"#!{sys.executable}\nimport os,sys,json,time\n"
        "open(os.environ['FD_ARGS'], 'w').write(json.dumps(sys.argv[1:]))\n"
        "sys.stdout.buffer.write(bytes.fromhex(os.environ.get('FD_DATA','')))\n"
        "sys.stdout.buffer.flush()\n"
        "time.sleep(float(os.environ.get('FD_SLEEP','0')))\n"
        "sys.exit(int(os.environ.get('FD_EXIT','0')))\n"
    )
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("FD_ARGS", str(tmp_path / "args.json"))
    return tmp_path


def search(capsys, root, query="a", limit="50"):
    code = main(
        ["file", "search", "--format", "json", "--root", str(root), "--limit", limit, "--", query]
    )
    data = json.loads(capsys.readouterr().out)
    assert data["schemaVersion"] == 1 and data["command"] == "file.search"
    assert data["ok"] == (code == 0)
    return code, data


def output(monkeypatch, paths):
    monkeypatch.setenv("FD_DATA", b"".join(os.fsencode(p) + b"\0" for p in paths).hex())


def test_literal_query_and_nul_metadata(fake_fd, monkeypatch, capsys):
    names = ['-中文 "\n\t#%?[(*.WAV', "aaa", "a", "ab", "za"]
    paths = [fake_fd / name for name in names]
    for path in paths:
        path.touch()
    folder = fake_fd / "folder"
    folder.mkdir()
    link = fake_fd / "link"
    link.symlink_to(folder)
    dangling = fake_fd / "dangling"
    dangling.symlink_to(fake_fd / "absent")
    fifo = fake_fd / "fifo"
    os.mkfifo(fifo)
    output(monkeypatch, paths + [folder, link, dangling, fifo])
    code, data = search(capsys, fake_fd, query="-[(*")
    assert code == 0 and data["complete"] and not data["limited"]
    args = json.loads((fake_fd / "args.json").read_text())
    assert args[-3:] == ["--", "-[(*", str(fake_fd)]
    assert "--fixed-strings" in args and "--print0" in args and "--ignore-case" in args
    assert "--hidden" not in args and "--follow" not in args
    items = {item["path"]: item for item in data["entries"]}
    assert str(fifo) not in items
    assert items[str(paths[0])]["extension"] == "wav"
    assert items[str(paths[0])]["size"] == 0
    assert items[str(paths[0])]["name"] == names[0]
    assert items[str(folder)]["size"] is None
    assert items[str(link)]["kind"] == "symlink" and items[str(link)]["isDirectory"]
    assert not items[str(link)]["isExecutable"]
    assert not items[str(dangling)]["targetAvailable"]
    assert items[str(dangling)]["modifiedTime"] == dangling.lstat().st_mtime
    assert items[str(dangling)]["parentPath"] == str(fake_fd)
    assert items[str(dangling)]["mimeType"] == "application/octet-stream"


def test_sort_limits_and_path_matching(fake_fd, monkeypatch, capsys):
    paths = [fake_fd / name for name in ["za", "ab", "a", "aa"]]
    for p in paths:
        p.touch()
    output(monkeypatch, paths)
    data = search(capsys, fake_fd, limit="2")[1]
    assert [e["name"] for e in data["entries"]] == ["a", "aa"]
    assert data["limited"] and not data["complete"] and data["limitReasons"] == ["results"]
    search(capsys, fake_fd, "folder/a")
    assert "--full-path" in json.loads((fake_fd / "args.json").read_text())


def test_empty_missing_failed_and_invalid(fake_fd, monkeypatch, capsys):
    assert search(capsys, fake_fd, " \t")[1]["entries"] == []
    assert not (fake_fd / "args.json").exists()
    assert search(capsys, fake_fd)[1]["complete"]
    monkeypatch.setenv("FD_EXIT", "2")
    assert search(capsys, fake_fd)[1]["error"]["code"] == "file_search_failed"
    assert search(capsys, fake_fd, limit="0")[0] == 2
    assert search(capsys, fake_fd, limit="oops")[0] == 2
    monkeypatch.setenv("PATH", "")
    assert search(capsys, fake_fd)[0] == 3
    assert main(["file", "search", "--format", "json"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_arguments"


def test_partial_time_candidate_and_non_utf8(fake_fd, monkeypatch, capsys):
    path = fake_fd / "a"
    path.touch()
    output(monkeypatch, [path, os.fsencode(fake_fd) + b"/\xff"])
    monkeypatch.setenv("FD_SLEEP", "2")
    monkeypatch.setattr(backend, "SEARCH_SECONDS", 0.15)
    data = search(capsys, fake_fd)[1]
    assert data["limitReasons"] == ["time"] and data["skippedNonUtf8"] == 1
    assert data["entries"][0]["path"] == str(path)
    monkeypatch.setattr(backend, "MAX_CANDIDATES", 1)
    assert search(capsys, fake_fd)[1]["limitReasons"] == ["candidates"]


def test_status_reports_missing_search_without_disabling_actions(monkeypatch, capsys):
    monkeypatch.setattr(backend, "fd_program", lambda: None)
    monkeypatch.setattr(backend, "manager_available", lambda: False)
    monkeypatch.setattr(backend.shutil, "which", lambda p: "/bin/gio" if p == "gio" else None)
    assert main(["file", "status", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert not data["canSearch"] and data["canOpen"] and data["canReveal"]
    assert data["reasons"]["search"] == "fd_unavailable"


def test_cancel_reaps_owned_fd(fake_fd, monkeypatch):
    pid_path = fake_fd / "pid"
    tool = fake_fd / "fd"
    tool.write_text(
        f"#!{sys.executable}\nimport os,time\nopen({str(pid_path)!r},'w').write(str(os.getpid()))\ntime.sleep(30)\n"
    )
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    child = subprocess.Popen(
        [sys.executable, "-m", "key_cli", "file", "search", "--root", str(fake_fd), "--", "a"],
        env=env,
        stdout=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 5
        while not pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pid_path.exists()
        fd_pid = int(pid_path.read_text())
        child.send_signal(signal.SIGTERM)
        data = json.loads(child.communicate(timeout=3)[0])
        assert data["error"]["code"] == "file_search_cancelled"
        assert not Path(f"/proc/{fd_pid}").exists()
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
