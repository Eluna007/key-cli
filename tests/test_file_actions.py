from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from key_cli import main
from key_cli.commands import file


@pytest.fixture
def environment(tmp_path, monkeypatch):
    data = tmp_path / "data"
    applications = data / "applications"
    applications.mkdir(parents=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "empty"))
    monkeypatch.setattr(file.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(
        file.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="manager.desktop\n"),
    )
    launched = []
    monkeypatch.setattr(file.subprocess, "Popen", lambda argv, **kw: launched.append(argv))
    target = tmp_path / '测试 <a> " $(touch nope) #%.m4a'
    target.write_bytes(b"audio")
    return applications / "manager.desktop", target, launched


def entry(path, program, terminal=False):
    path.write_text(
        f"[Desktop Entry]\nType=Application\nExec={program} %f\nTerminal={str(terminal).lower()}\n"
    )


@pytest.mark.parametrize(
    "program,terminal,prefix",
    [
        ("yazi", True, ["xdg-terminal-exec", "--", "yazi", "--"]),
        ("dolphin", False, ["dolphin", "--select"]),
        ("nautilus", False, ["nautilus", "--select"]),
    ],
)
def test_reveal_public_command(environment, capsys, program, terminal, prefix):
    desktop, target, launched = environment
    entry(desktop, program, terminal)
    assert main(["file", "reveal", str(target), "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == dict(
        schemaVersion=1,
        command="file.reveal",
        ok=True,
        error=None,
        mode="reveal",
        fileExists=True,
        path=str(target),
    )
    assert launched == [[*prefix, str(target)]]
    assert target.read_bytes() == b"audio"


@pytest.mark.parametrize("terminal", [False, True])
def test_unknown_manager_opens_directory(environment, capsys, terminal):
    desktop, target, launched = environment
    entry(desktop, "custom-manager", terminal)
    assert main(["file", "reveal", str(target)]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "directory"
    assert launched == [
        (["xdg-terminal-exec", "--"] if terminal else []) + ["xdg-open", str(target.parent)]
    ]


def test_missing_file_reveals_parent_but_cannot_open(environment, capsys):
    desktop, target, launched = environment
    entry(desktop, "yazi", True)
    target.unlink()
    assert main(["file", "reveal", str(target)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["fileExists"] is False and result["mode"] == "directory"
    assert main(["file", "open", str(target)]) == 5
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "file_missing"
    assert len(launched) == 1
    assert not target.exists()


def test_open_uses_exact_path(environment, capsys):
    _, target, launched = environment
    assert main(["file", "open", str(target)]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "open"
    assert launched == [["xdg-open", str(target)]]


def test_missing_terminal_reports_action_error(environment, monkeypatch, capsys):
    desktop, target, launched = environment
    entry(desktop, "yazi", True)
    monkeypatch.setattr(
        file.shutil, "which", lambda name: None if name == "xdg-terminal-exec" else name
    )
    assert main(["file", "reveal", str(target)]) == 3
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "dependency_missing"
    assert not launched


def test_invalid_path_and_spawn_failure(environment, monkeypatch, capsys):
    _, target, launched = environment
    assert main(["file", "open", "relative"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_path"

    def denied(*a, **k):
        raise PermissionError("launch denied")

    monkeypatch.setattr(file.subprocess, "Popen", denied)
    assert main(["file", "open", str(target)]) == 5
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "file_action_failed"
    assert not launched
