import pytest

from gimp_agent_mcp.plugin.agent_bridge_core import (
    resolve_edit_refs,
    validate_edit_steps,
    validate_render_overlay,
)


@pytest.mark.parametrize("steps", [[], [{}], [{"op": "shutdown", "params": {}}], [{"op": "layer", "params": []}], [{"op": "exec", "params": {}}], [{"op": "layer", "params": {}}] * 101])
def test_batch_rejects_unsafe_or_malformed_requests(steps):
    with pytest.raises(ValueError):
        validate_edit_steps(steps)


def test_refs_resolve_nested_data_without_mutating_inputs():
    params = {"layer_id": {"$ref": "0.id"}, "nested": [{"$ref": "1.layer.id"}]}
    assert resolve_edit_refs(params, [{"id": 12}, {"layer": {"id": 14}}]) == {"layer_id": 12, "nested": [14]}
    assert params["layer_id"] == {"$ref": "0.id"}


@pytest.mark.parametrize("ref", ["-1.id", "1.id", "0.missing", "__import__('os')"])
def test_refs_cannot_read_future_steps_or_evaluate_code(ref):
    with pytest.raises(ValueError):
        resolve_edit_refs({"$ref": ref}, [{"id": 12}])


def test_render_overlay_normalises_points_and_deduplicates_modes():
    overlay, points, spacing = validate_render_overlay(
        ["GRID", "grid", "layers"], [{"x": 12, "y": 4.5, "label": "edge"}], 64
    )
    assert overlay == ["grid", "layers", "points"]
    assert points == [{"x": 12.0, "y": 4.5, "label": "edge"}]
    assert spacing == 64


@pytest.mark.parametrize(
    ("overlay", "points", "spacing"),
    [(["unknown"], [], 100), ("grid", [], 100), ([], [{"x": float("nan"), "y": 2}], 100), ([], [], 1)],
)
def test_render_overlay_rejects_bad_input(overlay, points, spacing):
    with pytest.raises(ValueError):
        validate_render_overlay(overlay, points, spacing)
