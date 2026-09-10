from __future__ import annotations

import platform
import shutil
import subprocess
import os
import sys
from pathlib import Path
from ..keyboard.backend import responses
from ..clipboard.backend import watcher_running
from typing import Any

from ..utils.executable import current_key_executable
from ..utils.output import DEPENDENCY_FAILURE, Result


COMMANDS = {
    "qs": {"features": ["shell", "ipc"]},
    "gpu-screen-recorder": {"features": ["record"]},
    "slurp": {"features": ["record-region"]},
    "ffmpeg": {"features": ["audio", "record-gif"]},
    "ffprobe": {"features": ["audio-validation"]},
    "pactl": {"features": ["audio-source-resolution"]},
    "cliphist": {"features": ["clipboard-list", "clipboard-store"]},
    "wl-copy": {"features": ["clipboard-restore"]},
    "wl-paste": {"features": ["clipboard-store", "clipboard-watch"]},
}


def safe_version(program: str) -> str | None:
    path = shutil.which(program)
    if not path:
        return None
    for option in ("--version", "-V", "version"):
        try:
            process = subprocess.run(
                [path, option], capture_output=True, text=True, timeout=2, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if process.returncode != 0:
            continue
        text = (process.stdout or process.stderr).strip().splitlines()
        if text:
            return text[0][:240]
    return None


def installation_details():
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    units = {}
    for unit in ("clavis-clipboard.service", "clavis-shell.service"):
        try:
            probe = subprocess.run(
                [
                    "systemctl",
                    "--user",
                    "show",
                    unit,
                    "--property=FragmentPath,DropInPaths,ExecStart",
                ],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            units[unit] = dict(
                line.split("=", 1) for line in probe.stdout.splitlines() if "=" in line
            )
        except (OSError, subprocess.TimeoutExpired):
            units[unit] = {}
    resources = []
    for directory in (
        "/etc/udev/rules.d",
        "/run/udev/rules.d",
        "/usr/local/lib/udev/rules.d",
        "/usr/lib/udev/rules.d",
    ):
        path = Path(directory) / "71-clavis-keyboard-leds.rules"
        if path.exists() or path.is_symlink():
            resources.append(
                {
                    "path": str(path),
                    "symlinkTarget": os.readlink(path) if path.is_symlink() else None,
                }
            )
    return {
        "keyPath": shutil.which("key"),  # preserved legacy field: PATH default
        "invocation": sys.argv[0],
        "currentKey": (
            None
            if sys.argv[0] in {"-c", "", "-"} or sys.argv[0].endswith("/__main__.py")
            else current_key_executable(prefer_environment=False)
        ),
        "pythonExecutable": sys.executable,
        "modulePath": str(Path(__file__).resolve().parents[1]),
        "clavisKey": os.environ.get("CLAVIS_KEY"),
        "userUnits": units,
        "keyboardRules": resources,  # highest precedence first
        "sourceManifest": "/usr/local/share/key-cli/install-manifest.json"
        if Path("/usr/local/share/key-cli/install-manifest.json").is_file()
        else None,
        "developmentManifest": str(config / "systemd/user/key-cli-development.json")
        if (config / "systemd/user/key-cli-development.json").is_file()
        else None,
    }


def run(args) -> Result:
    commands: dict[str, Any] = {}
    missing: list[str] = []
    for name, metadata in COMMANDS.items():
        path = shutil.which(name)
        value = {
            "available": path is not None,
            "path": path,
            "version": safe_version(name),
            "features": metadata["features"],
        }
        commands[name] = value
        if path is None:
            missing.append(name)
    features = {
        "shell": commands["qs"]["available"],
        "ipc": commands["qs"]["available"],
        "record": commands["gpu-screen-recorder"]["available"],
        "record-gif": commands["gpu-screen-recorder"]["available"]
        and commands["ffmpeg"]["available"],
        "record-region": commands["gpu-screen-recorder"]["available"]
        and commands["slurp"]["available"],
        "audio": all(commands[name]["available"] for name in ("ffmpeg", "ffprobe", "pactl")),
        "clipboard-list": commands["cliphist"]["available"],
        "clipboard-restore": all(commands[name]["available"] for name in ("cliphist", "wl-copy")),
        "clipboard-watch": all(commands[name]["available"] for name in ("cliphist", "wl-paste")),
    }
    keyboard = next(responses()).json()
    watching = watcher_running()
    services = {}
    for unit in ("niri.service", "clavis-clipboard.service"):
        try:
            probe = subprocess.run(
                ["systemctl", "--user", "is-active", unit],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            services[unit] = probe.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            services[unit] = False
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    overrides = [
        str(path)
        for path in (
            Path("/etc/udev/rules.d/71-clavis-keyboard-leds.rules"),
            config / "systemd/user/clavis-clipboard.service",
            Path("/usr/local/lib/systemd/user/clavis-clipboard.service"),
        )
        if path.exists() or path.is_symlink()
    ]
    features["keyboard"] = keyboard["available"]
    runtime_ready = keyboard["available"] and watching and all(services.values())
    payload = {
        "schemaVersion": 1,
        "platform": platform.platform(),
        "commands": commands,
        "features": features,
        "missing": missing,
        "keyboard": keyboard,
        "clipboard": {"watcherRunning": watching, "services": services},
        "installation": {**installation_details(), "overrides": overrides},
        "runtimeReady": runtime_ready,
    }
    text = "key dependencies (not runtime readiness): " + (
        "ready" if not missing else "missing " + ", ".join(missing)
    )
    return Result(0 if not missing else DEPENDENCY_FAILURE, "doctor", payload, text, bool(missing))
