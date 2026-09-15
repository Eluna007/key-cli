"""Desktop request contracts through real GIO and isolated associations/tools."""

import json
from pathlib import Path
import shutil
import sys
import time

import pytest

from key_cli import main


@pytest.fixture
def isolated_desktop(tmp_path, monkeypatch):
    gio = shutil.which("gio")
    if not gio:
        pytest.skip("GIO desktop integration requires the declared glib2 runtime")
    bins = tmp_path / "bin"
    bins.mkdir()
    (bins / "gio").symlink_to(gio)
    data = tmp_path / "data"
    apps = data / "applications"
    apps.mkdir(parents=True)
    config = tmp_path / "config"
    config.mkdir()
    system = tmp_path / "system"
    system.mkdir()
    # Only MIME definitions, never the host's application catalog or associations.
    mime = Path("/usr/share/mime")
    if mime.is_dir():
        (system / "mime").symlink_to(mime)
    for name, value in {
        "HOME": tmp_path,
        "XDG_CONFIG_HOME": config,
        "XDG_CONFIG_DIRS": tmp_path / "empty",
        "XDG_DATA_HOME": data,
        "XDG_DATA_DIRS": system,
        "XDG_CACHE_HOME": tmp_path / "cache",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + str(tmp_path / "no-bus"),
        "PATH": bins,
        "FIXTURE_ROOT": tmp_path,
        "XDG_CURRENT_DESKTOP": "niri",
    }.items():
        monkeypatch.setenv(name, str(value))
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "GIO_USE_PORTALS", "GIO_LAUNCH_DESKTOP"):
        monkeypatch.delenv(name, raising=False)
    helper = bins / "xdg-terminal-exec"
    helper.write_text(
        f"#!{sys.executable}\n"
        "import os,pty,subprocess,sys\n"
        "from pathlib import Path\n"
        "root=Path(os.environ['FIXTURE_ROOT'])\n"
        "master,slave=pty.openpty()\n"
        "try:\n"
        " child=subprocess.Popen(sys.argv[1:],stdin=slave,stdout=slave,stderr=slave)\n"
        " child.wait(timeout=15)\n"
        "finally:\n"
        " os.close(slave); os.close(master)\n"
        " (root/'terminal-done').touch()\n"
    )
    helper.chmod(0o755)
    handler = bins / "fixture-editor"
    handler.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys,time\n"
        "from pathlib import Path\n"
        "root=Path(os.environ['FIXTURE_ROOT'])\n"
        "(root/'opened.json').write_text(json.dumps({'argv':sys.argv[1:],'tty':os.isatty(0),'handler':Path(sys.argv[0]).name}))\n"
        "deadline=time.monotonic()+10\n"
        "while not (root/'release').exists() and time.monotonic()<deadline: time.sleep(.01)\n"
        "(root/'app-done').touch()\n"
    )
    handler.chmod(0o755)
    (apps / "fixture.desktop").write_text(
        "[Desktop Entry]\nName=Fixture\nType=Application\nTerminal=true\n"
        "Exec=fixture-editor %f\nMimeType=text/plain;text/markdown;application/json;inode/directory;\n"
    )
    player = bins / "fixture-player"
    player.write_text(handler.read_text())
    player.chmod(0o755)
    (apps / "player.desktop").write_text(
        "[Desktop Entry]\nName=Player\nType=Application\nTerminal=false\n"
        "Exec=fixture-player %f\nMimeType=video/mp4;\n"
    )
    scheme = bins / "fixture-scheme"
    scheme.write_text(
        f"#!{sys.executable}\nimport os\nfrom pathlib import Path\n"
        "(Path(os.environ['FIXTURE_ROOT'])/'scheme-called').touch()\n"
    )
    scheme.chmod(0o755)
    (apps / "scheme.desktop").write_text(
        "[Desktop Entry]\nName=URI handler\nType=Application\nTerminal=false\n"
        "Exec=fixture-scheme %u\nMimeType=x-scheme-handler/file;\n"
    )
    (config / "mimeapps.list").write_text(
        "[Default Applications]\nx-scheme-handler/file=scheme.desktop;\nvideo/mp4=player.desktop;\n"
        + "".join(
            mime + "=fixture.desktop;\n"
            for mime in ("text/plain", "text/markdown", "application/json", "inode/directory")
        )
    )
    yield tmp_path
    (tmp_path / "release").touch()
    if (tmp_path / "opened.json").exists():
        opened = json.loads((tmp_path / "opened.json").read_text())
        wait_for(tmp_path / ("terminal-done" if opened["tty"] else "app-done"))


def wait_for(path):
    deadline = time.monotonic() + 5
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.exists(), f"Timed out waiting for fixture {path.name}"


@pytest.mark.parametrize("kind", ["json", "md", "directory", "reveal-fallback"])
def test_terminal_associations_return_before_application_exit(isolated_desktop, capsys, kind):
    root = isolated_desktop
    target = root / ('中文 " # % ? ' + kind)
    action = "open"
    if kind == "directory":
        target.mkdir()
    else:
        target = target.with_suffix(".json" if kind == "json" else ".md")
        target.write_text("{}" if kind == "json" else "# Markdown\n")
    if kind == "reveal-fallback":
        action = "reveal"
    assert main(["file", action, "--", str(target)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] and data["mode"] == ("directory" if action == "reveal" else "open")
    wait_for(root / "opened.json")
    opened = json.loads((root / "opened.json").read_text())
    assert opened == {
        "argv": [str(target.parent if action == "reveal" else target)],
        "tty": True,
        "handler": "fixture-editor",
    }
    assert not (root / "scheme-called").exists()
    assert not (root / "app-done").exists(), "Open must not wait for application exit"


def test_real_gio_launch_failure_is_not_success(isolated_desktop, capsys):
    root = isolated_desktop
    # A valid association with an unavailable executable must be a protocol error.
    (root / "bin/fixture-editor").unlink()
    target = root / "sample.json"
    target.write_text("{}")
    assert main(["file", "open", "--", str(target)]) == 5
    data = json.loads(capsys.readouterr().out)
    assert not data["ok"] and data["error"]["code"] == "file_action_failed"
    assert not (root / "opened.json").exists()


def test_video_uses_mime_player_not_file_uri_handler(isolated_desktop, capsys):
    root = isolated_desktop
    target = root / '中文 # % ? " movie.mp4'
    target.write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42")
    assert main(["file", "open", "--", str(target)]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "open"
    wait_for(root / "opened.json")
    assert json.loads((root / "opened.json").read_text()) == {
        "argv": [str(target)],
        "tty": False,
        "handler": "fixture-player",
    }
    assert not (root / "scheme-called").exists()
    assert not (root / "app-done").exists()


def test_missing_mime_app_does_not_fall_back_to_file_uri_handler(isolated_desktop, capsys):
    root = isolated_desktop
    (root / "data/applications/player.desktop").unlink()
    target = root / "movie.mp4"
    target.write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42")
    assert main(["file", "open", "--", str(target)]) == 5
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "file_action_failed"
    assert not (root / "scheme-called").exists()
