"""Cancellation and progress without GIMP.

``FakeBridge`` mirrors the plug-in's request loop on one thread with plain sockets: one operation runs at a
time, and long operations call ``Job.checkpoint``, whose poll answers cancel/jobs from any connection (including
a connection that arrives mid-operation) while ordinary requests wait. The shared pieces, ``JobTracker`` and
``split_control_requests``, are the real ones from ``agent_bridge_core`` that the plug-in uses.
"""

import os
import select
import socket
import threading
import time

import pytest

from gimp_agent_mcp import server
from gimp_agent_mcp.bridge_client import BridgeClient, BridgeError
from gimp_agent_mcp.plugin import agent_bridge_core as core

TOKEN = "test-token-0123456789"


class FakeBridge:
    def __init__(self, steps=200, step_seconds=0.005):
        self.steps = steps
        self.step_seconds = step_seconds
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.sock.setblocking(False)
        self.port = self.sock.getsockname()[1]
        self.jobs = core.JobTracker(poll=self.poll)
        self.buffers = {}
        self.stopping = False
        self.handled = []
        self.started = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)

    # -- plumbing, as in the plug-in ------------------------------------------------

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stopping = True
        self.thread.join(5)
        for s in list(self.buffers):
            s.close()
        self.sock.close()

    def accept_all(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except (BlockingIOError, InterruptedError, OSError):
                return
            conn.setblocking(False)
            self.buffers[conn] = b""

    def read(self, conn):
        while True:
            try:
                data = conn.recv(65536)
            except (BlockingIOError, InterruptedError):
                return True
            except OSError:
                return False
            if not data:
                return False
            self.buffers[conn] += data

    def send(self, conn, payload):
        conn.setblocking(True)
        try:
            conn.sendall(core.encode_message(payload))
        finally:
            conn.setblocking(False)

    def poll(self):
        self.accept_all()
        for conn in list(self.buffers):
            self.read(conn)
            remaining, controls = core.split_control_requests(self.buffers[conn], TOKEN)
            self.buffers[conn] = remaining
            for request in controls:
                self.send(conn, self.handle(request, conn))

    def process(self, conn):
        while b"\n" in self.buffers.get(conn, b""):
            line, self.buffers[conn] = self.buffers[conn].split(b"\n", 1)
            if line.strip():
                self.send(conn, self.handle(core.decode_message(line), conn))

    def serve(self):
        while not self.stopping:
            readable, _, _ = select.select([self.sock, *self.buffers], [], [], 0.02)
            for s in readable:
                if s is self.sock:
                    self.accept_all()
                elif not self.read(s):
                    self.buffers.pop(s, None)
                    s.close()
            for conn in list(self.buffers):
                self.process(conn)

    def handle(self, request, conn):
        req_id = request.get("id")
        if request.get("token") != TOKEN:
            return {"id": req_id, "ok": False, "error": {"type": "Unauthorized", "message": "bad token"}}
        op = request["op"]
        params = request.get("params") or {}
        job = None
        if op not in core.CONTROL_OPS:
            send = None
            if request.get("progress"):
                def send(progress, _conn=conn, _id=req_id):
                    self.send(_conn, {"id": _id, "progress": progress})
            job = self.jobs.start(req_id, op, image_id=params.get("image_id"), send_progress=send)
        self.handled.append((op, time.monotonic()))
        try:
            response = {"ok": True, "result": getattr(self, "op_" + op)(params)}
        except core.OperationCancelled as exc:
            response = {"ok": False, "error": {"type": "OperationCancelled", "message": str(exc)}}
        finally:
            if job is not None:
                self.jobs.finish(job)
        response["id"] = req_id
        return response

    # -- ops ------------------------------------------------------------------------

    def op_slow(self, params):
        self.started.set()
        for i in range(self.steps):
            self.jobs.checkpoint(i / self.steps, f"step {i + 1} of {self.steps}")
            time.sleep(self.step_seconds)
        self.jobs.checkpoint(1.0, "done", cancellable=False)
        return {"steps": self.steps}

    def op_exec(self, params):
        return {"stdout": "", "result": self.op_slow(params)}

    def op_echo(self, params):
        return params

    def op_cancel(self, params):
        return self.jobs.cancel(image_id=params.get("image_id"), request_id=params.get("request_id"))

    def op_jobs(self, params):
        return self.jobs.status()


def client_for(bridge):
    return BridgeClient(port=bridge.port, token=TOKEN)


def run_in_thread(fn):
    box = {}

    def target():
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - surfaced by the test
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, box


# --------------------------------------------------------------------------- core pieces


def test_checkpoint_reports_progress_and_cancels():
    sent = []
    now = [0.0]
    tracker = core.JobTracker(clock=lambda: now[0])
    job = tracker.start("r1", "exec", image_id=3, send_progress=sent.append)
    tracker.checkpoint(0.1, "first")
    now[0] = 0.1
    tracker.checkpoint(0.2, "throttled")
    now[0] = 0.5
    tracker.checkpoint(float("nan"), "unknown fraction")
    assert [s["text"] for s in sent] == ["first", "unknown fraction"]
    assert sent[-1]["fraction"] is None and job.checkpoints == 3

    assert tracker.cancel(image_id=4)["cancel_requested"] is False
    assert tracker.cancel(request_id="other")["cancel_requested"] is False
    assert tracker.cancel(image_id=3)["cancel_requested"] is True
    tracker.checkpoint(0.9, "after", cancellable=False)  # progress-only checkpoints never raise
    with pytest.raises(core.OperationCancelled, match="exec was cancelled"):
        tracker.checkpoint(0.95, "stop here")
    tracker.finish(job)
    assert tracker.status() == {"running": None}
    assert tracker.cancel()["cancel_requested"] is False
    tracker.checkpoint(0.5)  # outside a job: no-op


def test_progress_send_failure_does_not_stop_work():
    tracker = core.JobTracker()

    def broken(_progress):
        raise OSError("client gone")

    job = tracker.start("r", "exec", send_progress=broken)
    tracker.checkpoint(0.5)
    assert job.send_progress is None
    tracker.checkpoint(0.6)


def test_split_control_requests_keeps_order_and_partial_lines():
    def line(op, token=TOKEN, rid="x"):
        return core.encode_message({"id": rid, "token": token, "op": op, "params": {}})

    buffer = line("layer", rid="a") + line("cancel", rid="b") + b"not json\n" + line("cancel", token="bad", rid="c") + line("jobs", rid="d") + b'{"id": "e", "tok'
    remaining, controls = core.split_control_requests(buffer, TOKEN)
    assert [c["id"] for c in controls] == ["b", "d"]
    assert remaining == line("layer", rid="a") + b"not json\n" + line("cancel", token="bad", rid="c") + b'{"id": "e", "tok'


# --------------------------------------------------------------------------- fake long operation over sockets


def test_cancel_reaches_a_running_operation_and_progress_streams():
    with FakeBridge() as bridge:
        progress = []
        worker = client_for(bridge)
        thread, box = run_in_thread(lambda: worker.call("slow", {"image_id": 7}, timeout=10, on_progress=progress.append))
        assert bridge.started.wait(5)
        time.sleep(0.05)

        canceller = client_for(bridge)
        status = canceller.call("jobs", timeout=5)
        assert status["running"]["op"] == "slow" and status["running"]["image_id"] == 7
        answer = canceller.call("cancel", {"image_id": 7}, timeout=5)
        assert answer["cancel_requested"] is True
        thread.join(5)
        canceller.close()
        worker.close()

    assert isinstance(box.get("error"), BridgeError)
    assert box["error"].error_type == "OperationCancelled"
    fractions = [p["fraction"] for p in progress]
    assert fractions and fractions == sorted(fractions) and fractions[-1] < 1.0


def test_ordinary_requests_wait_and_run_in_order_after_the_operation():
    with FakeBridge(steps=60) as bridge:
        worker = client_for(bridge)
        thread, box = run_in_thread(lambda: worker.call("slow", timeout=10))
        assert bridge.started.wait(5)
        other = client_for(bridge)
        assert other.call("echo", {"n": 1}, timeout=10) == {"n": 1}
        thread.join(5)
        other.close()
        worker.close()
        ops = [op for op, _t in bridge.handled]
    assert box["value"] == {"steps": 60}
    assert ops.index("echo") > ops.index("slow")


def test_without_progress_flag_only_one_reply_arrives():
    with FakeBridge(steps=20, step_seconds=0.02) as bridge:
        client = client_for(bridge)
        assert client.call("slow", timeout=10) == {"steps": 20}
        assert client.call("echo", {"ok": 1}, timeout=10) == {"ok": 1}
        client.close()


# --------------------------------------------------------------------------- MCP server tools


@pytest.fixture
def fake_env(monkeypatch, tmp_path):
    bridge = FakeBridge()
    bridge.__enter__()
    monkeypatch.setenv("GIMP_AGENT_PORT", str(bridge.port))
    monkeypatch.setenv("GIMP_AGENT_TOKEN", TOKEN)
    monkeypatch.setenv("GIMP_AGENT_BRIDGE_FILE", str(tmp_path / "missing-bridge.json"))
    monkeypatch.setattr(server, "_client", client_for(bridge))
    yield bridge
    server._client.close()
    bridge.__exit__(None, None, None)


def test_gimp_cancel_stops_a_running_recipe(fake_env):
    thread, box = run_in_thread(lambda: server.gimp_run_recipe("fit_and_export", {"input_path": "a.png", "output_path": "b.png"}))
    assert fake_env.started.wait(5)
    answer = server.gimp_cancel()
    thread.join(5)
    assert answer["cancel_requested"] is True and answer["running"]["op"] == "exec"
    assert "OperationCancelled" in str(box.get("error"))


def test_gimp_cancel_when_idle_is_harmless(fake_env):
    assert server.gimp_cancel()["cancel_requested"] is False
    assert server.gimp_run_recipe("fit_and_export", {"input_path": "a.png", "output_path": "b.png"})["result"] == {"steps": 200}


def test_gimp_cancel_stops_a_batch_between_files(fake_env, tmp_path):
    for name in ("a", "b", "c", "d"):
        (tmp_path / f"{name}.png").write_bytes(b"")
    fake_env.steps = 40
    thread, box = run_in_thread(
        lambda: server.gimp_batch_recipe("fit_and_export", os.path.join(str(tmp_path), "*.png"), str(tmp_path / "out"))
    )
    assert fake_env.started.wait(5)
    server.gimp_cancel()
    thread.join(10)
    result = box["value"]
    assert result["cancelled"] is True
    assert result["count"] < 4 and len(result["not_started"]) == 4 - result["count"]


def test_progress_reporter_scales_and_never_goes_backwards(monkeypatch):
    seen = []

    class Ctx:
        async def report_progress(self, progress, total=None, message=None):
            seen.append((progress, total, message))

    def run_sync(fn, *args):
        import asyncio

        asyncio.run(fn(*args))

    monkeypatch.setattr(server.anyio.from_thread, "run", run_sync)
    report = server._progress_reporter(Ctx(), start=0.5, span=0.25)
    report({"fraction": 0.0, "text": "file 3"})
    report({"fraction": 0.8, "text": "half"})
    report({"fraction": None, "text": "no fraction"})
    report({"fraction": 0.4, "text": "late"})
    assert seen == [(50.0, 100.0, "file 3"), (70.0, 100.0, "half"), (70.0, 100.0, "no fraction"), (70.0, 100.0, "late")]
    assert server._progress_reporter(None) is None


def test_context_parameter_is_not_part_of_tool_schemas():
    tools = {t.name: t for t in server.mcp._tool_manager.list_tools()}
    for name in ("gimp_run_recipe", "gimp_batch_recipe", "gimp_edit_batch", "gimp_apply_filter", "gimp_run_python"):
        assert "ctx" not in tools[name].parameters.get("properties", {}), name
    assert "gimp_cancel" in tools
