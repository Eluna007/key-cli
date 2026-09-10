from __future__ import annotations

import ctypes
import errno
import fcntl
import selectors
import struct
from dataclasses import dataclass
from pathlib import Path

from ..utils.output import DEPENDENCY_FAILURE, STATE_FAILURE, Result, error

EV_SYN, EV_KEY, EV_LED = 0, 1, 17
SYN_REPORT, SYN_DROPPED = 0, 3
LED_NUML, LED_CAPSL = 0, 1


@dataclass
class Device:
    source: object
    caps: bool = False
    num: bool = False
    dropped: bool = False

    def snapshot(self):
        leds = self.source.leds()
        self.caps, self.num = LED_CAPSL in leds, LED_NUML in leds
        self.dropped = False

    def consume(self, event):
        if event.type == EV_SYN and event.code == SYN_DROPPED:
            self.dropped = True
        elif self.dropped:
            if event.type == EV_SYN and event.code == SYN_REPORT:
                self.snapshot()
                return True
        elif event.type == EV_LED:
            if event.code == LED_CAPSL:
                self.caps = bool(event.value)
            elif event.code == LED_NUML:
                self.num = bool(event.value)
        return False


def filter_keys(fd):
    # Linux EVIOCSMASK, struct input_mask (u32 type, u32 size, u64 pointer).
    # No python-evdev high-level mask API is required. Unsupported kernels still
    # work: Device.consume ignores ordinary input and nothing logs those events.
    mask = ctypes.create_string_buffer(96)
    for event_type in (EV_KEY, 4, 20):  # KEY, MSC scan codes, REP
        try:
            fcntl.ioctl(fd, 0x40104593, struct.pack("=IIQ", event_type, 96, ctypes.addressof(mask)))
        except OSError as exc:
            if exc.errno not in (errno.ENOTTY, errno.EINVAL):
                raise


class KeyboardMonitor:
    def __init__(self, context, device_factory, selector=None):
        self.context = context
        self.device_factory = device_factory
        self.selector = selector
        self.devices = {}
        self.errors = {}

    def close_device(self, path):
        device = self.devices.pop(path)
        if self.selector:
            self.selector.unregister(device.source.fd)
        device.source.close()

    def close(self):
        for path in list(self.devices):
            self.close_device(path)

    def rescan(self):
        paths = set()
        errors = {}
        for entry in self.context.list_devices(subsystem="input", ID_INPUT_KEYBOARD="1"):
            path = entry.device_node
            if not path or not entry.sys_name.startswith("event"):
                continue
            # Check capability before opening, including inaccessible keyboards.
            try:
                bits = int(
                    (Path(entry.sys_path) / "device/capabilities/led").read_text().split()[-1], 16
                )
                if not bits & 3:
                    continue
            except (OSError, ValueError, IndexError):
                pass  # evdev is authoritative if the sysfs hint is unavailable.
            paths.add(path)
            source = None
            try:
                if path in self.devices:
                    self.devices[path].snapshot()
                    continue
                source = self.device_factory(path)
                if not set(source.capabilities().get(EV_LED, ())) & {LED_NUML, LED_CAPSL}:
                    source.close()
                    continue
                filter_keys(source.fd)
                device = Device(source)
                device.snapshot()
                if self.selector:
                    self.selector.register(source.fd, selectors.EVENT_READ, path)
                self.devices[path] = device
            except OSError as exc:
                if source is not None:
                    source.close()
                if path in self.devices:
                    self.close_device(path)
                errors[path] = str(exc)
        for path in set(self.devices) - paths:
            self.close_device(path)
        self.errors = errors

    def read_device(self, path):
        device = self.devices.get(path)
        if device is None:
            return False
        resynced = False
        try:
            for event in device.source.read():
                resynced |= device.consume(event)
        except BlockingIOError:
            pass
        except OSError as exc:
            self.close_device(path)
            self.errors[path] = str(exc)
            resynced = True
        return resynced

    def result(self, command, event="snapshot"):
        available = bool(self.devices) and not self.errors
        diagnostic = None
        if self.errors:
            diagnostic = error(
                "keyboard_device_unavailable",
                "Cannot read all keyboard LED devices",
                devices=dict(self.errors),
            )
        elif not self.devices:
            diagnostic = error("keyboard_device_unavailable", "No readable keyboard LED devices")
        return Result(
            0 if available else STATE_FAILURE,
            command,
            {
                "event": event,
                "available": available,
                "capsLock": any(d.caps for d in self.devices.values()) if available else None,
                "numLock": any(d.num for d in self.devices.values()) if available else None,
                "error": diagnostic,
            },
            "Keyboard LEDs available" if available else diagnostic["message"],
            not available,
        )


def responses(watch=False):
    command = "keyboard.watch" if watch else "keyboard.status"
    try:
        from evdev import InputDevice
        import pyudev
    except ImportError:
        yield Result(
            DEPENDENCY_FAILURE,
            command,
            {
                "event": "snapshot",
                "available": False,
                "capsLock": None,
                "numLock": None,
                "error": error(
                    "keyboard_dependency_unavailable", "Install python-evdev and python-pyudev"
                ),
            },
            "Install python-evdev and python-pyudev",
            True,
        )
        return
    backend = None
    try:
        with selectors.DefaultSelector() as selector:
            context = pyudev.Context()
            if watch:
                monitor = pyudev.Monitor.from_netlink(context)
                monitor.filter_by(subsystem="input")
                monitor.start()  # Subscribe before enumerating to avoid a hotplug gap.
                selector.register(monitor.fileno(), selectors.EVENT_READ, None)
            backend = KeyboardMonitor(context, InputDevice, selector if watch else None)
            try:
                backend.rescan()
                previous = backend.result(command).json()
                yield backend.result(command)
                if not watch:
                    return
                while True:
                    for key, _ in selector.select():  # No timeout, polling, or heartbeat.
                        snapshot = key.data is None
                        if snapshot:
                            while monitor.poll(timeout=0) is not None:
                                pass
                            backend.rescan()
                        else:
                            snapshot = backend.read_device(key.data)
                        result = backend.result(command)
                        value = result.json()
                        if snapshot or value != previous:
                            result.payload["event"] = "snapshot" if snapshot else "changed"
                            yield result
                        previous = value
            finally:
                backend.close()
    except OSError as exc:
        yield Result(
            STATE_FAILURE,
            command,
            {
                "event": "snapshot",
                "available": False,
                "capsLock": None,
                "numLock": None,
                "error": error("keyboard_monitor_failed", str(exc)),
            },
            str(exc),
            True,
        )
