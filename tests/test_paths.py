from pathlib import Path

from gimp_agent_mcp import paths
from gimp_agent_mcp.plugin import agent_bridge_core as core


def test_config_dir_picks_newest_3x(tmp_path, monkeypatch):
    root = tmp_path / "GIMP"
    for name in ("2.10", "3.0", "3.2", "3.10", "junk"):
        (root / name).mkdir(parents=True)
    monkeypatch.delenv("GIMP_AGENT_CONFIG_DIR", raising=False)
    monkeypatch.setattr(paths, "candidate_config_roots", lambda: [root])
    assert paths.gimp_config_dir() == root / "3.10"
    assert paths.bridge_file() == root / "3.10" / core.BRIDGE_FILE_NAME
    assert paths.plugin_install_dir() == root / "3.10" / "plug-ins" / "gimp-agent-bridge"


def test_config_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("GIMP_AGENT_CONFIG_DIR", str(tmp_path))
    assert paths.gimp_config_dir() == tmp_path


def test_config_dir_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("GIMP_AGENT_CONFIG_DIR", raising=False)
    monkeypatch.setattr(paths, "candidate_config_roots", lambda: [tmp_path / "missing"])
    assert paths.gimp_config_dir() is None
    assert paths.bridge_file() is None


def test_launch_command_shapes(tmp_path, monkeypatch):
    gui = tmp_path / "gimp-3.2.exe"
    console = tmp_path / "gimp-console-3.2.exe"
    gui.write_bytes(b"")
    console.write_bytes(b"")
    monkeypatch.setattr(paths, "find_gimp", lambda: paths.GimpExecutables(gui=gui, console=console))
    headless = paths.launch_command("headless")
    assert headless[0] == str(console)
    assert "-i" in headless and "--batch-interpreter=python-fu-eval" in headless
    assert core.PROCEDURE_NAME in headless[-1]
    gui_cmd = paths.launch_command("gui")
    assert gui_cmd[0] == str(gui) and "--new-instance" in gui_cmd and "-i" not in gui_cmd


def test_launch_command_without_console_uses_no_interface(tmp_path, monkeypatch):
    gui = tmp_path / "gimp"
    gui.write_bytes(b"")
    monkeypatch.setattr(paths, "find_gimp", lambda: paths.GimpExecutables(gui=gui, console=None))
    cmd = paths.launch_command("headless")
    assert cmd[0] == str(gui) and "--no-interface" in cmd


def test_gimp_exe_env_override(tmp_path, monkeypatch):
    exe = tmp_path / "gimp-3.2.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("GIMP_AGENT_GIMP_EXE", str(exe))
    found = paths.find_gimp()
    assert found.gui == Path(exe)
