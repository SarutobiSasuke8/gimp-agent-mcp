"""Command line: serve (default), install-plugin, doctor, launch, smoke."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from pathlib import Path

from . import paths
from .plugin import agent_bridge_core as core

PLUGIN_FILES = ("gimp-agent-bridge.py", "agent_bridge_core.py")


def _plugin_source_dir() -> Path:
    return Path(__file__).resolve().parent / "plugin"


def cmd_install_plugin(args: argparse.Namespace) -> int:
    target = Path(args.dir) if args.dir else paths.plugin_install_dir()
    if target is None:
        print("Could not find a GIMP 3 config directory. Start GIMP 3 once, or pass --dir.", file=sys.stderr)
        return 2
    target.mkdir(parents=True, exist_ok=True)
    src = _plugin_source_dir()
    for name in PLUGIN_FILES:
        dst = target / name
        shutil.copyfile(src / name, dst)
        if os.name == "posix":
            dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Installed bridge plug-in to {target}")
    print("Restart GIMP, then use Filters > Development > Start Agent Bridge, or run: gimp-agent-mcp launch")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .bridge_client import BridgeClient

    exes = paths.find_gimp()
    cfg = paths.gimp_config_dir()
    install = paths.plugin_install_dir()
    bf = paths.bridge_file()
    info = core.read_bridge_file(str(bf)) if bf else None
    report = {
        "gimp_gui": str(exes.gui) if exes.gui else None,
        "gimp_console": str(exes.console) if exes.console else None,
        "config_dir": str(cfg) if cfg else None,
        "plugin_installed": bool(install and all((install / f).is_file() for f in PLUGIN_FILES)),
        "plugin_dir": str(install) if install else None,
        "bridge_file": str(bf) if bf else None,
        "bridge_file_present": info is not None,
        "bridge_port": info["port"] if info else None,
    }
    ping = BridgeClient().ping()
    report["bridge_reachable"] = ping is not None
    if ping:
        report["gimp_version"] = ping.get("gimp_version")
        report["mode"] = ping.get("mode")
        report["open_images"] = len(ping.get("images", []))
    print(json.dumps(report, indent=2))
    ok = report["gimp_gui"] or report["gimp_console"]
    return 0 if ok else 1


def cmd_launch(args: argparse.Namespace) -> int:
    from .bridge_client import BridgeUnavailable, launch_gimp

    try:
        result = launch_gimp(mode=args.mode, wait_seconds=args.wait)
    except (BridgeUnavailable, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in result.items() if k != "ping"}, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import run

    run()
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    from .smoke import run_smoke

    return run_smoke(mode=args.mode, keep=args.keep, segmentation=args.segmentation)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gimp-agent-mcp", description="MCP server for GIMP 3")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="run the MCP server on stdio (default)")

    p_install = sub.add_parser("install-plugin", help="copy the bridge plug-in into GIMP's plug-ins folder")
    p_install.add_argument("--dir", help="override the plug-in target directory")

    sub.add_parser("doctor", help="report what was found and whether the bridge answers")

    p_launch = sub.add_parser("launch", help="start GIMP with the bridge running")
    p_launch.add_argument("--mode", choices=("gui", "headless"), default="gui")
    p_launch.add_argument("--wait", type=float, default=90.0)

    p_smoke = sub.add_parser("smoke", help="launch headless GIMP and exercise the whole tool surface")
    p_smoke.add_argument("--mode", choices=("gui", "headless"), default="headless")
    p_smoke.add_argument("--keep", action="store_true", help="leave GIMP running afterwards")
    p_smoke.add_argument("--segmentation", action="store_true", help="also run the AI cut-out check (downloads a small model on first use)")

    args = parser.parse_args(argv)
    command = args.command or "serve"
    return {
        "serve": cmd_serve,
        "install-plugin": cmd_install_plugin,
        "doctor": cmd_doctor,
        "launch": cmd_launch,
        "smoke": cmd_smoke,
    }[command](args)


if __name__ == "__main__":
    sys.exit(main())
