"""Locate GIMP 3 executables and the per-user config directory on each platform."""

from __future__ import annotations

import os
import platform
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .plugin import agent_bridge_core as core

_VERSION_DIR = re.compile(r"^3\.\d+$")


def _version_key(name: str) -> tuple[int, ...]:
    return tuple(int(p) for p in name.split("."))


def candidate_config_roots() -> list[Path]:
    system = platform.system()
    roots: list[Path] = []
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            roots.append(Path(appdata) / "GIMP")
    elif system == "Darwin":
        roots.append(Path.home() / "Library" / "Application Support" / "GIMP")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        roots.append(Path(xdg) / "GIMP")
        roots.append(Path.home() / ".var" / "app" / "org.gimp.GIMP" / "config" / "GIMP")
        roots.append(Path.home() / "snap" / "gimp" / "current" / ".config" / "GIMP")
    return roots


def gimp_config_dir() -> Path | None:
    """The newest GIMP 3.x per-user config directory, or None if GIMP 3 has never run."""
    override = os.environ.get("GIMP_AGENT_CONFIG_DIR")
    if override:
        return Path(override)
    best: tuple[tuple[int, ...], Path] | None = None
    for root in candidate_config_roots():
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if child.is_dir() and _VERSION_DIR.match(child.name):
                key = _version_key(child.name)
                if best is None or key > best[0]:
                    best = (key, child)
    return best[1] if best else None


def bridge_file() -> Path | None:
    override = os.environ.get("GIMP_AGENT_BRIDGE_FILE")
    if override:
        return Path(override)
    cfg = gimp_config_dir()
    return cfg / core.BRIDGE_FILE_NAME if cfg else None


def plugin_install_dir() -> Path | None:
    cfg = gimp_config_dir()
    return cfg / "plug-ins" / "gimp-agent-bridge" if cfg else None


@dataclass(frozen=True)
class GimpExecutables:
    gui: Path | None
    console: Path | None

    @property
    def any(self) -> Path | None:
        return self.gui or self.console


def _first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        if p.is_file():
            return p
    return None


def _glob_versions(folder: Path, stem: str, ext: str) -> list[Path]:
    if not folder.is_dir():
        return []
    found = sorted(folder.glob(f"{stem}-3.*{ext}"), reverse=True)
    generic = folder / f"{stem}-3{ext}"
    if generic.is_file():
        found.append(generic)
    return found


def find_gimp() -> GimpExecutables:
    override = os.environ.get("GIMP_AGENT_GIMP_EXE")
    if override:
        exe = Path(override)
        console = exe.with_name(exe.name.replace("gimp-", "gimp-console-")) if "gimp-" in exe.name else None
        return GimpExecutables(gui=exe if exe.is_file() else None, console=console if console and console.is_file() else None)

    system = platform.system()
    gui_candidates: list[Path] = []
    console_candidates: list[Path] = []

    if system == "Windows":
        bins = []
        for base in (
            os.environ.get("LOCALAPPDATA", "") and Path(os.environ["LOCALAPPDATA"]) / "Programs" / "GIMP 3" / "bin",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "GIMP 3" / "bin",
            Path(os.environ.get("ProgramW6432", r"C:\Program Files")) / "GIMP 3" / "bin",
        ):
            if base:
                bins.append(Path(base))
        for b in bins:
            gui_candidates += _glob_versions(b, "gimp", ".exe")
            console_candidates += _glob_versions(b, "gimp-console", ".exe")
    elif system == "Darwin":
        macos = Path("/Applications/GIMP.app/Contents/MacOS")
        gui_candidates += [macos / "gimp", macos / "GIMP"]
        console_candidates += [macos / "gimp-console"]
    else:
        for name in ("gimp-3.2", "gimp-3.0", "gimp3", "gimp"):
            found = shutil.which(name)
            if found:
                gui_candidates.append(Path(found))
        for name in ("gimp-console-3.2", "gimp-console-3.0", "gimp-console"):
            found = shutil.which(name)
            if found:
                console_candidates.append(Path(found))

    return GimpExecutables(gui=_first_existing(gui_candidates), console=_first_existing(console_candidates))


def start_bridge_batch_code(headless: bool = False) -> str:
    """Python executed by GIMP's python-fu-eval batch interpreter to start the bridge.

    The bridge procedure blocks until shutdown. Headless runs then quit GIMP through the PDB, because
    gimp-console stays alive after batch commands otherwise.
    """
    code = (
        "proc=Gimp.get_pdb().lookup_procedure('"
        + core.PROCEDURE_NAME
        + "');cfg=proc.create_config();cfg.set_property('run-mode',Gimp.RunMode.NONINTERACTIVE);proc.run(cfg)"
    )
    if headless:
        code += ";q=Gimp.get_pdb().lookup_procedure('gimp-quit');qc=q.create_config();qc.set_property('force',True);q.run(qc)"
    return code


def launch_command(mode: str = "gui") -> list[str]:
    exes = find_gimp()
    if mode == "headless":
        exe = exes.console or exes.gui
        if exe is None:
            raise FileNotFoundError("GIMP 3 executable not found; set GIMP_AGENT_GIMP_EXE")
        cmd = [str(exe)]
        if exes.console is None:
            cmd.append("--no-interface")
        cmd += ["-i", "--batch-interpreter=python-fu-eval", "-b", start_bridge_batch_code(headless=True)]
        return cmd
    exe = exes.gui
    if exe is None:
        raise FileNotFoundError("GIMP 3 executable not found; set GIMP_AGENT_GIMP_EXE")
    return [str(exe), "--new-instance", "--batch-interpreter=python-fu-eval", "-b", start_bridge_batch_code()]
