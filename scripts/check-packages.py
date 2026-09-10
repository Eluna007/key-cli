#!/usr/bin/env python3
"""Check the installed file/permission boundaries in the two Arch package artifacts."""

import configparser
import subprocess
import sys
from pathlib import Path


def files(package):
    return set(subprocess.check_output(["bsdtar", "-tf", package], text=True).splitlines())


def read(package, name):
    return subprocess.check_output(["bsdtar", "-xOf", package, name])


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: check-packages.py MAIN_PACKAGE ACCESS_PACKAGE")
    main_package, access_package = sys.argv[1:]
    main_files, access_files = files(main_package), files(access_package)
    rule = "usr/lib/udev/rules.d/71-clavis-keyboard-leds.rules"
    unit = "usr/lib/systemd/user/clavis-clipboard.service"
    assert unit in main_files and "usr/bin/key" in main_files
    assert any(name.endswith("key_cli/keyboard/backend.py") for name in main_files)
    assert not any("/udev/" in name for name in main_files)
    assert rule in access_files
    assert unit not in access_files and "usr/bin/key" not in access_files
    assert not any("site-packages/" in name for name in access_files)
    for names in (main_files, access_files):
        assert ".INSTALL" not in names
        assert not any(name.startswith(("etc/", "home/")) for name in names)
    root = Path(__file__).resolve().parents[1]
    assert read(access_package, rule) == (root / "packaging/udev" / Path(rule).name).read_bytes()
    assert read(main_package, unit) == (root / "systemd/user" / Path(unit).name).read_bytes()
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(read(main_package, unit).decode())
    assert config["Service"]["ExecStart"] == "key clipboard watch"
    assert config["Install"]["WantedBy"] == "niri.service"
    metadata = read(main_package, ".PKGINFO").decode().splitlines()
    for dependency in ("python-evdev", "python-pyudev", "cliphist", "wl-clipboard"):
        assert f"depend = {dependency}" in metadata
    assert not any(line == "depend = key-cli-keyboard-access" for line in metadata)
    print("Arch package boundaries and runtime dependencies verified")


if __name__ == "__main__":
    main()
