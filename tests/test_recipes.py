import pytest

from gimp_agent_mcp import recipes


def test_every_recipe_compiles_and_declares_params():
    listed = recipes.list_recipes()
    assert {r["name"] for r in listed} >= {"telegram_sticker", "fit_and_export"}
    for entry in listed:
        module = recipes.get_recipe(entry["name"])
        compile(module.SOURCE, f"<recipe {entry['name']}>", "exec")
        assert module.DESCRIPTION
        for name, spec in module.PARAMS.items():
            assert "description" in spec, (entry["name"], name)
            assert spec.get("required") or "default" in spec, (entry["name"], name)


def test_resolve_params_applies_defaults_and_validates():
    resolved = recipes.resolve_params("telegram_sticker", {"input_path": "a.png", "output_path": "b.png"})
    assert resolved["canvas"] == 512 and resolved["stroke_px"] == 8
    with pytest.raises(ValueError):
        recipes.resolve_params("telegram_sticker", {"input_path": "a.png"})
    with pytest.raises(ValueError):
        recipes.resolve_params("telegram_sticker", {"input_path": "a", "output_path": "b", "bogus": 1})
    with pytest.raises(KeyError):
        recipes.get_recipe("nope")


def test_recipe_sources_assign_result_and_use_injected_names():
    for entry in recipes.list_recipes():
        src = recipes.get_recipe(entry["name"]).SOURCE
        assert "result =" in src
        assert "params[" in src


@pytest.mark.parametrize("value", [0, -1, True, 2.5, "4", None])
def test_pack_rejects_invalid_columns(value):
    with pytest.raises(ValueError, match="columns"):
        recipes.resolve_params("sprite_sheet_pack", {"input_paths": ["a.png"], "output_path": "out.png", "columns": value})


@pytest.mark.parametrize("key,value", [("tile_width", 0), ("tile_height", -2), ("margin", -1), ("spacing", -1), ("skip_empty", "false")])
def test_slice_rejects_bad_geometry_and_boolean(key, value):
    params = {"input_path": "a.png", "output_dir": "out", "tile_width": 16, "tile_height": 16, key: value}
    with pytest.raises(ValueError, match=key):
        recipes.resolve_params("sprite_sheet_slice", params)


def test_defaults_are_not_shared_between_runs():
    first = recipes.resolve_params("icon_set", {"input_path": "a.png", "output_dir": "out"})
    first["sizes"].append(999)
    second = recipes.resolve_params("icon_set", {"input_path": "a.png", "output_dir": "out"})
    assert 999 not in second["sizes"]


def test_nullable_manifest_and_nonfinite_numbers():
    assert recipes.resolve_params("compose", {"output_path": "a.png"})["manifest"] is None
    from types import SimpleNamespace
    old = recipes._REGISTRY
    try:
        recipes._REGISTRY = {"test": SimpleNamespace(PARAMS={"n": {"type": "number", "required": True}})}
        for value in [True, float("nan"), float("inf")]:
            with pytest.raises(ValueError):
                recipes.resolve_params("test", {"n": value})
    finally:
        recipes._REGISTRY = old
