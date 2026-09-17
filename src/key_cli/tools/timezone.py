from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from ..utils.output import fail, ok

ALIASES = {
    "tokyo": "Asia/Tokyo",
    "shanghai": "Asia/Shanghai",
    "london": "Europe/London",
    "paris": "Europe/Paris",
    "new-york": "America/New_York",
    "los-angeles": "America/Los_Angeles",
    "sydney": "Australia/Sydney",
    "utc": "UTC",
}
AMBIGUOUS = {"CST", "IST", "BST", "EST", "MST", "PST", "AST", "CDT", "EDT", "MDT", "PDT"}
GRAMMAR = re.compile(
    r"^(now|(?:(\d{4}-\d{2}-\d{2})\s+)?(\d{2}:\d{2}(?::\d{2})?))"
    r"(?:\s+(\S+))?\s+to\s+(\S+)$",
    re.IGNORECASE,
)


def resolve_zone(name: str) -> ZoneInfo:
    if name.upper() in AMBIGUOUS:
        raise ValueError("Choose an IANA time zone instead of an ambiguous abbreviation")
    return ZoneInfo(ALIASES.get(name.lower(), name))


def system_zone() -> ZoneInfo:
    # Preserve the actual transition table, including when /etc/localtime is a
    # copied tzfile rather than a symlink. astimezone().tzinfo is a fixed offset.
    configured = os.environ.get("TZ", "").removeprefix(":")
    if configured:
        if configured.startswith("/"):
            with open(configured, "rb") as stream:
                return ZoneInfo.from_file(stream, key="system")
        return resolve_zone(configured)
    localtime = Path("/etc/localtime")
    resolved = str(localtime.resolve())
    if "/zoneinfo/" in resolved:
        return ZoneInfo(resolved.split("/zoneinfo/", 1)[1])
    with localtime.open("rb") as stream:
        return ZoneInfo.from_file(stream, key="system")


def catalog():
    return sorted(available_timezones())


def describe(value: datetime) -> dict:
    seconds = int(value.utcoffset().total_seconds())
    sign = "+" if seconds >= 0 else "-"
    minutes = abs(seconds) // 60
    return {
        "datetime": value.isoformat(),
        "date": value.date().isoformat(),
        "zone": value.tzinfo.key,
        "offset": f"{sign}{minutes // 60:02d}:{minutes % 60:02d}",
        "fold": value.fold,
    }


def evaluate(expression: str, fold: int | None = None, *, now=None, local_zone=None):
    command = "tool.time"
    if not expression.strip():
        return ok(command, state="empty")
    if len(expression) > 512:
        return fail(command, 2, "invalid_expression", "Time expression is too long", state="error")
    match = GRAMMAR.fullmatch(expression.strip())
    if not match:
        return ok(command, state="incomplete", hint="now to Asia/Tokyo")
    try:
        source_zone = resolve_zone(match[4]) if match[4] else (local_zone or system_zone())
        target_zone = resolve_zone(match[5])
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None:
            raise ValueError("The reference clock must include a time zone")
        if match[1].lower() == "now":
            source = instant.astimezone(source_zone)
        else:
            date = match[2] or instant.astimezone(source_zone).date().isoformat()
            naive = datetime.fromisoformat(date + "T" + match[3])
            candidates = []
            for choice in (0, 1):
                candidate = naive.replace(tzinfo=source_zone, fold=choice)
                roundtrip = candidate.astimezone(timezone.utc).astimezone(source_zone)
                if roundtrip.replace(tzinfo=None) == naive and not any(
                    item.utcoffset() == candidate.utcoffset() for item in candidates
                ):
                    candidates.append(candidate)
            if not candidates:
                return fail(
                    command, 2, "nonexistent_time", "This local time does not exist", state="error"
                )
            if len(candidates) > 1 and fold is None:
                return ok(
                    command, state="ambiguous", candidates=[describe(item) for item in candidates]
                )
            source = next((item for item in candidates if item.fold == fold), candidates[0])
        target = source.astimezone(target_zone)
        answer = f"{target.strftime('%Y-%m-%d %H:%M:%S')} {target_zone.key} (UTC{describe(target)['offset']})"
        return ok(
            command,
            text=answer,
            state="valid",
            answer=answer,
            source=describe(source),
            target=describe(target),
            dayDelta=(target.date() - source.date()).days,
            evaluatedAt=instant.isoformat(),
        )
    except (ZoneInfoNotFoundError, OSError):
        return fail(
            command,
            3,
            "timezone_unavailable",
            "Time zone data is unavailable for this zone",
            state="unavailable",
        )
    except ValueError as error:
        return fail(command, 2, "invalid_time", str(error), state="error")
