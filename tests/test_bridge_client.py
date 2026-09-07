import io
import json

import pytest

from gimp_agent_mcp.bridge_client import BridgeClient, BridgeUnavailable
from gimp_agent_mcp.plugin import agent_bridge_core as core


class Socket:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)

    def close(self):
        pass


class Writer(io.BytesIO):
    def close(self):
        self.saved = self.getvalue()
        super().close()


def attached(monkeypatch, reader):
    c = BridgeClient()
    c._sock = Socket()
    c._wfile = Writer()
    c._rfile = reader
    c._token = "test"
    calls = []
    monkeypatch.setattr(c, "connect", lambda: calls.append(True))
    return c, calls


def test_lost_response_does_not_replay_an_edit(monkeypatch):
    c, connects = attached(monkeypatch, io.BytesIO(b""))
    writer = c._wfile
    with pytest.raises(BridgeUnavailable, match="NOT replayed"):
        c.call("layer", {"action": "duplicate", "layer_id": 1})
    assert len(writer.saved.splitlines()) == 1
    assert len(connects) == 1
    assert c._sock is None


def test_mismatched_response_is_rejected(monkeypatch):
    c, _ = attached(monkeypatch, io.BytesIO(core.encode_message({"id": "wrong", "ok": True})))
    with pytest.raises(BridgeUnavailable, match="id does not match"):
        c.call("ping")


def test_successful_response_restores_timeout(monkeypatch):
    class Reader:
        def readline(self):
            req = json.loads(c._wfile.getvalue())
            return core.encode_message({"id": req["id"], "ok": True, "result": 17})
    c, _ = attached(monkeypatch, Reader())
    assert c.call("ping", timeout=5) == 17
    assert c._sock.timeouts == [5, c.timeout]



def test_posix_gimp_uses_its_installation_python(monkeypatch):
    from gimp_agent_mcp import bridge_client
    monkeypatch.setattr(bridge_client.sys, "platform", "linux")
    monkeypatch.setenv("PATH", "/project/.venv/bin:/usr/bin")
    monkeypatch.setenv("PYTHONPATH", "/project/vendor")
    monkeypatch.setenv("PYTHONHOME", "/project/python")
    monkeypatch.setenv("VIRTUAL_ENV", "/project/.venv")
    env = bridge_client._gimp_environment("headless", str(__import__("pathlib").Path("/usr/bin/gimp")))
    assert env["PATH"].split(bridge_client.os.pathsep)[0].endswith("bin")
    assert env["PATH"].endswith("/project/.venv/bin:/usr/bin")
    assert not {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"} & env.keys()
    assert env["GIMP_AGENT_MODE"] == "headless"
