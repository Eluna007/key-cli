import errno
import json
import os
import sys
from types import SimpleNamespace

import pytest

from key_cli import main
from key_cli.keyboard import backend


class Input:
    def __init__(self, leds=()):
        self.fd, self.writer = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.current = list(leds)
        self.events = []
        self.closed = False

    def capabilities(self):
        return {17: [0, 1]}

    def leds(self):
        return self.current

    def send(self, *events):
        self.events.extend(SimpleNamespace(type=t, code=c, value=v) for t, c, v in events)
        os.write(self.writer, b"x")

    def read(self):
        os.read(self.fd, 100)
        events, self.events = self.events, []
        return iter(events)

    def close(self):
        if not self.closed:
            os.close(self.fd)
            os.close(self.writer)
            self.closed = True


@pytest.fixture
def devices(tmp_path, monkeypatch):
    sources = {"/fake/one": Input([1]), "/fake/two": Input([0])}
    entries = [
        SimpleNamespace(device_node=p, sys_name="event" + str(i), sys_path=str(tmp_path / str(i)))
        for i, p in enumerate(sources)
    ]
    context = SimpleNamespace(list_devices=lambda **_: entries)
    monkeypatch.setattr(backend, "filter_keys", lambda _: None)
    yield context, sources, entries
    for source in sources.values():
        source.close()


def test_snapshot_or_events_and_removal(devices):
    context, sources, entries = devices
    monitor = backend.KeyboardMonitor(context, sources.__getitem__)
    monitor.rescan()
    value = monitor.result("keyboard.status").json()
    assert value == {
        "schemaVersion": 1,
        "command": "keyboard.status",
        "ok": True,
        "event": "snapshot",
        "available": True,
        "capsLock": True,
        "numLock": True,
        "error": None,
    }
    sources["/fake/one"].send((1, 58, 1), (1, 30, 1))
    monitor.read_device("/fake/one")
    assert monitor.result("keyboard.status").json() == value
    sources["/fake/one"].send((17, 1, 0))
    monitor.read_device("/fake/one")
    assert monitor.result("keyboard.status").json()["capsLock"] is False
    entries.pop()
    monitor.rescan()
    assert sources["/fake/two"].closed
    assert monitor.result("keyboard.status").json()["numLock"] is False
    monitor.close()


def test_permissions_are_unknown_not_off_and_recover(devices):
    context, sources, _ = devices

    def denied(path):
        if path.endswith("two"):
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return sources[path]

    monitor = backend.KeyboardMonitor(context, denied)
    monitor.rescan()
    value = monitor.result("keyboard.status")
    assert value.exit_code == 5
    assert value.json()["capsLock"] is None
    assert value.json()["available"] is False
    monitor.device_factory = sources.__getitem__
    monitor.rescan()
    assert monitor.result("keyboard.status").json()["available"] is True
    monitor.close()


def test_dropped_frame_waits_for_report_and_reads_authoritative_state():
    source = Input([0])
    try:
        device = backend.Device(source, caps=True)
        for event in [(0, 3, 0), (17, 1, 0)]:
            assert not device.consume(SimpleNamespace(type=event[0], code=event[1], value=event[2]))
        assert device.caps
        assert device.consume(SimpleNamespace(type=0, code=0, value=0))
        assert not device.caps and device.num
        assert not device.dropped
    finally:
        source.close()


def test_masks_use_kernel_abi_and_ignore_unsupported_ioctl(monkeypatch):
    import ctypes
    import struct

    masks = []

    def ioctl(fd, request, data):
        event, size, pointer = struct.unpack("=IIQ", data)
        masks.append((fd, request, event, ctypes.string_at(pointer, size)))

    monkeypatch.setattr(backend.fcntl, "ioctl", ioctl)
    backend.filter_keys(42)
    assert [m[2] for m in masks] == [1, 4, 20]
    assert all(m[0] == 42 and m[1] == 0x40104593 and m[3] == bytes(96) for m in masks)
    monkeypatch.setattr(
        backend.fcntl,
        "ioctl",
        lambda *args: (_ for _ in ()).throw(OSError(errno.ENOTTY, "unsupported")),
    )
    backend.filter_keys(42)


def test_status_and_watch_missing_dependencies(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "evdev", None)
    assert main(["keyboard", "status", "--format", "json"]) == 3
    value = json.loads(capsys.readouterr().out)
    assert value["command"] == "keyboard.status" and not value["ok"]
    assert value["error"]["code"] == "keyboard_dependency_unavailable"
    assert main(["keyboard", "watch", "--format", "jsonl"]) == 3
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["command"] == "keyboard.watch"


def test_watch_real_fd_notifications_and_cleanup(devices, monkeypatch):
    context, sources, entries = devices
    notification = Input()
    monitor = SimpleNamespace(
        filter_by=lambda **_: None,
        start=lambda: None,
        fileno=lambda: notification.fd,
        poll=lambda timeout: notification.read() if ready(notification.fd) else None,
    )
    monkeypatch.setitem(sys.modules, "evdev", SimpleNamespace(InputDevice=sources.__getitem__))
    monkeypatch.setitem(
        sys.modules,
        "pyudev",
        SimpleNamespace(
            Context=lambda: context, Monitor=SimpleNamespace(from_netlink=lambda _: monitor)
        ),
    )
    stream = backend.responses(watch=True)
    try:
        assert next(stream).json()["event"] == "snapshot"
        sources["/fake/one"].send((1, 30, 1), (17, 1, 0))
        value = next(stream).json()
        assert value["event"] == "changed" and value["capsLock"] is False
        sources["/fake/one"].current = [1]
        sources["/fake/one"].send((0, 3, 0), (17, 1, 0), (0, 0, 0))
        value = next(stream).json()
        assert value["event"] == "snapshot" and value["capsLock"] is True
        removed = list(entries)
        entries.clear()
        notification.send()
        value = next(stream).json()
        assert value["event"] == "snapshot" and not value["available"]
        assert all(s.closed for s in sources.values())
        for path in sources:
            sources[path] = Input([0])
        entries.extend(removed)
        notification.send()
        value = next(stream).json()
        assert value["event"] == "snapshot" and value["available"]
        assert value["numLock"] is True
    finally:
        stream.close()
        notification.close()


def ready(fd):
    import select

    return bool(select.select([fd], [], [], 0)[0])


def test_doctor_separates_dependencies_from_runtime(monkeypatch):
    from key_cli.commands import doctor
    from key_cli.utils.output import Result

    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/fake/" + name)
    monkeypatch.setattr(doctor, "safe_version", lambda _: "fixture")
    monkeypatch.setattr(doctor.platform, "platform", lambda: "fixture")
    monkeypatch.setattr(
        doctor,
        "responses",
        lambda: iter(
            [
                Result(
                    5,
                    "keyboard.status",
                    {
                        "available": False,
                        "capsLock": None,
                        "numLock": None,
                        "error": {
                            "code": "keyboard_device_unavailable",
                            "message": "permission denied",
                        },
                    },
                )
            ]
        ),
    )
    monkeypatch.setattr(doctor, "watcher_running", lambda: True)
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    result = doctor.run(SimpleNamespace())
    assert result.exit_code == 0  # Existing dependency exit code is preserved.
    value = result.json()
    assert value["features"]["clipboard-watch"] is True
    assert value["clipboard"]["watcherRunning"] is True
    assert value["features"]["keyboard"] is False
    assert value["runtimeReady"] is False
