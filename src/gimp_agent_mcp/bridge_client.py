"""TCP client for the GIMP Agent Bridge, plus GIMP process launching."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from . import paths
from .plugin import agent_bridge_core as core


class BridgeError(RuntimeError):
    def __init__(self, message: str, error_type: str = "BridgeError", trace: str | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.trace = trace


class BridgeUnavailable(BridgeError):
    pass


class BridgeClient:
    def __init__(self, timeout: float = core.DEFAULT_TIMEOUT, port: int | None = None, token: str | None = None):
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._rfile = None
        self._wfile = None
        self._token: str | None = None
        self._port: int | None = None
        # Explicit overrides win over the environment and the bridge file (used by the launcher).
        self.fixed_port = port
        self.fixed_token = token

    # -- connection ------------------------------------------------------------------

    def _load_bridge_info(self) -> tuple[str, int, str]:
        host = core.DEFAULT_HOST
        env_port = os.environ.get("GIMP_AGENT_PORT")
        env_token = os.environ.get("GIMP_AGENT_TOKEN")
        info = None
        bf = paths.bridge_file()
        if bf is not None:
            info = core.read_bridge_file(str(bf))
        # Precedence: explicit override, then the bridge file (the bridge may have fallen back to another
        # port than the one requested), then GIMP_AGENT_PORT as the requested port, then the default.
        if self.fixed_port:
            port = self.fixed_port
        elif info:
            port = int(info["port"])
        elif env_port:
            port = int(env_port)
        else:
            port = core.DEFAULT_PORT
        token = self.fixed_token or env_token or (info["token"] if info else None)
        if not token:
            raise BridgeUnavailable(
                "No bridge token found. Start GIMP with the bridge (gimp_launch) or click "
                "Filters > Development > Start Agent Bridge inside GIMP 3."
            )
        return host, port, token

    def connect(self) -> None:
        if self._sock is not None:
            return
        host, port, token = self._load_bridge_info()
        try:
            sock = socket.create_connection((host, port), timeout=5.0)
        except OSError as exc:
            raise BridgeUnavailable(
                f"GIMP Agent Bridge is not reachable on {host}:{port} ({exc}). "
                "Run gimp_launch, or start the bridge from GIMP's Filters > Development menu."
            ) from exc
        sock.settimeout(self.timeout)
        self._sock = sock
        self._rfile = sock.makefile("rb")
        self._wfile = sock.makefile("wb")
        self._token = token
        self._port = port

    def close(self) -> None:
        for f in (self._rfile, self._wfile):
            try:
                if f:
                    f.close()
            except OSError:
                pass
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = self._rfile = self._wfile = None

    def is_connected(self) -> bool:
        return self._sock is not None

    # -- calls ------------------------------------------------------------------------

    def call(self, op: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                self.connect()
                assert self._sock and self._rfile and self._wfile
                if timeout is not None:
                    self._sock.settimeout(timeout)
                req_id = uuid.uuid4().hex
                self._wfile.write(core.encode_message({"id": req_id, "token": self._token, "op": op, "params": params or {}}))
                self._wfile.flush()
                line = self._rfile.readline()
                if not line:
                    raise ConnectionError("bridge closed the connection")
                response = core.decode_message(line)
                if timeout is not None:
                    self._sock.settimeout(self.timeout)
                break
            except (OSError, ConnectionError, ValueError) as exc:
                last_exc = exc
                self.close()
                if attempt == 1 or isinstance(exc, BridgeUnavailable):
                    raise BridgeUnavailable(f"bridge call {op} failed: {exc}") from exc
                time.sleep(0.2)
        else:  # pragma: no cover
            raise BridgeUnavailable(str(last_exc))

        if not response.get("ok"):
            err = response.get("error") or {}
            raise BridgeError(err.get("message", "unknown bridge error"), err.get("type", "BridgeError"), err.get("traceback"))
        return response.get("result")

    def ping(self) -> dict[str, Any] | None:
        try:
            info = self.call("ping", timeout=5.0)
        except BridgeError:
            return None
        # Follow the newest bridge: if the bridge file now names another port (a GUI bridge started after a
        # headless one, say), drop this connection so the next call reconnects there.
        try:
            _host, port, _token = self._load_bridge_info()
            if self._port is not None and port != self._port:
                self.close()
                info = self.call("ping", timeout=5.0)
        except BridgeError:
            pass
        return info


# --------------------------------------------------------------------------- launching


def _log_path() -> Path:
    cfg = paths.gimp_config_dir()
    base = cfg if cfg else Path.home()
    return base / "gimp-agent-launch.log"


def launch_gimp(mode: str = "gui", wait_seconds: float = 90.0, client: BridgeClient | None = None, retries: int = 1) -> dict[str, Any]:
    """Start GIMP 3 with the bridge procedure running, then wait until it answers.

    GIMP occasionally loses the batch plug-in during start-up and keeps running without a bridge;
    in that case the process we started is killed and the launch is retried once.
    """
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return _launch_once(mode, wait_seconds, client)
        except BridgeUnavailable as exc:
            last = exc
            if attempt < retries and "did not answer" in str(exc):
                time.sleep(1.0)
                continue
            raise
    raise BridgeUnavailable(str(last))  # pragma: no cover


def _launch_once(mode: str, wait_seconds: float, client: BridgeClient | None) -> dict[str, Any]:
    if mode not in ("gui", "headless"):
        raise ValueError("mode must be 'gui' or 'headless'")
    install_dir = paths.plugin_install_dir()
    if install_dir is None or not (install_dir / "gimp-agent-bridge.py").is_file():
        raise BridgeUnavailable(
            "The bridge plug-in is not installed in GIMP's plug-ins folder. Run: gimp-agent-mcp install-plugin"
        )
    cmd = paths.launch_command(mode)
    log = _log_path()
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
    env = dict(os.environ)
    env["GIMP_AGENT_MODE"] = mode
    with open(log, "ab") as logfh:
        logfh.write(f"\n=== launch {time.strftime('%Y-%m-%d %H:%M:%S')} mode={mode}\n{cmd}\n".encode())
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=logfh,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            close_fds=True,
            env=env,
        )
    client = client or BridgeClient()
    launched_at = time.time()
    bf = paths.bridge_file()
    deadline = launched_at + wait_seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            raise BridgeUnavailable(f"GIMP exited early with code {proc.returncode}; see {log}")
        # Identify *our* bridge by the bridge file it writes, not by port: an older bridge may still hold the
        # default port and would answer a blind ping.
        written = core.read_bridge_file(str(bf)) if bf else None
        if written and float(written.get("started", 0)) >= launched_at - 1.0:
            probe = BridgeClient(port=int(written["port"]), token=str(written["token"]))
            info = probe.ping()
            probe.close()
            if info:
                client.close()  # next call re-reads the bridge file and lands on the new bridge
                return {"pid": proc.pid, "gimp_pid": info.get("pid"), "port": int(written["port"]), "mode": info.get("mode"), "log": str(log), "ping": info}
        time.sleep(0.5)
    # Do not leave a bridge-less GIMP behind; it would block the port and confuse the next launch.
    with open(log, "ab") as logfh:
        logfh.write(f"bridge did not answer within {wait_seconds}s; killing pid {proc.pid}\n".encode())
    try:
        proc.kill()
    except OSError:
        pass
    raise BridgeUnavailable(f"GIMP started (pid {proc.pid}) but the bridge did not answer within {wait_seconds}s; see {log}")
