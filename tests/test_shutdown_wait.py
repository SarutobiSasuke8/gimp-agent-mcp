"""Regression tests for the macOS arm64 live-smoke failures of 15 Oct 2026 (runs 38725621437, 38806864812).

The smoke step asked the bridge to shut down and exited at once. The bridge kept listening for its grace period,
so the next proof step found it, attached, and lost its socket when GIMP quit under it. ``shutdown_and_wait``
must only return once a fresh client can no longer reach the old bridge.
"""
from __future__ import annotations

import os
import socket
import threading
import time

import pytest

from gimp_agent_mcp import bridge_client
from gimp_agent_mcp.bridge_client import BridgeClient, BridgeError, BridgeUnavailable
from gimp_agent_mcp.plugin import agent_bridge_core as core

TOKEN = "t" * 32
FAKE_PID = 424242


class FakeBridge:
    """A minimal line-protocol bridge. ``linger`` mimics the old bridge: still listening after shutdown."""

    def __init__(self, bridge_file, linger: float = 0.0, refuse_after_shutdown: bool = False, never_stop: bool = False):
        self.bridge_file = str(bridge_file)
        self.linger = linger
        self.refuse_after_shutdown = refuse_after_shutdown
        self.never_stop = never_stop
        self.shutdown_requested = False
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((core.DEFAULT_HOST, 0))
        self.sock.listen(8)
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]
        self.running = True
        core.write_bridge_file(self.bridge_file, port=self.port, token=TOKEN, pid=FAKE_PID, gimp_version="3.2.4", mode="headless")
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        with conn, conn.makefile("rb") as rf, conn.makefile("wb") as wf:
            for line in rf:
                req = core.decode_message(line)
                if self.refuse_after_shutdown and self.shutdown_requested:
                    resp = {"ok": False, "error": {"type": core.STOPPING_ERROR, "message": core.STOPPING_MESSAGE}}
                elif req["op"] == "ping":
                    resp = {"ok": True, "result": {"gimp_version": "3.2.4", "pid": FAKE_PID}}
                elif req["op"] == "shutdown":
                    self.shutdown_requested = True
                    resp = {"ok": True, "result": {"stopping": True}}
                    if not self.never_stop:
                        threading.Timer(self.linger, self.stop).start()
                else:
                    resp = {"ok": True, "result": None}
                resp["id"] = req["id"]
                wf.write(core.encode_message(resp))
                wf.flush()

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass
        try:
            os.remove(self.bridge_file)
        except OSError:
            pass


@pytest.fixture
def bridge_env(tmp_path, monkeypatch):
    path = tmp_path / "agent-bridge.json"
    monkeypatch.setenv("GIMP_AGENT_BRIDGE_FILE", str(path))
    monkeypatch.delenv("GIMP_AGENT_PORT", raising=False)
    monkeypatch.delenv("GIMP_AGENT_TOKEN", raising=False)
    # The fake bridge has no real plug-in process; process liveness is covered by the live smoke.
    monkeypatch.setattr(bridge_client, "_pid_alive", lambda pid: False)
    return path


def test_shutdown_waits_until_a_lingering_bridge_is_gone(bridge_env):
    fake = FakeBridge(bridge_env, linger=0.4)
    client = BridgeClient()
    assert client.ping() is not None
    started = time.monotonic()
    done = client.shutdown_and_wait(quit_gimp=True, wait_seconds=10)
    elapsed = time.monotonic() - started
    assert done["stopped"] is True
    # The old code returned as soon as the reply arrived, well inside the linger window.
    assert elapsed >= 0.35, elapsed
    assert BridgeClient().ping() is None
    assert not bridge_env.exists()
    fake.stop()


def test_shutdown_with_no_bridge_is_a_no_op(bridge_env):
    assert BridgeClient().shutdown_and_wait(wait_seconds=1)["already_stopped"] is True


def test_shutdown_that_never_completes_fails_loudly(bridge_env):
    fake = FakeBridge(bridge_env, never_stop=True)
    with pytest.raises(BridgeError, match="still present") as info:
        BridgeClient().shutdown_and_wait(wait_seconds=0.5)
    assert info.value.error_type == "ShutdownTimeout"
    fake.stop()


def test_stopping_bridge_counts_as_no_bridge(bridge_env):
    fake = FakeBridge(bridge_env, refuse_after_shutdown=True, never_stop=True)
    first = BridgeClient()
    assert first.call("shutdown", {"quit_gimp": True})["stopping"] is True
    late = BridgeClient()
    # A client arriving during the grace period must not believe a bridge is there to use.
    assert late.ping() is None
    with pytest.raises(BridgeUnavailable, match="shutting down"):
        late.call("new_image", {"width": 8, "height": 8})
    fake.stop()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process probe")
def test_pid_probe_sees_live_and_exited_processes():
    import subprocess
    import sys

    assert bridge_client._pid_alive(os.getpid()) is True
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()  # reaped, so the pid is free
    assert bridge_client._pid_alive(proc.pid) is False


def test_shutdown_without_quit_choice_lets_the_bridge_decide(bridge_env, monkeypatch):
    fake = FakeBridge(bridge_env, linger=0.1)
    client = BridgeClient()
    sent = []
    original = client._call_locked

    def spy(op, params=None, *args, **kwargs):
        sent.append((op, params))
        return original(op, params, *args, **kwargs)

    monkeypatch.setattr(client, "_call_locked", spy)
    assert client.shutdown_and_wait(quit_gimp=None, wait_seconds=10)["stopped"] is True
    assert ("shutdown", {}) in sent
    fake.stop()
