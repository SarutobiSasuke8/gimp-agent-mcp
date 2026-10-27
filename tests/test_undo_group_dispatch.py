"""Exercise the real dispatch method without importing gi or starting GIMP."""

import ast
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest

from gimp_agent_mcp.plugin import agent_bridge_core as core


@pytest.mark.parametrize("control_fails", [False, True])
def test_nested_control_request_restores_held_group_owner(control_fails):
    source = Path(__file__).parents[1] / "src/gimp_agent_mcp/plugin/gimp-agent-bridge.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    bridge = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Bridge")
    dispatch = next(node for node in bridge.body if isinstance(node, ast.FunctionDef) and node.name == "_handle_request")
    namespace = {"core": core, "traceback": traceback, "GLib": SimpleNamespace(idle_add=lambda fn: None)}
    exec(compile(ast.Module(body=[dispatch], type_ignores=[]), str(source), "exec"), namespace)

    class DispatchBridge:
        _handle_request = namespace["_handle_request"]
        token = "fixture"
        shutting_down = False
        _request_owner = None
        jobs = core.JobTracker()

        def _drain_buffers(self):
            pass

        def op_jobs(self, params):
            if control_fails:
                raise ValueError("control failure")
            return self.jobs.status()

        def op_edit(self, params):
            assert self._request_owner == id(editor)
            reply = self._handle_request({"id": 2, "token": "fixture", "op": "jobs"}, observer)
            assert reply["ok"] is not control_fails
            # A second edit in the running operation still belongs to the same client.
            assert self._request_owner == id(editor)
            return "edited"

    editor, observer = object(), object()
    instance = DispatchBridge()
    assert instance._handle_request({"id": 1, "token": "fixture", "op": "edit"}, editor) == {
        "ok": True, "result": "edited", "id": 1,
    }
    assert instance._request_owner is None
    assert instance.jobs.current is None
