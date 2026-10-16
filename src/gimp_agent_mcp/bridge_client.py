"""TCP client for the GIMP Agent Bridge, plus GIMP process launching."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
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
        self._lock = threading.RLock()
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
        with self._lock:
            return self._connect_locked()

    def _connect_locked(self) -> None:
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
        with self._lock:
            return self._close_locked()

    def _close_locked(self) -> None:
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

    def call(
        self,
        op: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> Any:
        """Send one request and wait for its reply.

        With ``on_progress`` the request asks the bridge for interim progress lines, which are passed to the
        callback as they arrive. ``timeout`` applies to each wait, so a long operation that keeps reporting
        progress is not cut off by it.
        """
        with self._lock:
            if on_progress is None:
                return self._call_locked(op, params, timeout)
            return self._call_locked(op, params, timeout, on_progress)

    def _call_locked(
        self,
        op: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> Any:
        self.connect()
        assert self._sock and self._rfile and self._wfile
        req_id = uuid.uuid4().hex
        message: dict[str, Any] = {"id": req_id, "token": self._token, "op": op, "params": params or {}}
        if on_progress is not None:
            message["progress"] = True
        payload = core.encode_message(message)
        try:
            self._sock.settimeout(self.timeout if timeout is None else timeout)
            self._wfile.write(payload)
            self._wfile.flush()
            while True:
                line = self._rfile.readline()
                if not line:
                    raise ConnectionError("bridge closed the connection")
                response = core.decode_message(line)
                if response.get("id") != req_id:
                    raise ValueError("bridge response id does not match request")
                if "progress" in response and "ok" not in response:
                    if on_progress is not None:
                        try:
                            on_progress(response["progress"])
                        except Exception:  # noqa: BLE001 - a reporting failure must not lose the reply
                            pass
                    continue
                break
        except (OSError, ConnectionError, ValueError) as exc:
            self.close()
            raise BridgeUnavailable(
                f"Response to {op!r} was lost or invalid; its outcome is unknown. "
                "The request was NOT replayed. Reconnect and inspect the image before retrying an edit. "
                f"Details: {exc}"
            ) from exc
        finally:
            if self._sock is not None:
                self._sock.settimeout(self.timeout)

        if not response.get("ok"):
            err = response.get("error") or {}
            message = err.get("message", "unknown bridge error")
            if err.get("type") == core.STOPPING_ERROR:
                # The bridge accepted a shutdown and will not do more work; treat it like no bridge at all.
                self.close()
                raise BridgeUnavailable(message, core.STOPPING_ERROR)
            if err.get("type") == "UnknownOp":
                # The usual cause is a plug-in left over from an older release.
                message = f"{message}. {paths.PLUGIN_UPDATE_HINT}"
            raise BridgeError(message, err.get("type", "BridgeError"), err.get("traceback"))
        return response.get("result")

    def ping(self) -> dict[str, Any] | None:
        with self._lock:
            return self._ping_locked()

    def _ping_locked(self) -> dict[str, Any] | None:
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

    def shutdown_and_wait(self, quit_gimp: bool = True, wait_seconds: float = 30.0, poll: float = 0.1) -> dict[str, Any]:
        """Ask the bridge to stop, then return only once it is really gone.

        The bridge answers ``shutdown`` before it stops, and GIMP quits a little later. A caller that moves on
        straight away (the next CI step, or a new launch) could otherwise still reach the old bridge and lose its
        socket mid-request when GIMP exits. "Gone" means: nothing accepts connections on the old port, the bridge
        file no longer names the old bridge, and (on POSIX) the bridge plug-in process has exited.
        """
        with self._lock:
            before = self._ping_locked()
            if before is None:
                return {"stopped": True, "already_stopped": True, "waited": 0.0}
            port = self._port
            pid = before.get("pid")
            result = self._call_locked("shutdown", {"quit_gimp": quit_gimp}, timeout=10.0)
            self._close_locked()
        started = time.monotonic()
        deadline = started + wait_seconds
        while True:
            state = _bridge_presence(port, pid)
            if not any(state.values()):
                return {**(result or {}), "stopped": True, "waited": round(time.monotonic() - started, 3)}
            if time.monotonic() >= deadline:
                raise BridgeError(
                    f"bridge on port {port} (pid {pid}) was asked to shut down but is still present after "
                    f"{wait_seconds}s: {state}",
                    "ShutdownTimeout",
                )
            time.sleep(poll)


def _bridge_presence(port: int | None, pid: Any) -> dict[str, bool]:
    """What is still left of a bridge that was asked to stop. All False means it has gone."""
    listening = False
    if port:
        try:
            with socket.create_connection((core.DEFAULT_HOST, port), timeout=1.0):
                listening = True
        except OSError:
            listening = False
    bf = paths.bridge_file()
    info = core.read_bridge_file(str(bf)) if bf is not None else None
    file_names_it = bool(info and pid is not None and str(info.get("pid")) == str(pid))
    return {"listening": listening, "bridge_file": file_names_it, "process": _pid_alive(pid)}


def _pid_alive(pid: Any) -> bool:
    if sys.platform == "win32" or not isinstance(pid, int) or pid <= 0:
        return False  # Windows: port and bridge file are the signal; there is no cheap signal-0 probe.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    # In a container whose PID 1 does not reap orphans, an exited plug-in lingers as a zombie; that is gone too.
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as fh:
            state = fh.read().rsplit(")", 1)[-1].split()[0]
        return state not in ("Z", "X")
    except (OSError, IndexError):
        return True


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


def _gimp_environment(mode: str, executable: str) -> dict[str, str]:
    env = dict(os.environ)
    env["GIMP_AGENT_MODE"] = mode
    # GIMP's Python plug-ins belong to GIMP's installation, not the MCP virtualenv.
    # In particular uv prepends .venv/bin, whose python3 cannot import distro gi.
    if sys.platform != "win32":
        env["PATH"] = str(Path(executable).resolve().parent) + os.pathsep + env.get("PATH", "")
        for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
            env.pop(key, None)
    return env


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
    env = _gimp_environment(mode, cmd[0])
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
