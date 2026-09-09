"""The single persistent clipboard history limit, independent of the shell."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from ..utils.output import GENERAL_FAILURE, USAGE_ERROR, Result, fail, ok


def config_path() -> Path:
    home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(home) / "key" / "clipboard.json"


def valid_limit(value: object) -> bool:
    return type(value) is int and 50 <= value <= 750 and value % 50 == 0


def load() -> dict:
    path = config_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if path.is_symlink():
            raise ValueError("clipboard configuration is a broken symbolic link") from None
        return {"maxItems": 500}
    if not isinstance(value, dict) or not valid_limit(value.get("maxItems")):
        raise ValueError("maxItems must be an integer from 50 to 750 in steps of 50")
    return value


def save(value: dict) -> None:
    path = config_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".clipboard.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def run(raw_limit: str | None) -> Result:
    command = "clipboard.config"
    if raw_limit is not None:
        try:
            limit = int(raw_limit) if re.fullmatch(r"[0-9]+", raw_limit) else None
        except ValueError:
            limit = None
        if not valid_limit(limit):
            return fail(
                command,
                USAGE_ERROR,
                "invalid_clipboard_limit",
                "max-items must be an integer from 50 to 750 in steps of 50",
            )
    try:
        value = load()
    except (OSError, ValueError) as exc:
        return fail(command, GENERAL_FAILURE, "clipboard_config_read_failed", str(exc))
    if raw_limit is not None:
        value["maxItems"] = limit
        try:
            save(value)
        except OSError as exc:
            return fail(command, GENERAL_FAILURE, "clipboard_config_write_failed", str(exc))
    return ok(command, str(value["maxItems"]), maxItems=value["maxItems"])
