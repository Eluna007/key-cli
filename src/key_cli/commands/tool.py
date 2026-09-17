"""Public, independently versioned CLI boundary for Spotlight tools."""

import shutil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..tools import calculator, currency, timezone
from ..utils.output import fail, ok


def run(args):
    if args.action == "status":
        try:
            ZoneInfo("UTC")
            tzdata = True
        except ZoneInfoNotFoundError:
            tzdata = False
        return ok(
            "tool.status",
            capabilities={
                "calculator": bool(shutil.which("qalc")),
                "currency": True,
                "time": tzdata,
            },
            source=currency.SOURCE,
        )
    if args.action == "catalog":
        if args.tool == "calculator":
            values = [
                {"text": value, "name": value}
                for value in dict.fromkeys(
                    calculator.FUNCTIONS + calculator.CONSTANTS + calculator.UNITS
                )
            ]
        elif args.tool == "currency":
            values = [{"text": code, "name": name} for code, name in currency.CURRENCIES.items()]
        else:
            values = [{"text": value, "name": value} for value in timezone.catalog()]
            values.extend({"text": value, "name": key} for key, value in timezone.ALIASES.items())
        return ok("tool.catalog", tool=args.tool, candidates=values)
    if args.action == "calculator":
        return calculator.evaluate(args.expression)
    if args.action == "currency":
        return currency.evaluate(args.expression)
    if args.action == "time":
        return timezone.evaluate(args.expression, args.fold)
    return fail("tool.unknown", 2, "invalid_arguments", "Unknown tool command")
