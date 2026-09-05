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
