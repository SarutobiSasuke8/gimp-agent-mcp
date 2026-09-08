from gimp_agent_mcp import recipes, segmentation, server


def test_help_topics_cover_the_surface():
    from gimp_agent_mcp import help as helpdoc

    assert set(helpdoc.topics()) >= {"start", "filters", "colours", "text", "masks", "paths", "layers", "measure", "recipes", "compose", "errors"}
    assert "Read this first" in server.gimp_help.__doc__
    assert "compose" in helpdoc.get("recipes")
    assert helpdoc.get("all").count("\n") > 100


def test_tool_surface():
    names = sorted(t.name for t in server.mcp._tool_manager.list_tools())
    assert len(names) == 39, names
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
    ):
        assert required in names


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
        "compose",
    }


def test_segmentation_availability_is_a_bool():
    assert isinstance(segmentation.available(), bool)
    assert "u2net" in segmentation.MODELS
