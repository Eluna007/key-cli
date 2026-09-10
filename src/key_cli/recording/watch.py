"""Linux subscriptions to atomic recording state replacement and process exit."""

from __future__ import annotations

import ctypes
import json
import os
import selectors
import struct
from contextlib import contextmanager

from .common import process_fields, response
from .state import base_state, load, locked, runtime_dir, save
from ..utils.output import error, fail
from ..utils.process import matches

ACTIVE = {"starting", "recording", "paused", "stopping", "finalizing"}


@contextmanager
def state_events():
    # Watch the directory: save replaces the file inode. Each reader gets events
    # independently, without socket ownership or best-effort writer notifications.
    libc = ctypes.CDLL(None, use_errno=True)
    libc.inotify_init1.argtypes = [ctypes.c_int]
    libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    fd = libc.inotify_init1(os.O_CLOEXEC | os.O_NONBLOCK)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "inotify_init1 failed")
    try:
        if libc.inotify_add_watch(fd, os.fsencode(runtime_dir()), 0x80 | 0x400 | 0x800) < 0:
            raise OSError(ctypes.get_errno(), "inotify_add_watch failed")
        yield fd
    finally:
        os.close(fd)


def relevant_event(fd, kind):
    relevant = False
    data = os.read(fd, 65536)
    offset = 0
    while offset < len(data):
        _, mask, _, length = struct.unpack_from("iIII", data, offset)
        name = data[offset + 16 : offset + 16 + length].rstrip(b"\0")
        offset += 16 + length
        if mask & (0x400 | 0x800 | 0x8000):
            raise RuntimeError("recording runtime directory watch was removed")
        relevant |= bool(mask & 0x4000) or name == os.fsencode(f"{kind}.json")
    return relevant


def reconcile_exit(kind, observed, executable):
    # Stop owns this lock across termination and finalization. Wait for its result.
    with locked(kind, blocking=True):
        current = load(kind)
        if (
            current.get("sessionId") == observed.get("sessionId")
            and process_fields(current) == process_fields(observed)
            and current.get("state") in ACTIVE
            and not matches(process_fields(current), executable, current.get("temporaryPath", ""))
        ):
            current.update(
                state="error",
                pid=0,
                processStartTicks=None,
                error=error("recorder_exited", f"{executable} is no longer running"),
            )
            save(kind, current)
        return current


def events(kind):
    executable = "ffmpeg" if kind == "audio" else "gpu-screen-recorder"
    pidfd = None
    with state_events() as changes, selectors.DefaultSelector() as selector:
        selector.register(changes, selectors.EVENT_READ, "state")
        try:
            # Subscribe before reading to close the initial replacement race.
            with locked(kind, blocking=True):
                current = load(kind)
            previous = None
            while True:
                if pidfd is not None:
                    selector.unregister(pidfd)
                    os.close(pidfd)
                    pidfd = None
                if current.get("state") in ACTIVE:
                    identity = process_fields(current)
                    if matches(identity, executable, current.get("temporaryPath", "")):
                        try:
                            pidfd = os.pidfd_open(identity.pid)
                        except ProcessLookupError:
                            pass
                        # Recheck identity after opening to exclude PID reuse.
                        if pidfd is not None and matches(
                            identity, executable, current.get("temporaryPath", "")
                        ):
                            selector.register(pidfd, selectors.EVENT_READ, "pid")
                        else:
                            if pidfd is not None:
                                os.close(pidfd)
                                pidfd = None
                            current = reconcile_exit(kind, current, executable)
                    else:
                        current = reconcile_exit(kind, current, executable)
                if current != previous:
                    payload = base_state() | current
                    yield response(
                        payload,
                        f"{kind}.watch",
                        ok_value=not payload.get("error"),
                        error_value=payload.get("error"),
                        event="snapshot" if previous is None else "changed",
                    ).payload
                    previous = dict(current)
                if current.get("state") not in ACTIVE:
                    return
                ready = selector.select()  # Deliberately no timeout or heartbeat.
                if any(key.data == "pid" for key, _ in ready):
                    current = reconcile_exit(kind, current, executable)
                if any(key.data == "state" for key, _ in ready) and relevant_event(changes, kind):
                    current = load(kind)
        finally:
            if pidfd is not None:
                os.close(pidfd)


def run(kind):
    try:
        for payload in events(kind):
            print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 0
    except (OSError, RuntimeError, AttributeError) as exc:
        result = fail(f"{kind}.watch", 5, "recording_watch_unavailable", str(exc))
        print(json.dumps(result.payload), flush=True)
        return result.exit_code
