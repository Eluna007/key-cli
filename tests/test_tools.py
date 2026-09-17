from datetime import datetime, timezone as datetime_zone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

import pytest

from key_cli import main
from key_cli.tools import calculator, currency, timezone


def test_public_tool_contract(capsys):
    assert main(["tool", "currency", "--expression=1 USD to USD"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schemaVersion"] == 1
    assert result["command"] == "tool.currency"
    assert result["error"] is None
    assert result["answer"] == "1 USD"
    assert main(["tool", "time"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_arguments"


def test_catalog_does_not_evaluate(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Completion must not evaluate or fetch")

    monkeypatch.setattr(calculator, "evaluate", forbidden)
    monkeypatch.setattr(currency, "evaluate", forbidden)
    for tool in ("calculator", "currency", "time"):
        assert main(["tool", "catalog", tool]) == 0
        response = json.loads(capsys.readouterr().out)
        assert response["command"] == "tool.catalog"
        assert response["candidates"]


@pytest.mark.parametrize(
    "expression",
    [
        "save x",
        "plot(1)",
        "load(foo)",
        "1\nquit",
        "1;2",
        "x=2",
        "/quit",
        "system(1)",
        "10 to USD",
        "1" * 1025,
    ],
)
def test_calculator_rejects_side_effects(expression, monkeypatch):
    def forbidden(*args):
        raise AssertionError("Invalid input must not spawn a process")

    monkeypatch.setattr(calculator, "bounded_process", forbidden)
    assert calculator.evaluate(expression).json()["state"] == "error"


def test_calculator_argv_isolation_and_diagnostics(monkeypatch):
    monkeypatch.setattr(calculator.shutil, "which", lambda name: "/fake/qalc")

    def run(argv, env):
        assert argv[-1] == "(-2 + 4)"
        assert "update exchange rates 0" in argv
        assert env["HOME"] == env["XDG_CONFIG_HOME"] == env["XDG_DATA_HOME"]
        return 0, "-2 + 4 = 2", ""

    monkeypatch.setattr(calculator, "bounded_process", run)
    assert calculator.evaluate("-2 + 4").json()["answer"] == "2"
    monkeypatch.setattr(
        calculator,
        "bounded_process",
        lambda *args: (0, "warning: Division by zero.\n1 / 0 = 1 / 0", ""),
    )
    assert calculator.evaluate("1/0").json()["state"] == "error"


def test_calculator_limits_and_child_reaping(monkeypatch):
    monkeypatch.setattr(calculator, "TIMEOUT", 0.1)
    with pytest.raises(TimeoutError):
        calculator.bounded_process([sys.executable, "-c", "import time; time.sleep(2)"], {})
    monkeypatch.setattr(calculator, "MAX_OUTPUT", 64)
    with pytest.raises(ValueError):
        calculator.bounded_process([sys.executable, "-c", "print('a'*1000)"], {})


def test_calculator_cancellation_exits_with_child(tmp_path):
    pid_file = tmp_path / "child.pid"
    child = "from pathlib import Path; import os,sys,time; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(20)"
    script = tmp_path / "cancel.py"
    script.write_text(
        "from key_cli.tools.calculator import bounded_process\nimport sys\n"
        f"bounded_process([sys.executable, '-c', {child!r}, {str(pid_file)!r}], {{}})\n"
    )
    process = subprocess.Popen(
        [sys.executable, str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + 2
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pid_file.exists(), "Calculator child did not start"
        child_pid = int(pid_file.read_text())
        process.terminate()
        process.communicate(timeout=2)
        assert process.returncode != 0
        import os

        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=3)


def test_currency_precision_cache_and_stale(tmp_path):
    calls = []

    def fetch(base, quote):
        calls.append((base, quote))
        return {"base": base, "quote": quote, "date": "2026-09-16", "rate": Decimal("7.123456789")}

    first = currency.evaluate(
        "0.1 usd to cny", directory=tmp_path, clock=lambda: 100000, fetch=fetch
    ).json()
    assert first["converted"] == "0.7123456789"
    assert first["date"] == "2026-09-16"
    assert first["source"] == "frankfurter-v2-ecb"
    second = currency.evaluate(
        "2 USD to CNY", directory=tmp_path, clock=lambda: 100001, fetch=fetch
    ).json()
    assert second["cache"] == "cached"
    assert len(calls) == 1

    def offline(*args):
        raise OSError("offline")

    stale = currency.evaluate(
        "2 USD to CNY", directory=tmp_path, clock=lambda: 200000, fetch=offline
    ).json()
    assert stale["cache"] == "stale"
    assert stale["fetchedAt"] == 100000
    assert (
        currency.evaluate(
            "2 USD to EUR", directory=tmp_path, clock=lambda: 200000, fetch=offline
        ).json()["state"]
        == "error"
    )
    assert (
        currency.evaluate("2 USD to USD", directory=tmp_path, fetch=offline).json()["cache"]
        == "identity"
    )


def test_currency_duplicate_requests_and_backoff(tmp_path):
    calls = []

    def fetch(base, quote):
        calls.append((base, quote))
        time.sleep(0.05)
        return {"base": base, "quote": quote, "date": "2026-09-16", "rate": "1.5"}

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(
            pool.map(
                lambda _: currency.evaluate("3 EUR to USD", directory=tmp_path, fetch=fetch).json(),
                range(3),
            )
        )
    assert all(result["converted"] == "4.5" for result in results)
    assert len(calls) == 1
    calls.clear()

    def offline(base, quote):
        calls.append((base, quote))
        raise OSError("offline")

    for _ in range(3):
        currency.evaluate("1 EUR to CNY", directory=tmp_path, clock=lambda: 200000, fetch=offline)
    assert len(calls) == 1


def test_currency_rejects_wrong_pair(tmp_path):
    result = currency.evaluate(
        "1 USD to CNY",
        directory=tmp_path,
        fetch=lambda *args: {"base": "EUR", "quote": "CNY", "date": "2026-09-16", "rate": "7"},
    ).json()
    assert result["state"] == "error"
    assert "answer" not in result


def test_timezone_dates_dst_and_aliases():
    clock = datetime(2026, 9, 17, 1, tzinfo=datetime_zone.utc)
    result = timezone.evaluate("09:00 America/Los_Angeles to Asia/Shanghai", now=clock).json()
    assert result["source"]["date"] == "2026-09-16"
    assert result["target"]["date"] == "2026-09-17"
    assert result["dayDelta"] == 1
    result = timezone.evaluate(
        "now to tokyo", now=clock, local_zone=ZoneInfo("America/Los_Angeles")
    ).json()
    assert result["source"]["zone"] == "America/Los_Angeles"
    assert result["source"]["offset"] == "-07:00"
    assert result["target"]["zone"] == "Asia/Tokyo"
    nonexistent = timezone.evaluate("2026-03-08 02:30 America/Los_Angeles to UTC").json()
    assert nonexistent["error"]["code"] == "nonexistent_time"
    expression = "2026-11-01 01:30 America/Los_Angeles to UTC"
    repeated = timezone.evaluate(expression).json()
    assert repeated["state"] == "ambiguous"
    assert [row["offset"] for row in repeated["candidates"]] == ["-07:00", "-08:00"]
    assert (
        timezone.evaluate(expression, 0).json()["answer"]
        != timezone.evaluate(expression, 1).json()["answer"]
    )
    assert timezone.evaluate("09:00 CST to UTC").json()["state"] == "error"
