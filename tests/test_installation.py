"""Ownership and configuration contracts using only temporary roots and fake systemctl."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "installer", Path(__file__).parents[1] / "scripts/installer.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_unknown_modified_and_unapproved_files_are_preserved(tmp_path):
    target = tmp_path / "entry"
    manifest = tmp_path / "manifest.json"
    owned = installer.OwnedFiles(manifest, [target], tmp_path, "test")
    target.write_text("someone else")
    with pytest.raises(ValueError):
        owned.write(target, b"ours")
    assert target.read_text() == "someone else"
    target.unlink()
    owned.write(target, b"ours")
    owned.write(target, b"updated")
    target.write_text("user edit")
    assert not owned.remove()
    assert target.read_text() == "user edit"
    data = json.loads(manifest.read_text())
    data["files"]["/etc/passwd"] = {"sha256": "fake"}
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        installer.OwnedFiles(manifest, [target], tmp_path, "test")


def test_symlink_parent_cannot_redirect_write(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    link = tmp_path / "link"
    link.symlink_to(other, target_is_directory=True)
    owned = installer.OwnedFiles(tmp_path / "manifest", [link / "file"], tmp_path, "test")
    with pytest.raises(ValueError):
        owned.write(link / "file", b"no")
    assert not (other / "file").exists()


def test_development_configuration_without_base_and_retraction(tmp_path, monkeypatch):
    repo = tmp_path / "source with spaces $d %n"
    key = repo / ".venv/bin/key"
    key.parent.mkdir(parents=True)
    key.touch()
    source = repo / "systemd/user" / installer.UNIT
    source.parent.mkdir(parents=True)
    source.write_bytes((installer.BASE / "systemd/user" / installer.UNIT).read_bytes())
    config = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setattr(installer, "BASE", repo)
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="not-found\n"),
    )
    args = SimpleNamespace(dev_services="enable", apollo_unit=None)
    installer.dev_services(args)
    user = config / "systemd/user"
    override = user / f"{installer.UNIT}.d/80-key-cli-development.conf"
    # Verify the generated systemd artifact, not Python/QML source structure.
    assert str(key).replace("$", "$$").replace("%", "%%") in override.read_text()
    assert (user / installer.UNIT).is_file()
    custom = override.parent / "90-user.conf"
    custom.write_text("[Service]\nRestartSec=10\n")
    installer.dev_services(args)
    installer.dev_services(SimpleNamespace(dev_services="disable", apollo_unit=None))
    assert custom.exists()
    assert not override.exists()
    assert not (user / installer.UNIT).exists()


def test_existing_base_is_not_adopted(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="loaded\n"),
    )
    # Actual development venv is not a test dependency.
    repo = tmp_path / "repo"
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/key").touch()
    monkeypatch.setattr(installer, "BASE", repo)
    installer.dev_services(SimpleNamespace(dev_services="enable", apollo_unit=None))
    assert not (tmp_path / "systemd/user" / installer.UNIT).exists()


def test_keyboard_is_independent_idempotent_and_does_not_adopt_package_rule(tmp_path):
    args = SimpleNamespace(
        root=tmp_path, keyboard="enable", acknowledge_keyboard_access=False, apply=False
    )
    with pytest.raises(ValueError):
        installer.keyboard(args)
    args.acknowledge_keyboard_access = True
    rule = tmp_path / "usr/lib/udev/rules.d" / installer.RULE
    rule.parent.mkdir(parents=True)
    rule.write_bytes((installer.BASE / "packaging/udev" / installer.RULE).read_bytes())
    installer.keyboard(args)
    assert not (tmp_path / "etc/udev/rules.d" / installer.RULE).exists()
    args.keyboard = "disable"
    installer.keyboard(args)
    assert rule.exists()
    rule.unlink()
    args.keyboard = "enable"
    installer.keyboard(args)
    installer.keyboard(args)
    target = tmp_path / "etc/udev/rules.d" / installer.RULE
    assert target.exists()
    args.keyboard = "disable"
    installer.keyboard(args)
    assert not target.exists()


def test_install_build_failure_does_not_touch_old_install(tmp_path, monkeypatch, capsys):
    marker = tmp_path / "usr/local/bin/key"
    marker.parent.mkdir(parents=True)
    marker.write_text("old")
    monkeypatch.setattr(installer.sys, "argv", ["install", "--root", str(tmp_path)])
    monkeypatch.setattr(installer.os, "geteuid", lambda: 1000)

    def fail(_self, _path):
        raise OSError("venv unavailable")

    monkeypatch.setattr(installer.venv.EnvBuilder, "create", fail)
    assert installer.main() == 1
    assert marker.read_text() == "old"
    assert "installation complete" not in capsys.readouterr().out


def test_doctor_distinguishes_invocation_and_path_default(tmp_path, monkeypatch):
    from key_cli.commands import doctor

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APOLLO_KEY", "/selected/shell/key")
    monkeypatch.setattr(doctor.sys, "argv", ["/development/.venv/bin/key"])
    monkeypatch.setattr(doctor, "current_key_executable", lambda **kw: "/development/.venv/bin/key")
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/key")
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout="FragmentPath=/usr/local/lib/systemd/user/apollo-clipboard.service\nDropInPaths=/user/dev.conf\nExecStart=development-key\n",
        ),
    )
    result = doctor.installation_details()
    assert result["keyPath"] == "/usr/bin/key"
    assert result["currentKey"] == result["invocation"] == "/development/.venv/bin/key"
    assert result["apolloKey"] == "/selected/shell/key"
    assert result["pythonExecutable"]
    assert result["modulePath"].endswith("key_cli")
    assert result["userUnits"]["apollo-clipboard.service"]["DropInPaths"] == "/user/dev.conf"
