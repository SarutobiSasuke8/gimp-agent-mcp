from gimp_agent_mcp import recipes, segmentation, server


def test_help_topics_cover_the_surface():
    from gimp_agent_mcp import help as helpdoc

    assert set(helpdoc.topics()) >= {"start", "filters", "colours", "text", "masks", "paths", "layers", "measure", "recipes", "compose", "errors"}
    assert "Read this first" in server.gimp_help.__doc__
    assert "compose" in helpdoc.get("recipes")
    assert helpdoc.get("all").count("\n") > 100


def test_tool_surface():
    names = sorted(t.name for t in server.mcp._tool_manager.list_tools())
    assert len(names) == 33, names
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
    ):
        assert required in names


def test_recipe_catalogue():
    assert {r["name"] for r in recipes.list_recipes()} == {
        "telegram_sticker",
        "fit_and_export",
        "web_optimise",
        "icon_set",
        "watermark",
        "contact_sheet",
        "sprite_sheet_slice",
        "compose",
    }


def test_segmentation_availability_is_a_bool():
    assert isinstance(segmentation.available(), bool)
    assert "u2net" in segmentation.MODELS
