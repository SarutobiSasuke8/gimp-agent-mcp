"""Runs the full smoke test against a real GIMP 3. Skipped unless GIMP_AGENT_LIVE=1."""

import os

import pytest

from gimp_agent_mcp import paths

pytestmark = pytest.mark.skipif(
    os.environ.get("GIMP_AGENT_LIVE") != "1" or paths.find_gimp().any is None,
    reason="set GIMP_AGENT_LIVE=1 with GIMP 3 installed to run the live smoke test",
)


def test_smoke_headless():
    from gimp_agent_mcp.smoke import run_smoke

    assert run_smoke(mode="headless", keep=False, verbose=True) == 0
