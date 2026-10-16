from gimp_agent_mcp import recipes, segmentation, server


def test_help_topics_cover_the_surface():
    from gimp_agent_mcp import help as helpdoc

    assert set(helpdoc.topics()) >= {"start", "filters", "colours", "text", "masks", "paths", "layers", "measure", "recipes", "compose", "errors"}
    assert "Read this first" in server.gimp_help.__doc__
    assert "compose" in helpdoc.get("recipes")
    assert helpdoc.get("all").count("\n") > 100


def test_tool_surface():
    names = sorted(t.name for t in server.mcp._tool_manager.list_tools())
    assert len(names) == 41, names
    assert "gimp_help" in names
    for required in (
        "gimp_measure",
        "gimp_snapshot",
        "gimp_render_compare",
        "gimp_select",
        "gimp_layer_mask",
        "gimp_layer",
        "gimp_layer_effect",
        "gimp_text",
        "gimp_list_fonts",
        "gimp_path",
        "gimp_remove_background",
        "gimp_batch_recipe",
        "gimp_adjust",
        "gimp_canvas",
        "gimp_draw",
        "gimp_cancel",
        "gimp_brand",
    ):
        assert required in names


def test_status_returns_active_context_from_mocked_bridge(monkeypatch):
    context = {
        "active_image_id": 7,
        "active_layer_ids": [18],
        "selection": {"non_empty": True, "x1": 2, "y1": 3, "x2": 12, "y2": 13},
        "active_image_dirty": True,
    }
    monkeypatch.setattr(server._client, "ping", lambda: {"mode": "gui", "images": [], **context})
    monkeypatch.setattr(server, "_freshness", lambda _info: {})

    result = server.gimp_status()

    assert {key: result[key] for key in context} == context
    assert result["connected"] is True


def test_list_images_returns_images_and_active_context_from_mocked_bridge(monkeypatch):
    payload = {
        "images": [{"id": 7, "name": "Untitled", "selected_layer_ids": [18]}],
        "active_image_id": 7,
        "active_layer_ids": [18],
        "selection": {"non_empty": False, "x1": 0, "y1": 0, "x2": 0, "y2": 0},
        "active_image_dirty": False,
    }
    monkeypatch.setattr(server, "_call", lambda op, params=None, timeout=None: payload if op == "list_images" else None)

    assert server.gimp_list_images() == payload


def test_adjust_resolves_operation_before_apply(monkeypatch):
    calls = []

    def fake_call(op, params=None, timeout=None):
        calls.append((op, params))
        if op == "filter_describe":
            return {"op": params["op"], "properties": []}
        return {"ok": True}

    monkeypatch.setattr(server, "_call", fake_call)
    result = server.gimp_adjust(7, "blur", {"radius": 4}, mode="append")
    assert [op for op, _ in calls] == ["filter_describe", "apply_filter"]
    assert calls[1][1]["params"] == {"std-dev-x": 4, "std-dev-y": 4}
    assert result["editable"] is True and result["operation"]["op"] == "gegl:gaussian-blur"


def test_canvas_describes_then_executes_and_reports_dimensions(monkeypatch):
    calls = []

    def fake_call(op, params=None, timeout=None):
        calls.append((op, params))
        if op == "pdb_describe":
            return {"name": params["name"]}
        if op == "image_info":
            return {"id": params["image_id"], "width": 320, "height": 180}
        return {"status": "success"}

    monkeypatch.setattr(server, "_call", fake_call)
    result = server.gimp_canvas(3, "scale", width=320, height=180)
    assert [op for op, _ in calls] == ["pdb_describe", "pdb_call", "image_info"]
    assert calls[1][1]["args"] == {"image": 3, "new-width": 320, "new-height": 180}
    assert result["image"]["width"] == 320


def test_draw_rectangle_reports_every_runtime_operation(monkeypatch):
    calls = []

    def fake_call(op, params=None, timeout=None):
        calls.append((op, params))
        if op == "context":
            return {"foreground": "#112233"}
        if op == "pdb_describe":
            return {"name": params["name"]}
        if op == "layer":
            return {"id": params["layer_id"]}
        return {"status": "success"}

    monkeypatch.setattr(server, "_call", fake_call)
    result = server.gimp_draw(2, 9, "rectangle", "#ff0000", x=5, y=6, width=20, height=10)
    names = [op["name"] for op in result["operations"]]
    assert names == [
        "gimp-context-set-foreground",
        "gimp-image-select-rectangle",
        "gimp-drawable-edit-fill",
        "gimp-selection-none",
        "gimp-context-set-foreground",
    ]
    assert result["layer"] == {"id": 9}
    first_mutation = next(i for i, (op, _params) in enumerate(calls) if op == "pdb_call")
    assert all(op in ("context", "pdb_describe") for op, _params in calls[:first_mutation])
    assert calls[-2][1]["args"] == {"foreground": "#112233"}


def test_recipe_catalogue():
    assert {r["name"] for r in recipes.list_recipes()} == {
        "telegram_sticker",
        "fit_and_export",
        "web_optimise",
        "icon_set",
        "watermark",
        "contact_sheet",
        "sprite_sheet_slice",
        "sprite_sheet_pack",
        "sprite_atlas_pack",
        "social_crop",
        "compose",
    }


def test_segmentation_availability_is_a_bool():
    assert isinstance(segmentation.available(), bool)
    assert "u2net" in segmentation.MODELS


class _FakeShutdownClient:
    """Stands in for server._client: records the shutdown_and_wait call and returns or raises what it is given."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []
        self.closed = 0

    def shutdown_and_wait(self, quit_gimp=True, wait_seconds=30.0, poll=0.1):
        self.calls.append({"quit_gimp": quit_gimp, "wait_seconds": wait_seconds})
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return dict(self.outcome)

    def close(self):
        self.closed += 1


def test_shutdown_waits_and_reports_full_exit(monkeypatch):
    fake = _FakeShutdownClient({"stopping": True, "quit_gimp": True, "accepting": False, "stopped": True, "waited": 0.4})
    monkeypatch.setattr(server, "_client", fake)
    result = server.gimp_shutdown(quit_gimp=True)
    assert fake.calls == [{"quit_gimp": True, "wait_seconds": 30.0}]
    assert result["fully_exited"] is True and result["timed_out"] is False and result["waited"] == 0.4
    assert fake.closed >= 1


def test_shutdown_leaves_the_quit_default_to_the_bridge(monkeypatch):
    fake = _FakeShutdownClient({"stopping": True, "quit_gimp": False, "stopped": True, "waited": 0.2})
    monkeypatch.setattr(server, "_client", fake)
    result = server.gimp_shutdown()
    assert fake.calls[0]["quit_gimp"] is None
    # A GUI bridge stopped without quitting: the bridge is gone but GIMP is still open.
    assert result["stopped"] is True and result["fully_exited"] is False


def test_shutdown_timeout_is_reported_not_raised(monkeypatch):
    from gimp_agent_mcp.bridge_client import BridgeError

    fake = _FakeShutdownClient(BridgeError("bridge on port 1 (pid 2) ... still present after 30.0s", "ShutdownTimeout"))
    monkeypatch.setattr(server, "_client", fake)
    result = server.gimp_shutdown(quit_gimp=True)
    assert result["fully_exited"] is False and result["timed_out"] is True and result["stopped"] is False
    assert "still present" in result["detail"]
    assert fake.closed >= 1


def test_shutdown_with_no_bridge_does_not_claim_gimp_exited(monkeypatch):
    fake = _FakeShutdownClient({"stopped": True, "already_stopped": True, "waited": 0.0})
    monkeypatch.setattr(server, "_client", fake)
    result = server.gimp_shutdown(quit_gimp=True)
    assert result["already_stopped"] is True and result["fully_exited"] is None


def test_shutdown_other_bridge_errors_become_tool_errors(monkeypatch):
    import pytest

    from gimp_agent_mcp.bridge_client import BridgeError

    monkeypatch.setattr(server, "_client", _FakeShutdownClient(BridgeError("boom", "BridgeError")))
    with pytest.raises(server.ToolError, match="boom"):
        server.gimp_shutdown(quit_gimp=True)
