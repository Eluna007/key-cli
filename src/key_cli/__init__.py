"""The stable, small command line boundary for Apollo."""

from __future__ import annotations

import sys
from typing import Sequence

from ._version import __version__

from .parser import build_parser
from .utils.output import emit_result, fail


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = list(argv) if argv is not None else sys.argv[1:]
    try:
        args = parser.parse_args(arguments)
    except SystemExit as exc:
        if exc.code == 2 and arguments[:1] == ["tool"]:
            action = (
                arguments[1]
                if len(arguments) > 1
                and arguments[1] in {"status", "catalog", "calculator", "currency", "time"}
                else "unknown"
            )
            return emit_result(
                fail("tool." + action, 2, "invalid_arguments", "Invalid tool command arguments"),
                True,
            )
        if exc.code == 2 and arguments[:1] == ["file"]:
            action = (
                arguments[1]
                if len(arguments) > 1 and arguments[1] in {"status", "search", "open", "reveal"}
                else "unknown"
            )
            return emit_result(
                fail("file." + action, 2, "invalid_arguments", "Invalid file command arguments"),
                True,
            )
        raise
    if getattr(args, "version_flag", False):
        args.command = "version"
        args.json = getattr(args, "json", False)
        from .commands.version import run

        return emit_result(run(args), args.json)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 0
    try:
        result = args.handler(args)
        if isinstance(result, int):
            return result
        json_requested = getattr(args, "json", False) or getattr(args, "format", None) == "json"
        return emit_result(result, json_requested)
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        print("key: interrupted", file=sys.stderr)
        return 130


__all__ = ["main", "__version__"]
