from __future__ import annotations

import json
import queue
import shutil
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from key_cli import main
from key_cli.commands import audio
from key_cli.recording import state, watch
from key_cli.utils.process import capture


@pytest.mark.parametrize("kind", ["record", "audio"])
def test_idle_watch_protocol(kind, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert main([kind, "watch", "--format", "jsonl"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == state.base_state() | {
        "command": f"{kind}.watch",
        "ok": True,
        "event": "snapshot",
    }
    assert not state.state_path(kind).exists()


def test_strict_revision_and_response_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(state.time, "time", lambda: 1)
    value = state.base_state()
    revisions = []
    for status in [
        "starting",
        "recording",
        "paused",
        "recording",
        "stopping",
        "finalizing",
        "completed",
        "error",
    ]:
        with state.locked("audio"):
            value["state"] = status
            state.save("audio", value)
        revisions.append(value["updatedAtMs"])
        assert state.load("audio") == value
    assert revisions == list(range(1000, 1008))


@pytest.fixture
def recorder(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    executable = tmp_path / "ffmpeg"
    shutil.copy2(sys.executable, executable)
    temporary = tmp_path / "partial.m4a"
    temporary.write_bytes(b"fixture audio")
    process = subprocess.Popen(
        [str(executable), "-c", "import signal; signal.pause()", str(temporary)]
    )
    identity = capture(process.pid)
    value = state.base_state() | {
        "state": "recording",
        "sessionId": "test-session",
        "pid": process.pid,
        "processStartTicks": str(identity.start_ticks),
        "temporaryPath": str(temporary),
        "outputPath": str(tmp_path / "final.m4a"),
        "source": {"type": "mic"},
    }
    with state.locked("audio"):
        state.save("audio", value)
    yield process, value
    if process.poll() is None:
        process.kill()
    process.wait()


def subscribe(kind="audio"):
    results = queue.Queue()

    def read():
        try:
            for payload in watch.events(kind):
                results.put(payload)
        except Exception as exc:
            results.put(exc)

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    initial = results.get(timeout=5)
    assert initial["event"] == "snapshot"
    assert initial["state"] == "recording"
    return thread, results


@pytest.mark.parametrize("kind", ["audio", "record"])
def test_changed_then_unexpected_pidfd_exit(recorder, kind):
    process, value = recorder
    if kind == "record":
        from pathlib import Path

        directory = Path(value["outputPath"]).parent
        (directory / "ffmpeg").rename(directory / "gpu-screen-recorder")
        with state.locked(kind):
            state.save(kind, value)
    thread, results = subscribe(kind)
    with state.locked(kind):
        value["state"] = "paused"
        state.save(kind, value)
    changed = results.get(timeout=5)
    assert changed["event"] == "changed"
    assert changed["state"] == "paused"
    process.kill()
    process.wait()
    failed = results.get(timeout=5)
    assert failed["state"] == "error"
    assert failed["error"]["code"] == "recorder_exited"
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert state.load(kind)["error"] == failed["error"]


@pytest.mark.parametrize("source", ["mic", "system"])
def test_stop_lock_pidfd_and_successful_audio_finalize(recorder, monkeypatch, source):
    process, value = recorder
    value["source"] = {"type": source}
    with state.locked("audio"):
        state.save("audio", value)
    thread, results = subscribe()
    waiting = threading.Event()
    original_reconcile = watch.reconcile_exit

    def reconcile(*args):
        waiting.set()
        return original_reconcile(*args)

    monkeypatch.setattr(watch, "reconcile_exit", reconcile)

    def stop(*args):
        process.kill()
        process.wait()
        # The watcher has reached blocking lock acquisition while stop owns it.
        assert waiting.wait(5)
        return True, False, ""

    monkeypatch.setattr(audio, "stop_verified", stop)
    monkeypatch.setattr(audio.shutil, "which", lambda name: "/fixture/ffprobe")
    monkeypatch.setattr(
        audio.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"format": {"duration": "1"}, "streams": [{"codec_type": "audio"}]}),
        ),
    )
    result = audio.run(SimpleNamespace(action="stop"))
    assert result.exit_code == 0
    assert result.payload["state"] == "completed"
    assert result.payload["error"] is None
    from pathlib import Path

    assert Path(result.payload["outputPath"]).read_bytes() == b"fixture audio"
    thread.join(timeout=5)
    assert not thread.is_alive()
    observed = []
    while not results.empty():
        observed.append(results.get_nowait())
    assert observed[-1]["state"] == "completed"
    assert all(item["error"] is None for item in observed)
    assert state.load("audio")["state"] == "completed"
