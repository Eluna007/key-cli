from __future__ import annotations

import platform
import shutil
import subprocess
import os
from pathlib import Path
from ..keyboard.backend import responses
from ..clipboard.backend import watcher_running
from typing import Any

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
        "installation": {"keyPath": shutil.which("key"), "overrides": overrides},
        "runtimeReady": runtime_ready,
    }
    text = "key dependencies (not runtime readiness): " + (
        "ready" if not missing else "missing " + ", ".join(missing)
    )
    return Result(0 if not missing else DEPENDENCY_FAILURE, "doctor", payload, text, bool(missing))
