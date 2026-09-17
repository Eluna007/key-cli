from __future__ import annotations

import os
import re
import selectors
import shutil
import signal
import subprocess
import tempfile
import time

from ..utils.output import fail, ok

FUNCTIONS = (
    "abs",
    "sqrt",
    "cbrt",
    "sin",
    "cos",
    "tan",
    "asin",
    "acos",
    "atan",
    "ln",
    "log",
    "exp",
    "floor",
    "ceil",
    "round",
    "min",
    "max",
)
CONSTANTS = ("pi", "e")
UNITS = (
    "m",
    "km",
    "cm",
    "mm",
    "ft",
    "in",
    "mi",
    "yd",
    "s",
    "min",
    "h",
    "day",
    "kg",
    "g",
    "mg",
    "lb",
    "oz",
    "L",
    "mL",
    "K",
    "degC",
    "degF",
    "rad",
    "deg",
)
MAX_EXPRESSION = 1024
MAX_OUTPUT = 16384
TIMEOUT = 2.5
TOKEN = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|[A-Za-z]+|[+*/^%(),.<>!=\-]| +")


def validate(expression):
    if len(expression) > MAX_EXPRESSION or not expression.strip():
        raise ValueError("Expression is empty or too long")
    tokens = TOKEN.findall(expression)
    if "".join(tokens) != expression:
        raise ValueError("Unsupported expression characters")
    identifiers = [token for token in tokens if token.isalpha()]
    allowed = set(FUNCTIONS + CONSTANTS + UNITS + ("to",))
    if any(token not in allowed for token in identifiers):
        raise ValueError("Unsupported function, constant or unit")
    if identifiers.count("to") > 1 or expression.lstrip().startswith(("/", "to ")):
        raise ValueError("Enter a mathematical expression")
    # No assignment, chained commands, strings, datasets or arbitrary functions.
    if re.search(r"(?<![<>=!])=(?!=)", expression):
        raise ValueError("Assignments are not supported")
    for name in re.findall(r"([A-Za-z]+)\s*\(", expression):
        if name not in FUNCTIONS:
            raise ValueError("Unsupported function")
    parts = re.split(r"\s+to\s+", expression, maxsplit=1)
    if len(parts) == 2:
        if not re.fullmatch(r"[A-Za-z]+(?:\s*[/\*]\s*[A-Za-z]+)?", parts[1]):
            raise ValueError("Choose a supported conversion unit")
        if any(name not in UNITS for name in re.findall(r"[A-Za-z]+", parts[1])):
            raise ValueError("Choose a supported conversion unit")
    # The expression argv starts with '(' so negative numbers cannot become flags.
    return "(" + parts[0] + ")" + (" to " + parts[1] if len(parts) == 2 else "")


class CalculationCancelled(Exception):
    pass


def bounded_process(argv, env):
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    handlers = {}

    def terminate(signum, frame):
        raise CalculationCancelled("Calculation cancelled")

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            handlers[signum] = signal.signal(signum, terminate)
        output = {"stdout": bytearray(), "stderr": bytearray()}
        deadline = time.monotonic() + TIMEOUT
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Calculation timed out")
                for key, _ in selector.select(min(remaining, 0.1)):
                    data = os.read(key.fileobj.fileno(), 4096)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    output[key.data].extend(data)
                    if sum(map(len, output.values())) > MAX_OUTPUT:
                        raise ValueError("Calculation output is too large")
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        return process.returncode, *(
            bytes(output[key]).decode("utf-8", "replace").strip() for key in ("stdout", "stderr")
        )
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        process.stdout.close()
        process.stderr.close()
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def evaluate(expression):
    command = "tool.calculator"
    if not expression.strip():
        return ok(command, state="empty")
    try:
        safe_expression = validate(expression)
    except ValueError as error:
        return fail(command, 2, "invalid_expression", str(error), state="error")
    if expression.count("(") > expression.count(")") or re.search(r"[+*/^,<>-]\s*$", expression):
        return ok(command, state="incomplete")
    program = shutil.which("qalc")
    if not program:
        return fail(command, 3, "dependency_missing", "qalc is unavailable", state="unavailable")
    try:
        with tempfile.TemporaryDirectory(prefix="key-calculator-") as directory:
            env = dict(
                os.environ,
                HOME=directory,
                XDG_CONFIG_HOME=directory,
                XDG_DATA_HOME=directory,
                XDG_CACHE_HOME=directory,
                LC_ALL="C",
            )
            argv = [
                program,
                "--defaults",
                "--nocurrencies",
                "--nodatasets",
                "--time",
                "1500",
                "--set",
                "update exchange rates 0",
                "--set",
                "save config 0",
                "--set",
                "save definitions 0",
                "--set",
                "save mode 0",
                "--set",
                "max history 0",
                "--set",
                "color 0",
                "--set",
                "unicode 0",
                safe_expression,
            ]
            code, answer, error = bounded_process(argv, env)
        if (
            code
            or error
            or not answer
            or any(marker in answer.lower() for marker in ("error:", "warning:"))
        ):
            return fail(
                command,
                2,
                "calculation_failed",
                (error or answer or "Calculation failed")[:1000],
                state="error",
            )
        answer = answer.rsplit(" = ", 1)[-1].strip()
        return ok(command, text=answer, state="valid", answer=answer)
    except (TimeoutError, subprocess.TimeoutExpired):
        return fail(command, 1, "timeout", "Calculation timed out", state="error")
    except CalculationCancelled:
        return fail(command, 1, "cancelled", "Calculation cancelled", state="error")
    except (OSError, ValueError) as error:
        return fail(command, 1, "calculation_failed", str(error), state="error")
