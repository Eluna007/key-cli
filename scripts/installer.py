#!/usr/bin/env python3
"""Explicit source deployment and optional configuration; no daemon or package manager."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import venv

BASE = Path(__file__).resolve().parent.parent
RULE = "71-apollo-keyboard-leds.rules"
UNIT = "apollo-clipboard.service"


def run(argv):
    subprocess.run([str(x) for x in argv], check=True)


def fingerprint(path):
    if path.is_symlink():
        return {"link": os.readlink(path)}
    if path.is_file():
        return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return None


def safe_path(path):
    for parent in (path.parent, *path.parents):
        if parent.is_symlink():
            raise ValueError(f"Symlink parent is not allowed: {parent}")
    if path.exists() and path.is_dir():
        raise ValueError(f"Expected a file: {path}")


def atomic(path, data):
    safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".key-cli-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class OwnedFiles:
    def __init__(self, manifest, allowed, root, mode):
        if root == Path("/") and os.geteuid() == 0:
            for parent in (manifest, *manifest.parents):
                if parent.exists():
                    info = parent.stat()
                    if parent.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
                        raise ValueError(
                            f"Untrusted installation metadata directory/file: {parent}"
                        )
        self.path, self.allowed, self.root, self.mode = manifest, set(allowed), root, mode
        safe_path(manifest)
        if manifest.is_symlink():
            raise ValueError(f"Manifest must not be a symlink: {manifest}")
        self.data = {"mode": mode, "root": str(root), "files": {}}
        if manifest.exists():
            self.data = json.loads(manifest.read_text())
            if self.data.get("mode") != mode or self.data.get("root") != str(root):
                raise ValueError("Installation manifest root/mode mismatch")
            if not set(self.data["files"]) <= {str(p) for p in self.allowed}:
                raise ValueError("Manifest contains unapproved paths")

    def check(self, path):
        if path not in self.allowed:
            raise ValueError(f"Unapproved path: {path}")
        safe_path(path)
        actual = fingerprint(path)
        old = self.data["files"].get(str(path))
        if (path.exists() or path.is_symlink()) and (not old or actual != old):
            raise ValueError(f"Unknown or modified file; preserved: {path}")

    def save(self):
        atomic(self.path, (json.dumps(self.data, indent=2) + "\n").encode())

    def write(self, path, data=None, link=None):
        self.check(path)
        if link is None:
            atomic(path, data)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.unlink(missing_ok=True)
            path.symlink_to(link)
        self.data["files"][str(path)] = fingerprint(path)
        self.save()

    def remove(self):
        # Keep the saved uninstaller usable if any resource needs manual review.
        valid = True
        for name in self.data["files"]:
            try:
                self.check(Path(name))
            except ValueError as exc:
                print(exc, file=sys.stderr)
                valid = False
        if not valid:
            return False
        for name in list(self.data["files"]):
            Path(name).unlink(missing_ok=True)
            del self.data["files"][name]
            self.save()
        self.path.unlink(missing_ok=True)
        return True


def layout(root):
    prefix = root / "usr/local"
    share = prefix / "share/key-cli"
    resources = {
        prefix / "lib/systemd/user" / UNIT: BASE / "systemd/user" / UNIT,
        prefix / "share/fish/vendor_completions.d/key.fish": BASE / "completions/key.fish",
        share / "installer.py": Path(__file__).resolve(),
        share / "systemd/user" / UNIT: BASE / "systemd/user" / UNIT,
        share / "packaging/udev" / RULE: BASE / "packaging/udev" / RULE,
        share / "completions/key.fish": BASE / "completions/key.fish",
    }
    # Installed copy is standalone; its resources live alongside it.
    if (Path(__file__).parent / "systemd").exists():
        resources = {
            p: Path(__file__).parent / s.relative_to(BASE) if s != Path(__file__).resolve() else s
            for p, s in resources.items()
        }
    return prefix, share, resources


def unit_override(key, arguments):
    # systemd command quoting (not shell quoting): escape specifiers and env expansion.
    value = str(key).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    if any(c in value for c in "\n\r\0"):
        raise ValueError("Invalid unit executable path")
    return f'[Service]\nExecStart=\nExecStart="{value}" {arguments}\n'.encode()


def dev_services(args):
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    if not config.is_absolute():
        raise ValueError("XDG_CONFIG_HOME must be absolute")
    user = config / "systemd/user"
    paths = [
        user / UNIT,
        user / f"{UNIT}.d/80-key-cli-development.conf",
        user / "apollo-shell.service.d/80-key-cli-development.conf",
    ]
    owned = OwnedFiles(user / "key-cli-development.json", paths, config, "development")
    if args.dev_services == "disable":
        if not owned.remove():
            raise ValueError("Modified development configuration was preserved")
    else:
        key = BASE / ".venv/bin/key"
        if not key.is_file():
            raise ValueError("Create .venv and pip install -e '.[dev]' first")
        # A loaded unit, including a user unit, should be reused, never replaced.
        probe = subprocess.run(
            ["systemctl", "--user", "show", UNIT, "--property=LoadState", "--value"],
            capture_output=True,
            text=True,
            check=False,
        )
        base_exists = probe.returncode == 0 and probe.stdout.strip() == "loaded"
        if not base_exists and not paths[0].exists():
            owned.write(paths[0], (BASE / "systemd/user" / UNIT).read_bytes())
        owned.write(paths[1], unit_override(key, "clipboard watch"))
        if args.apollo_unit:
            source = Path(args.apollo_unit).resolve()
            if source.name != "apollo-shell.service" or not source.is_file():
                raise ValueError("--apollo-unit must name Apollo's existing apollo-shell.service")
            # Keep ownership of Shell's base unit in the Apollo repository.
            print(
                f"If the base unit is not installed, run: systemctl --user link {shlex.quote(str(source))}"
            )
            owned.write(paths[2], unit_override(key, "shell --foreground --no-duplicate"))
    print(
        "Configuration saved. Run systemctl --user daemon-reload; restart only the services you intend to switch."
    )
    escaped = str(BASE / ".venv/bin").replace("\\", "\\\\").replace("'", "\\'")
    print(f"Optional fish PATH: fish_add_path --universal --move '{escaped}'")


def keyboard(args):
    prefix, share, resources = layout(args.root)
    target = args.root / "etc/udev/rules.d" / RULE
    owned = OwnedFiles(share / "keyboard-manifest.json", [target], args.root, "keyboard")
    if args.keyboard == "disable":
        if not owned.remove():
            raise ValueError("Modified rule preserved")
        print(
            "Persistent installer rule removed. Existing ACLs and open fds are NOT revoked. Check other rules/input group; reconnect devices and log in again (or reboot), then verify ACLs and key keyboard status."
        )
        return
    if not args.acknowledge_keyboard_access:
        raise ValueError(
            "Keyboard authorization grants whole event-device access, including raw keys, to the active user, not LED-only or Apollo-only. Repeat with --acknowledge-keyboard-access to opt in."
        )
    source = resources[share / "packaging/udev" / RULE].read_bytes()
    # Never adopt someone else's rule. Respect /etc masking and package-provided rules.
    if str(target) not in owned.data["files"]:
        for directory in ("etc", "run", "usr/local/lib", "usr/lib"):
            path = args.root / directory / "udev/rules.d" / RULE
            if path.exists() or path.is_symlink():
                if not path.is_symlink() and path.read_bytes() == source:
                    print(f"Existing equivalent rule retained, not owned: {path}")
                    return
                raise ValueError(f"Existing rule requires manual review: {path}")
    changed = fingerprint(target) != {"sha256": hashlib.sha256(source).hexdigest()}
    owned.write(target, source)
    if changed and args.apply:
        if args.root != Path("/"):
            raise ValueError("--apply cannot target a test root")
        run(["udevadm", "control", "--reload-rules"])
        run(["udevadm", "trigger", "--action=change", "--subsystem-match=input"])
        run(["udevadm", "settle"])
    elif changed:
        print(
            "Rule saved; reconnect/relogin or explicitly reload/trigger udev to apply. No device changes were made."
        )


def deploy(args):
    prefix, share, resources = layout(args.root)
    entry = prefix / "bin/key"
    uninstaller = share / "uninstall.sh"
    environment = prefix / "lib/key-cli/venv"
    owned = OwnedFiles(
        share / "install-manifest.json", [*resources, entry, uninstaller], args.root, "source"
    )
    if args.root == Path("/"):
        for path in (share, environment.parent, entry.parent):
            for parent in (path, *path.parents):
                if parent.exists():
                    info = parent.stat()
                    if parent.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
                        raise ValueError(f"Untrusted installation directory: {parent}")
        if owned.path.exists() and (
            owned.path.stat().st_uid != 0 or owned.path.stat().st_mode & 0o022
        ):
            raise ValueError("Untrusted installation manifest")
    if args.uninstall:
        # Validate the program directory independently of manifest-supplied paths.
        if owned.data.get("venv") != str(environment):
            raise ValueError("No owned source installation at this root")
        safe_path(environment / "ownership-check")
        if not owned.remove():
            raise ValueError("Modified resources preserved; installation retained for review")
        if environment.exists():
            shutil.rmtree(environment)
        print(
            "Source installation removed; user data and optional keyboard authorization retained."
        )
        return
    for path in [*resources, entry, uninstaller]:
        owned.check(path)
    safe_path(environment / "ownership-check")
    if environment.exists() and owned.data.get("venv") != str(environment):
        raise ValueError(f"Unknown environment preserved: {environment}")
    if not args.wheelhouse:
        raise ValueError("Missing prepared wheels")
    # Build only as caller; deployment uses wheels without network or build hooks.
    wheels = sorted(Path(args.wheelhouse).glob("*.whl"))
    if not wheels:
        raise ValueError("No prepared wheels")
    contents = {target: source.read_bytes() for target, source in resources.items()}
    print("Deploying prepared wheels into final environment...", flush=True)
    if environment.exists():
        shutil.rmtree(environment)
    owned.data["venv"] = str(environment)
    owned.save()
    venv.EnvBuilder(with_pip=True).create(environment)
    run(
        [
            environment / "bin/python",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--no-index",
            "--no-deps",
            "--force-reinstall",
            *wheels,
        ]
    )
    version = subprocess.check_output(
        [
            environment / "bin/python",
            "-c",
            'from importlib.metadata import version; print(version("key-cli"))',
        ],
        text=True,
    ).strip()
    owned.data["version"] = version
    for target, data in contents.items():
        if target == prefix / "lib/systemd/user" / UNIT:
            data = data.replace(
                b"ExecStart=key clipboard watch",
                unit_override(entry, "clipboard watch").split(b"ExecStart=\n", 1)[1].strip(),
            )
        owned.write(target, data)
    owned.write(entry, link=str(environment / "bin/key"))
    owned.write(
        uninstaller, b'#!/bin/sh\nexec python3 "$(dirname -- "$0")/installer.py" --uninstall "$@"\n'
    )
    os.chmod(uninstaller, 0o755)
    print(
        "Source installation complete. No services started or permissions changed. Check development PATH and unit overrides before switching versions."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--uninstall", action="store_true")
    action.add_argument("--dev-services", choices=["enable", "disable"])
    action.add_argument("--keyboard", choices=["enable", "disable"])
    action.add_argument("--clipboard", choices=["enable", "disable"])
    parser.add_argument(
        "--apollo-unit", help="Apollo-owned base unit for optional development override"
    )
    parser.add_argument("--acknowledge-keyboard-access", action="store_true")
    parser.add_argument(
        "--apply", action="store_true", help="Apply a newly added/changed keyboard rule now"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/"),
        help="Test installation root; never apply services/udev here",
    )
    parser.add_argument("--deploy", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--wheelhouse", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.keyboard == "enable" and not args.acknowledge_keyboard_access:
            raise ValueError(
                "Whole keyboard event-device access includes raw keys and is not LED-only or Apollo-only. Opt in with --acknowledge-keyboard-access."
            )
        if args.apply and (args.keyboard != "enable" or args.root != Path("/")):
            raise ValueError("--apply requires --keyboard enable at the real system root")
        if args.apollo_unit and args.dev_services != "enable":
            raise ValueError("--apollo-unit requires --dev-services enable")
        if not args.root.is_absolute() or args.root != args.root.resolve():
            raise ValueError("Root must be an absolute, canonical directory")
        if os.geteuid() == 0 and not args.deploy:
            raise ValueError(
                "Start this tool as your desktop user, without sudo. It elevates only deployment; root cannot configure user services."
            )
        if args.deploy:
            os.umask(0o022)
        if args.deploy and (args.dev_services or args.clipboard):
            raise ValueError("User configuration cannot use privileged deployment")
        if args.dev_services:
            dev_services(args)
        elif args.clipboard:
            if args.root != Path("/"):
                raise ValueError("Services cannot target a test root")
            run(["systemctl", "--user", "daemon-reload"])
            if args.clipboard == "enable":
                run(["systemctl", "--user", "is-active", "niri.service"])
            run(
                [
                    "systemctl",
                    "--user",
                    "enable" if args.clipboard == "enable" else "disable",
                    "--now",
                    UNIT,
                ]
            )
        elif args.deploy or args.root != Path("/") and (args.uninstall or args.keyboard):
            keyboard(args) if args.keyboard else deploy(args)
        else:
            with tempfile.TemporaryDirectory(prefix="key-cli-install-") as temporary:
                if not args.uninstall and not args.keyboard:
                    missing = [
                        name
                        for name in (
                            "qs",
                            "cliphist",
                            "wl-paste",
                            "wl-copy",
                            "ffmpeg",
                            "ffprobe",
                            "pactl",
                            "gpu-screen-recorder",
                        )
                        if not shutil.which(name)
                    ]
                    if missing:
                        print(
                            "Optional features need external tools (install separately): "
                            + ", ".join(missing)
                        )
                    print(
                        "Building current source and dependencies as the calling user...",
                        flush=True,
                    )
                    # A fresh build frontend does not require modifying the checkout venv.
                    source = Path(temporary) / "source"
                    shutil.copytree(
                        BASE,
                        source,
                        ignore=shutil.ignore_patterns(
                            ".git",
                            ".venv",
                            "build",
                            "dist",
                            "*.egg-info",
                            "__pycache__",
                            ".pytest_cache",
                            ".ruff_cache",
                        ),
                    )
                    builder = Path(temporary) / "builder"
                    venv.EnvBuilder(with_pip=True).create(builder)
                    run(
                        [
                            builder / "bin/python",
                            "-m",
                            "pip",
                            "wheel",
                            "--no-cache-dir",
                            "--wheel-dir",
                            temporary,
                            source,
                        ]
                    )
                    args.wheelhouse = temporary
                command = [
                    sys.executable,
                    Path(__file__).resolve(),
                    "--deploy",
                    "--root",
                    args.root,
                ]
                if args.uninstall:
                    command += ["--uninstall"]
                if args.keyboard:
                    command += ["--keyboard", args.keyboard]
                    if args.acknowledge_keyboard_access:
                        command += ["--acknowledge-keyboard-access"]
                    if args.apply:
                        command += ["--apply"]
                if args.wheelhouse:
                    command += ["--wheelhouse", args.wheelhouse]
                if args.root == Path("/"):
                    # Use system Python, not a writable development interpreter under sudo.
                    command[0] = "/usr/bin/python3"
                    command = ["sudo", *([] if sys.stdin.isatty() else ["-n"]), *command]
                run(command)
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(
            f"Installation/configuration failed: {exc}. Earlier completed steps may remain; inspect the manifest before retrying.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
