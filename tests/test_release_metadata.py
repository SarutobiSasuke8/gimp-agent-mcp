import json
import re
from pathlib import Path

from gimp_agent_mcp import __version__
from gimp_agent_mcp.plugin.agent_bridge_core import BRIDGE_VERSION


def test_release_versions_cannot_drift():
    root = Path(__file__).resolve().parents[1]
    package = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(), re.M)[1]
    plugin = json.loads((root / ".claude-plugin/plugin.json").read_text())
    registry = json.loads((root / "server.json").read_text())
    assert package == __version__ == BRIDGE_VERSION == plugin["version"] == registry["version"]
    assert all(p["version"] == package for p in registry["packages"])
