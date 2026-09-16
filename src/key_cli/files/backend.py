from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time

from ..utils.output import fail, ok
from ..utils.file_types import file_mime, theme_icon

MAX_RESULTS = 50
MAX_CANDIDATES = 400
SEARCH_SECONDS = 3.0
ACTION_SECONDS = 5.0
FILE_MANAGER = "org.freedesktop.FileManager1"


def fd_program():
    return shutil.which("fd") or shutil.which("fdfind")


def manager_available():
    if not shutil.which("busctl"):
        return False
    try:
        for method in ("ListNames", "ListActivatableNames"):
            response = subprocess.run(
                [
                    "busctl",
                    "--user",
                    "--timeout=1",
                    "--json=short",
                    "call",
                    "org.freedesktop.DBus",
                    "/org/freedesktop/DBus",
                    "org.freedesktop.DBus",
                    method,
                ],
                capture_output=True,
                timeout=2,
                check=False,
            )
            if response.returncode == 0 and FILE_MANAGER in json.loads(response.stdout)["data"][0]:
                return True
    except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired):
        pass
    return False


def status():
    fd = bool(fd_program())
    opener = bool(shutil.which("gio"))
    manager = manager_available()
    return ok(
        "file.status",
        capabilities={"search": True, "open": True, "reveal": True},
        available=fd,
        canSearch=fd,
        canOpen=opener,
        canReveal=manager or opener,
        dependencies={
            "fd": fd,
            "xdgOpen": bool(shutil.which("xdg-open")),
            "gio": opener,
            "xdgTerminalExec": bool(shutil.which("xdg-terminal-exec")),
            "fileManager1": manager,
        },
        reasons={
            "search": None if fd else "fd_unavailable",
            "open": None if opener else "dependency_missing",
            "reveal": None if manager or opener else "dependency_missing",
        },
    )


def safe_path(value):
    value.encode("utf-8", errors="strict")
    if not os.path.isabs(value) or "\0" in value:
        raise ValueError("An absolute UTF-8 local path is required")
    # Do not resolve symlinks (including symlink/.. traversal semantics).
    return Path(value)


def metadata(value):
    try:
        path = safe_path(value)
        info = path.lstat()
    except (FileNotFoundError, NotADirectoryError, UnicodeError, ValueError):
        return None
    except OSError:
        return None
    link = stat.S_ISLNK(info.st_mode)
    if not (link or stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        return None
    target = info
    if link:
        try:
            target = path.stat()
        except OSError:
            target = None
    directory = target is not None and stat.S_ISDIR(target.st_mode)
    regular = target is not None and stat.S_ISREG(target.st_mode)
    mime = file_mime(path.name, directory) or "application/octet-stream"
    executable = regular and os.access(path, os.X_OK)
    return dict(
        name=path.name or str(path),
        path=str(path),
        parentPath=str(path.parent),
        parentName=path.parent.name or str(path.parent),
        kind="symlink" if link else "directory" if directory else "file",
        mimeType=mime,
        extension=path.suffix[1:].lower() if not directory else "",
        size=target.st_size if regular else None,
        modifiedTime=info.st_mtime,
        isDirectory=directory,
        isSymlink=link,
        isExecutable=executable,
        icon=theme_icon(mime, directory),
        targetAvailable=target is not None,
    )


def search(args):
    command = "file.search"
    try:
        limit = int(args.limit)
        if not 1 <= limit <= MAX_RESULTS:
            raise ValueError("Limit must be from 1 to 50")
        roots = [str(safe_path(value)) for value in (args.root or [str(Path.home())])]
        if not all(Path(value).is_dir() for value in roots):
            raise ValueError("Search roots must be existing directories")
        query = args.query
        query.encode("utf-8", errors="strict")
        if "\0" in query:
            raise ValueError("Query contains NUL")
    except (ValueError, UnicodeError, OSError) as exc:
        return fail(command, 2, "invalid_search", str(exc))
    payload = dict(
        query=query,
        roots=roots,
        entries=[],
        complete=True,
        limited=False,
        limitReasons=[],
        skippedNonUtf8=0,
    )
    if not query.strip():
        return ok(command, **payload)
    program = fd_program()
    if not program:
        return fail(command, 3, "fd_unavailable", "fd or fdfind is not installed")
    argv = [
        program,
        "--fixed-strings",
        "--ignore-case",
        "--absolute-path",
        "--print0",
        "--color",
        "never",
        "--type",
        "f",
        "--type",
        "d",
        "--type",
        "l",
    ]
    if "/" in query:
        argv.append("--full-path")
    argv += ["--", query, *roots]
    candidates = set()
    reasons = []
    cancelled = False

    def cancel(_signum, _frame):
        nonlocal cancelled
        cancelled = True

    handlers = {sig: signal.signal(sig, cancel) for sig in (signal.SIGTERM, signal.SIGINT)}
    child = None
    try:
        child = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
        )
        pending = b""
        diagnostic = b""
        deadline = time.monotonic() + SEARCH_SECONDS
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ, "paths")
            selector.register(child.stderr, selectors.EVENT_READ, "error")
            while selector.get_map() and not reasons and not cancelled:
                if time.monotonic() >= deadline:
                    reasons.append("time")
                    break
                for key, _ in selector.select(min(0.05, max(0, deadline - time.monotonic()))):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.data == "error":
                        diagnostic = (diagnostic + chunk)[:4096]
                        continue
                    pending += chunk
                    while b"\0" in pending:
                        raw, pending = pending.split(b"\0", 1)
                        try:
                            value = raw.decode("utf-8", errors="strict")
                        except UnicodeError:
                            payload["skippedNonUtf8"] += 1
                            continue
                        if value:
                            candidates.add(value)
                        if len(candidates) >= MAX_CANDIDATES:
                            reasons.append("candidates")
                            break
                    if len(pending) > 65536:
                        raise ValueError("fd returned an oversized path")
            if not reasons and not cancelled:
                child.wait(timeout=max(0.01, deadline - time.monotonic()))
                if child.returncode or pending:
                    return fail(
                        command, 5, "file_search_failed", "fd failed or returned invalid paths"
                    )
    except subprocess.TimeoutExpired:
        reasons.append("time")
    except (OSError, ValueError) as exc:
        return fail(command, 5, "file_search_failed", str(exc))
    finally:
        # Owned child only; terminate and reap before Python exits, including SIGTERM
        # from Quickshell. Open/reveal deliberately never use this search lifetime.
        if child is not None:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            child.stdout.close()
            child.stderr.close()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    if cancelled:
        return fail(command, 5, "file_search_cancelled", "Search cancelled")
    needle = query.casefold()

    def rank(value):
        name = Path(value).name.casefold()
        tier = 0 if name == needle else 1 if name.startswith(needle) else 2 if needle in name else 3
        return tier, name, value.casefold(), value

    entries = []
    for value in sorted(candidates, key=rank):
        item = metadata(value)
        if item is not None:
            entries.append(item)
        if len(entries) > limit:
            reasons.append("results")
            break
    payload.update(
        entries=entries[:limit], complete=not reasons, limited=bool(reasons), limitReasons=reasons
    )
    return ok(command, **payload)


def open_request(path):
    if not shutil.which("gio"):
        raise FileNotFoundError("gio is not installed")
    # An isolated helper selects by content type and uses GAppInfo.launch.
    # gio open prefers x-scheme-handler/file, which may send every file to a
    # file manager. The helper still delegates Terminal=true and Exec to GIO.
    child = subprocess.Popen(
        [sys.executable, "-m", "key_cli.files.desktop_open", str(path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    code = child.wait(timeout=ACTION_SECONDS)
    if code == 3:
        raise FileNotFoundError("GIO runtime is unavailable")
    if code != 0:
        raise OSError("The default application rejected the open request")


def action(args):
    command = "file." + args.action
    try:
        path = safe_path(args.path)
    except (ValueError, UnicodeError):
        return fail(command, 2, "invalid_path", "An absolute UTF-8 local path is required")
    try:
        exists = path.exists()
        mode = "open"
        if args.action == "open":
            item = metadata(str(path))
            if not exists:
                return fail(
                    command,
                    5,
                    "file_missing",
                    "The file or symlink target no longer exists",
                    path=str(path),
                )
            if item is None:
                return fail(
                    command, 5, "file_unsupported", "This filesystem entry cannot be opened"
                )
            # Never turn Files into a launcher, including non-x desktop entries.
            target_suffix = path.resolve().suffix.lower()
            if not item["isDirectory"] and (
                item["isExecutable"]
                or target_suffix in {".desktop", ".appimage", ".exe", ".com", ".bat", ".cmd"}
            ):
                return fail(
                    command,
                    5,
                    "file_execution_blocked",
                    "Use Apps to launch applications; this item can be revealed",
                )
            open_request(path)
        else:
            if not path.parent.is_dir():
                return fail(
                    command, 5, "directory_missing", "The containing directory no longer exists"
                )
            mode = "directory"
            if path.is_symlink() or exists:
                try:
                    response = subprocess.run(
                        [
                            "busctl",
                            "--user",
                            "--timeout=3",
                            "call",
                            FILE_MANAGER,
                            "/org/freedesktop/FileManager1",
                            FILE_MANAGER,
                            "ShowItems",
                            "ass",
                            "1",
                            path.as_uri(),
                            "",
                        ],
                        capture_output=True,
                        timeout=4,
                        check=False,
                    )
                    if response.returncode == 0:
                        mode = "reveal"
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if mode == "directory":
                open_request(path.parent)
        return ok(command, path=str(path), mode=mode, fileExists=exists)
    except FileNotFoundError as exc:
        return fail(command, 3, "dependency_missing", str(exc))
    except subprocess.TimeoutExpired:
        return fail(
            command, 5, "file_action_timeout", "The system did not confirm the request in time"
        )
    except OSError as exc:
        return fail(command, 5, "file_action_failed", str(exc))
