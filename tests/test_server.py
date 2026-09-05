from gimp_agent_mcp import recipes, segmentation, server


def test_tool_surface():
    names = sorted(t.name for t in server.mcp._tool_manager.list_tools())
    assert len(names) == 32, names
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
    }


def test_segmentation_availability_is_a_bool():
    assert isinstance(segmentation.available(), bool)
    assert "u2net" in segmentation.MODELS
