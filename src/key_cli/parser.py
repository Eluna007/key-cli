from __future__ import annotations

import argparse

from .commands.audio import run as audio
from .commands.file import run as file_action
from .commands.clipboard import run as clipboard
from .commands.doctor import run as doctor
from .commands.keyboard import run as keyboard
from .commands.ipc import run as ipc
from .commands.record import run as record
from .commands.shell import run as shell
from .commands.version import run as version
from .commands.tool import run as tool


def _json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="write one stable JSON response")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="key", description="Apollo shell lifecycle and discrete task CLI"
    )
    parser.add_argument(
        "-v",
        "--version",
        dest="version_flag",
        action="store_true",
        help="print the key-cli version",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    tool_parser = commands.add_parser(
        "tool", help="evaluate Spotlight calculator, currency and time tools"
    )
    tool_parser.set_defaults(handler=tool)
    tool_commands = tool_parser.add_subparsers(dest="action", required=True)
    tool_status = tool_commands.add_parser(
        "status", help="inspect tool capabilities without starting calculations"
    )
    tool_status.add_argument("--format", choices=["json"], default="json")
    tool_catalog = tool_commands.add_parser(
        "catalog", help="read local completion names without evaluating"
    )
    tool_catalog.add_argument("tool", choices=["calculator", "currency", "time"])
    tool_catalog.add_argument("--format", choices=["json"], default="json")
    for name in ("calculator", "currency", "time"):
        evaluate = tool_commands.add_parser(name, help=f"evaluate the {name} expression")
        evaluate.add_argument(
            "--expression",
            required=True,
            help="expression; use --expression=VALUE for a leading minus",
        )
        evaluate.add_argument("--format", choices=["json"], default="json")
        if name == "time":
            evaluate.add_argument(
                "--fold", type=int, choices=[0, 1], help="confirm a repeated local time candidate"
            )

    shell_parser = commands.add_parser(
        "shell", help="start, stop, or inspect the Apollo Quickshell"
    )
    shell_parser.set_defaults(handler=shell)
    shell_parser.add_argument("--daemon", "-d", action="store_true", help="pass -d to qs")
    shell_parser.add_argument(
        "--kill", "-k", action="store_true", help="stop the apollo qs configuration"
    )
    shell_parser.add_argument("--log", "-l", action="store_true", help="print the apollo qs log")
    shell_parser.add_argument(
        "--show", "-s", action="store_true", help="show the apollo IPC methods"
    )
    shell_parser.add_argument("--log-rules", metavar="RULES")
    shell_parser.add_argument("--foreground", action="store_true", help=argparse.SUPPRESS)
    shell_parser.add_argument("--no-duplicate", action="store_true", help=argparse.SUPPRESS)

    ipc_parser = commands.add_parser("ipc", help="route IPC through the Apollo qs configuration")
    ipc_parser.set_defaults(handler=ipc)
    ipc_parser.add_argument("action", nargs="?", choices=["show", "list", "call"], default="show")
    ipc_parser.add_argument("target", nargs="?")
    ipc_parser.add_argument("method", nargs="?")
    ipc_parser.add_argument("arguments", nargs=argparse.REMAINDER)

    file_parser = commands.add_parser("file", help="search, open or reveal local files")
    file_commands = file_parser.add_subparsers(dest="action", required=True)
    for action in ("open", "reveal"):
        sub = file_commands.add_parser(action, help=f"{action} a local file")
        sub.add_argument("path", help="absolute local file path")
        sub.add_argument("--format", choices=["json"], default="json")
    status = file_commands.add_parser("status", help="inspect file search and action capabilities")
    status.add_argument("--format", choices=["json"], default="json")
    search = file_commands.add_parser("search", help="literal case-insensitive filename search")
    search.add_argument("--format", choices=["json"], default="json")
    search.add_argument("--limit", default="50", help="maximum results (1–50)")
    search.add_argument("--root", action="append", help="search root; repeatable, defaults to HOME")
    search.add_argument("query")
    file_parser.set_defaults(handler=file_action)

    record_parser = commands.add_parser("record", help="record the screen with gpu-screen-recorder")
    record_commands = record_parser.add_subparsers(dest="action", required=True)
    start = record_commands.add_parser("start", help="start one screen recording")
    start.add_argument("--type", choices=["video", "gif"], default="video")
    start.add_argument("--target", choices=["region", "screen"], default="region")
    start.add_argument("--geometry", help="compositor-logical WIDTHxHEIGHT+X+Y")
    start.add_argument("--audio", choices=["none", "system"], default="none")
    start.add_argument("--fps", type=int, default=60)
    start.add_argument("--output", help="output directory")
    start.add_argument("--clipboard", action="store_true", help="copy the completed file URI")
    _json(start)
    for action in ("status", "stop", "pause", "resume"):
        sub = record_commands.add_parser(action, help=f"{action} the saved screen recording")
        if action == "stop":
            sub.add_argument("--clipboard", action="store_true", help="copy the completed file URI")
        _json(sub)
    watch = record_commands.add_parser("watch", help="subscribe to recording state changes")
    watch.add_argument("--format", choices=["jsonl"], default="jsonl")
    record_parser.set_defaults(handler=record)

    audio_parser = commands.add_parser("audio", help="record a microphone or system audio file")
    audio_commands = audio_parser.add_subparsers(dest="action", required=True)
    start = audio_commands.add_parser("start", help="start an audio recording")
    start.add_argument("--source", choices=["mic", "system"], required=True)
    start.add_argument("--output", help="output directory")
    _json(start)
    for action in ("status", "stop"):
        sub = audio_commands.add_parser(action, help=f"{action} the audio recording")
        _json(sub)
    watch = audio_commands.add_parser("watch", help="subscribe to recording state changes")
    watch.add_argument("--format", choices=["jsonl"], default="jsonl")
    audio_parser.set_defaults(handler=audio)

    clipboard_parser = commands.add_parser(
        "clipboard", help="operate on the cliphist clipboard backend"
    )
    clipboard_commands = clipboard_parser.add_subparsers(dest="action", required=True)
    list_parser = clipboard_commands.add_parser("list", help="list clipboard entries")
    list_parser.add_argument(
        "--limit", type=int, default=100, help="maximum entries to return (1–750)"
    )
    list_parser.add_argument("--format", choices=["json"], default=None)
    list_parser.add_argument("--json", action="store_true")
    config_parser = clipboard_commands.add_parser(
        "config", help="read or set the saved history limit"
    )
    config_parser.add_argument(
        "--max-items", help="history limit: 50–750 in steps of 50 (default 500)"
    )
    config_parser.add_argument("--format", choices=["json"], default=None)
    config_parser.add_argument("--json", action="store_true")
    for action in ("inspect", "restore", "delete"):
        sub = clipboard_commands.add_parser(action, help=f"{action} one clipboard entry")
        sub.add_argument("id")
        sub.add_argument("--format", choices=["json"], default=None)
        sub.add_argument("--json", action="store_true")
    for action in ("clear", "status", "watch", "store"):
        help_text = (
            f"internal clipboard {action}"
            if action in {"watch", "store"}
            else f"clipboard {action}"
        )
        sub = clipboard_commands.add_parser(action, help=help_text)
        if action == "store":
            sub.add_argument("--stdin", action="store_true", help=argparse.SUPPRESS)
        sub.add_argument("--format", choices=["json"], default=None)
        sub.add_argument("--json", action="store_true")
    clipboard_parser.set_defaults(handler=clipboard)

    keyboard_parser = commands.add_parser("keyboard", help="monitor keyboard lock LEDs")
    keyboard_parser.set_defaults(handler=keyboard)
    keyboard_commands = keyboard_parser.add_subparsers(dest="action", required=True)
    status = keyboard_commands.add_parser("status", help="read current LED state")
    status.add_argument("--format", choices=["json"], default=None)
    status.add_argument("--json", action="store_true")
    watch = keyboard_commands.add_parser("watch", help="stream LED state changes without polling")
    watch.add_argument("--format", choices=["jsonl"], default="jsonl")

    doctor_parser = commands.add_parser("doctor", help="check key runtime dependencies")
    doctor_parser.set_defaults(handler=doctor)
    _json(doctor_parser)

    version_parser = commands.add_parser("version", help="print key-cli version metadata")
    version_parser.set_defaults(handler=version)
    _json(version_parser)
    return parser
