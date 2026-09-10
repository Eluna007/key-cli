"""One-shot file actions. Never execute paths or desktop entries as shell code."""

from __future__ import annotations

import configparser
import os
from pathlib import Path
import shlex
import shutil
import subprocess

from ..utils.output import fail, ok


def directory_application():
    query = subprocess.run(
        ["xdg-mime", "query", "default", "inode/directory"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    desktop_id = query.stdout.strip()
    if (
        query.returncode
        or not desktop_id
        or "/" in desktop_id
        or not desktop_id.endswith(".desktop")
    ):
        raise ValueError("Could not determine the default file manager")
    roots = [os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")]
    roots += (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    for directory in roots:
        if not Path(directory).is_absolute():
            continue
        applications = Path(directory) / "applications"
        # Desktop IDs encode subdirectories with '-'. Preserve XDG precedence.
        candidates = [applications / desktop_id]
        candidates += (
            []
            if candidates[0].is_file()
            else [
                p
                for p in applications.rglob("*.desktop")
                if str(p.relative_to(applications)).replace("/", "-") == desktop_id
            ]
        )
        for path in candidates:
            if not path.is_file():
                continue
            entry = configparser.ConfigParser(interpolation=None, strict=False)
            entry.read(path, encoding="utf-8")
            desktop = entry["Desktop Entry"]
            if desktop.getboolean("Hidden", fallback=False):
                raise ValueError("The default file manager is hidden")
            return shlex.split(desktop.get("Exec", "")), desktop.getboolean(
                "Terminal", fallback=False
            )
    raise ValueError("The default file manager desktop entry was not found")


def run(args):
    command = f"file.{args.action}"
    try:
        path = Path(args.path)
        if not path.is_absolute() or "\0" in args.path:
            return fail(command, 2, "invalid_path", "An absolute local file path is required")
        # abspath normalizes dots without resolving symlinks to a different directory.
        path = Path(os.path.abspath(path))
        exists = path.is_file()
        mode = "open"
        if args.action == "open":
            if not exists:
                return fail(
                    command, 5, "file_missing", "The saved file no longer exists", path=str(path)
                )
            argv = ["xdg-open", str(path)]
        else:
            if not path.parent.is_dir():
                return fail(
                    command,
                    5,
                    "directory_missing",
                    "The containing directory no longer exists",
                    path=str(path),
                )
            entry, terminal = directory_application()
            program = Path(entry[0]).name if entry else ""
            # Only adapt standard entries; custom launchers keep their own defaults.
            standard = len(entry) == 2 and entry[1] in {"%f", "%F", "%u", "%U"}
            mode = (
                "reveal"
                if exists and standard and program in {"yazi", "dolphin", "nautilus"}
                else "directory"
            )
            if mode == "reveal":
                argv = (
                    [entry[0], "--", str(path)]
                    if program == "yazi"
                    else [entry[0], "--select", str(path)]
                )
                terminal = terminal or program == "yazi"
            else:
                argv = ["xdg-open", str(path.parent)]
            if terminal:
                argv = ["xdg-terminal-exec", "--", *argv]
        programs = [argv[0], entry[0] if mode == "reveal" else "xdg-open"]
        for program in programs:
            if not shutil.which(program):
                return fail(
                    command, 3, "dependency_missing", f"{program} is not installed", path=str(path)
                )
        # A terminal/file manager can remain alive until its window closes. Report
        # dispatch, not completion or proof of focus; do not wait for the window.
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return ok(command, "File action dispatched", path=str(path), mode=mode, fileExists=exists)
    except FileNotFoundError as exc:
        return fail(command, 3, "dependency_missing", str(exc))
    except (OSError, ValueError, KeyError, configparser.Error, subprocess.TimeoutExpired) as exc:
        return fail(command, 5, "file_action_failed", str(exc))
