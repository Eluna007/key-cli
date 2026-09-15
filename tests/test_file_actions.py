"""Public file actions: safe desktop requests with acceptance and fallback."""

from types import SimpleNamespace
import json
import subprocess

import pytest

from key_cli import main
from key_cli.files import backend


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    target = tmp_path / '测试 <a> " $(touch nope)\n\t#%?.wav'
    target.write_bytes(b"audio")
    calls = []
    monkeypatch.setattr(backend.shutil, "which", lambda name: "/bin/" + name)

    def spawn(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(wait=lambda timeout: 0)

    def bus(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(backend.subprocess, "Popen", spawn)
    monkeypatch.setattr(backend.subprocess, "run", bus)
    return target, calls


def response(capsys, action, path):
    code = main(["file", action, "--format", "json", "--", str(path)])
    data = json.loads(capsys.readouterr().out)
    assert data["schemaVersion"] == 1 and data["command"] == "file." + action
    assert data["ok"] == (code == 0)
    return code, data


def test_open_exact_path_and_directory(desktop, capsys):
    target, calls = desktop
    for path in (target, target.parent):
        code, data = response(capsys, "open", path)
        assert code == 0 and data["mode"] == "open" and data["error"] is None
        assert calls[-1][0] == ["gio", "open", "--", str(path)]
        assert calls[-1][1]["start_new_session"] is True
        assert not calls[-1][1].get("shell")


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "dangling"])
def test_reveal_typed_uri_including_link_identity(desktop, capsys, kind):
    target, calls = desktop
    path = target
    if kind == "directory":
        path = target.parent
    elif kind in {"symlink", "dangling"}:
        path = target.parent / "link"
        path.symlink_to(target if kind == "symlink" else target.parent / "missing")
    code, data = response(capsys, "reveal", path)
    assert code == 0 and data["mode"] == "reveal"
    assert calls[-1][0][-5:] == ["ShowItems", "ass", "1", path.as_uri(), ""]
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["missing", "error", "timeout"])
def test_reveal_fallback_waits_for_opener(desktop, monkeypatch, capsys, failure):
    target, calls = desktop

    def failed(*args, **kwargs):
        if failure == "missing":
            raise FileNotFoundError()
        if failure == "timeout":
            raise subprocess.TimeoutExpired("busctl", 4)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(backend.subprocess, "run", failed)
    code, data = response(capsys, "reveal", target)
    assert code == 0 and data["mode"] == "directory"
    assert calls[-1][0] == ["gio", "open", "--", str(target.parent)]


def test_missing_and_dangling_open_fail_reveal_survives(desktop, capsys):
    target, calls = desktop
    target.unlink()
    assert response(capsys, "open", target)[1]["error"]["code"] == "file_missing"
    assert response(capsys, "reveal", target)[1]["mode"] == "directory"
    target.symlink_to(target.parent / "missing")
    assert response(capsys, "open", target)[0] == 5
    assert response(capsys, "reveal", target)[1]["mode"] == "reveal"


@pytest.mark.parametrize("kind", ["executable", "desktop", "linked-desktop"])
def test_never_launch_executable_content(desktop, capsys, kind):
    target, calls = desktop
    if kind == "executable":
        target.chmod(0o755)
    else:
        desktop_file = target.with_suffix(".desktop")
        desktop_file.write_text("[Desktop Entry]\nExec=touch /tmp/forbidden\n")
        if kind == "desktop":
            target = desktop_file
        else:
            target.unlink()
            target.symlink_to(desktop_file)
    code, data = response(capsys, "open", target)
    assert code == 5 and data["error"]["code"] == "file_execution_blocked"
    assert not calls


def test_failure_is_not_spawn_success(desktop, monkeypatch, capsys):
    target, _ = desktop
    monkeypatch.setattr(
        backend.subprocess, "Popen", lambda *a, **k: SimpleNamespace(wait=lambda timeout: 2)
    )
    assert response(capsys, "open", target)[1]["error"]["code"] == "file_action_failed"
    monkeypatch.setattr(backend.shutil, "which", lambda name: None)
    assert response(capsys, "open", target)[0] == 3
    assert response(capsys, "open", "relative")[0] == 2


def test_open_timeout_is_unconfirmed_without_killing_application(desktop, monkeypatch, capsys):
    target, _ = desktop

    def wait(timeout):
        raise subprocess.TimeoutExpired("gio", timeout)

    # No terminate/kill method: an unconfirmed request must not kill launched apps.
    monkeypatch.setattr(backend.subprocess, "Popen", lambda *a, **k: SimpleNamespace(wait=wait))
    code, data = response(capsys, "open", target)
    assert code == 5 and data["error"]["code"] == "file_action_timeout"
