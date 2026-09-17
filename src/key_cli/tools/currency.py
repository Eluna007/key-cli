from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from ..utils.output import fail, ok

# Current ECB reference currencies. This local completion catalog never queries
# the network; the fixed provider still validates availability for each pair.
CURRENCIES = {
    "EUR": "Euro",
    "USD": "US Dollar",
    "JPY": "Japanese Yen",
    "CZK": "Czech Koruna",
    "DKK": "Danish Krone",
    "GBP": "Pound Sterling",
    "HUF": "Hungarian Forint",
    "PLN": "Polish Zloty",
    "RON": "Romanian Leu",
    "SEK": "Swedish Krona",
    "CHF": "Swiss Franc",
    "ISK": "Icelandic Krona",
    "NOK": "Norwegian Krone",
    "TRY": "Turkish Lira",
    "AUD": "Australian Dollar",
    "BRL": "Brazilian Real",
    "CAD": "Canadian Dollar",
    "CNY": "Chinese Yuan",
    "HKD": "Hong Kong Dollar",
    "IDR": "Indonesian Rupiah",
    "ILS": "Israeli Shekel",
    "INR": "Indian Rupee",
    "KRW": "South Korean Won",
    "MXN": "Mexican Peso",
    "MYR": "Malaysian Ringgit",
    "NZD": "New Zealand Dollar",
    "PHP": "Philippine Peso",
    "SGD": "Singapore Dollar",
    "THB": "Thai Baht",
    "ZAR": "South African Rand",
}
SOURCE = "frankfurter-v2-ecb"
TTL = 86400
BACKOFF = 60
MAX_RESPONSE = 16384
GRAMMAR = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+([A-Za-z]{3})\s+to\s+([A-Za-z]{3})$", re.I)


def cache_root():
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "key-cli" / "currency"


def fetch_rate(base, quote):
    # Amounts and user expressions are deliberately absent from the URL.
    url = f"https://api.frankfurter.dev/v2/providers/ecb/rate/{base.lower()}/{quote.lower()}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "key-cli"})
    with urlopen(request, timeout=5) as response:
        data = response.read(MAX_RESPONSE + 1)
    if len(data) > MAX_RESPONSE:
        raise ValueError("Rate response is too large")
    return json.loads(data, parse_float=Decimal)


def validate_rate(value, base, quote):
    if (
        not isinstance(value, dict)
        or str(value.get("base", "")).upper() != base
        or str(value.get("quote", "")).upper() != quote
    ):
        raise ValueError("Rate currency pair does not match")
    rate = Decimal(str(value["rate"]))
    if not rate.is_finite() or rate <= 0 or rate.adjusted() > 12:
        raise ValueError("Invalid exchange rate")
    data_date = date.fromisoformat(value["date"]).isoformat()
    return {"base": base, "quote": quote, "rate": str(rate), "date": data_date}


def read_cache(path, base, quote):
    try:
        if path.stat().st_size > MAX_RESPONSE:
            return {}
        value = json.loads(path.read_text())
        if value.get("source") != SOURCE:
            return {}
        if "rate" in value:
            validate_rate(value, base, quote)
            if "fetchedAt" not in value:
                return {}
        for key in ("fetchedAt", "retryAfter"):
            if key in value and (not isinstance(value[key], (int, float)) or value[key] < 0):
                return {}
        return value
    except (OSError, ValueError, KeyError, InvalidOperation, TypeError):
        return {}


def write_cache(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream)
            stream.flush()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def evaluate(expression, *, directory=None, clock=time.time, fetch=fetch_rate):
    command = "tool.currency"
    if not expression.strip():
        return ok(command, state="empty")
    if len(expression) > 256:
        return fail(
            command, 2, "invalid_expression", "Currency expression is too long", state="error"
        )
    match = GRAMMAR.fullmatch(expression.strip())
    if not match:
        return ok(command, state="incomplete", hint="100 USD to CNY")
    amount, base, quote = match[1], match[2].upper(), match[3].upper()
    if base not in CURRENCIES or quote not in CURRENCIES:
        return fail(
            command, 2, "unsupported_currency", "Choose an ECB reference currency", state="error"
        )
    if base == quote:
        answer = f"{amount} {quote}"
        return ok(
            command,
            state="valid",
            answer=answer,
            amount=amount,
            converted=amount,
            base=base,
            quote=quote,
            rate="1",
            source=SOURCE,
            date=None,
            fetchedAt=None,
            cache="identity",
            approximate=False,
        )
    try:
        directory = directory or cache_root()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{SOURCE}-{base}-{quote}.json"
        # A per-pair lock merges concurrent CLI requests. A waiting process reads
        # the winner's cache rather than issuing a duplicate request.
        with (directory / f"{SOURCE}-{base}-{quote}.lock").open("a") as lock:
            deadline = time.monotonic() + 6
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Exchange rate request is busy")
                    time.sleep(0.025)
            now = clock()
            cached = read_cache(path, base, quote)
            fresh = "rate" in cached and 0 <= now - cached.get("fetchedAt", 0) < TTL
            status = "cached" if fresh else "stale"
            if not fresh and now >= cached.get("retryAfter", 0):
                try:
                    value = validate_rate(fetch(base, quote), base, quote)
                    cached = dict(value, source=SOURCE, fetchedAt=now)
                    status = "fresh"
                except (OSError, ValueError, KeyError, TypeError, InvalidOperation, URLError):
                    cached = dict(cached, source=SOURCE, retryAfter=now + BACKOFF)
                write_cache(path, cached)
            if "rate" not in cached:
                return fail(
                    command,
                    1,
                    "rate_unavailable",
                    "Exchange rate unavailable; try again later",
                    state="error",
                )
        with localcontext() as context:
            context.prec = 50
            converted = format(Decimal(amount) * Decimal(cached["rate"]), "f")
        answer = f"{converted} {quote}"
        return ok(
            command,
            text=answer,
            state="valid",
            answer=answer,
            amount=amount,
            converted=converted,
            base=base,
            quote=quote,
            rate=cached["rate"],
            source=SOURCE,
            date=cached["date"],
            fetchedAt=cached["fetchedAt"],
            cache=status,
            approximate=True,
        )
    except (OSError, ValueError, InvalidOperation) as error:
        return fail(command, 1, "rate_unavailable", str(error), state="error")
