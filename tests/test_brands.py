import json

import pytest

from gimp_agent_mcp import brands, recipes, server

PROFILE = {
    "name": "example",
    "description": "Test brand",
    "colors": {"bg": "#0f1117", "accent": "#1f3a8a", "text": "#ffffff", "muted": "#a4adbe"},
    "fonts": {"headline": "Bahnschrift Bold", "body": "Segoe UI Regular"},
    "assets": {"logo": "/brand/logo.png"},
    "canvases": {"x-card": [1200, 675], "og": [1200, 630], "square": [1080, 1080]},
}

TOKENS = {
    "brand": "example",
    "canvas": "x-card",
    "background": "@bg",
    "items": [
        {"type": "image", "path": "@logo", "x": 40, "y": 40, "width": 160},
        {"type": "rect", "x": 0, "y": 560, "width": 1200, "height": 115, "color": "@accent"},
        {"type": "text", "text": "Headline", "font": "@headline", "size": 72, "color": "@text", "x": 40, "y": 240},
        {"type": "text", "text": "Sub-line", "font": "@body", "size": 30, "color": "@muted", "x": 42, "y": 330,
         "effects": [{"op": "gegl:dropshadow", "params": {"color": "@bg", "opacity": 0.4}}]},
    ],
}

INLINED = {
    "width": 1200,
    "height": 675,
    "background": "#0f1117",
    "items": [
        {"type": "image", "path": "/brand/logo.png", "x": 40, "y": 40, "width": 160},
        {"type": "rect", "x": 0, "y": 560, "width": 1200, "height": 115, "color": "#1f3a8a"},
        {"type": "text", "text": "Headline", "font": "Bahnschrift Bold", "size": 72, "color": "#ffffff", "x": 40, "y": 240},
        {"type": "text", "text": "Sub-line", "font": "Segoe UI Regular", "size": 30, "color": "#a4adbe", "x": 42, "y": 330,
         "effects": [{"op": "gegl:dropshadow", "params": {"color": "#0f1117", "opacity": 0.4}}]},
    ],
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("GIMP_AGENT_BRANDS_DIR", str(tmp_path))
    brands.save_profile(PROFILE)
    return tmp_path


# --------------------------------------------------------------------------- schema


def test_valid_profile_round_trips(store):
    assert brands.load_profile("example") == PROFILE
    assert (store / "example.json").is_file()
    listed = brands.list_profiles()
    assert listed[0]["name"] == "example" and listed[0]["canvases"] == ["og", "square", "x-card"]


def test_validation_lists_every_problem():
    bad = {
        "name": "Bad Name",
        "colour": {},
        "colors": {"bg": "#12", "ok": "#fff", "x y": "#000"},
        "fonts": {"headline": ""},
        "canvases": {"x-card": [1200], "huge": [40000, 10], "zero": [0, 5], "float": [10.5, 4]},
    }
    with pytest.raises(brands.BrandError) as info:
        brands.validate_profile(bad)
    message = str(info.value)
    for expected in ("Bad Name", "unknown top-level key(s) ['colour']", "colors.bg", "colors.x y",
                     "fonts.headline", "canvases.x-card", "canvases.huge", "canvases.zero", "canvases.float"):
        assert expected in message, expected


def test_token_keys_must_be_unique_across_sections():
    with pytest.raises(brands.BrandError, match="defined in both colors and fonts"):
        brands.validate_profile({"name": "dup", "colors": {"main": "#000"}, "fonts": {"main": "Sans"}})


def test_file_name_must_match_declared_name(store):
    (store / "other.json").write_text(json.dumps({**PROFILE, "name": "example"}), encoding="utf-8")
    with pytest.raises(brands.BrandError, match="must match the file name"):
        brands.load_profile("other")
    assert "error" in next(p for p in brands.list_profiles() if p["name"] == "other")


def test_path_traversal_names_are_rejected(store):
    for name in ("../evil", "a/b", "", "UPPER"):
        with pytest.raises(brands.BrandError, match="brand name"):
            brands.profile_path(name)


def test_unknown_profile_lists_available(store):
    with pytest.raises(brands.BrandError, match=r"no brand profile named 'missing'.*\['example'\]"):
        brands.load_profile("missing")


# --------------------------------------------------------------------------- resolution


def test_token_manifest_resolves_to_the_inlined_manifest(store):
    # compose builds the image from the manifest alone, so equal resolved manifests render identically.
    assert brands.resolve_manifest(TOKENS) == INLINED


def test_unknown_token_names_profile_and_keys(store):
    manifest = {"brand": "example", "items": [{"type": "rect", "color": "@nope"}]}
    with pytest.raises(brands.BrandError) as info:
        brands.resolve_manifest(manifest)
    message = str(info.value)
    assert "'@nope'" in message and "manifest.items[0].color" in message and "'example'" in message
    assert "['accent', 'bg', 'body', 'headline', 'logo', 'muted', 'text']" in message


def test_unknown_canvas_lists_canvases(store):
    with pytest.raises(brands.BrandError, match=r"unknown canvas 'banner'.*\['og', 'square', 'x-card'\]"):
        brands.resolve_manifest({"brand": "example", "canvas": "banner"})


def test_literals_override_profile_values(store):
    manifest = {
        "brand": "example",
        "canvas": "x-card",
        "width": 800,
        "background": "#123456",
        "tokens": {"text": "#ff0000"},
        "items": [{"type": "text", "text": "@handle stays literal", "font": "Arial", "color": "@text", "name": "@layer"}],
    }
    resolved = brands.resolve_manifest(manifest)
    assert resolved["width"] == 800 and resolved["height"] == 675
    assert resolved["background"] == "#123456"
    item = resolved["items"][0]
    assert item == {"type": "text", "text": "@handle stays literal", "font": "Arial", "color": "#ff0000", "name": "@layer"}
    assert "brand" not in resolved and "canvas" not in resolved and "tokens" not in resolved


def test_double_at_escapes_a_literal_at(store):
    resolved = brands.resolve_manifest({"brand": "example", "items": [{"type": "image", "path": "@@2x/logo.png"}]})
    assert resolved["items"][0]["path"] == "@2x/logo.png"


def test_manifest_without_brand_is_unchanged():
    params = recipes.resolve_params("compose", {"output_path": "a.png", "manifest": {"background": "@not-a-token"}})
    assert brands.prepare_compose_params(params) is params


def test_brand_param_and_manifest_path(store, tmp_path):
    path = tmp_path / "card.json"
    path.write_text(json.dumps({k: v for k, v in TOKENS.items() if k != "brand"}), encoding="utf-8")
    params = recipes.resolve_params("compose", {"output_path": "a.png", "manifest_path": str(path), "brand": "example"})
    prepared = brands.prepare_compose_params(params)
    assert prepared["manifest"] == INLINED and prepared["manifest_path"] == ""


# --------------------------------------------------------------------------- server surface


def test_run_recipe_sends_only_literal_values(store, monkeypatch):
    sent = {}

    def fake_call(op, params=None, timeout=None, progress=None):
        sent["code"] = params["code"]
        return {"result": {"ok": True}}

    monkeypatch.setattr(server, "_call", fake_call)
    out = server.gimp_run_recipe("compose", {"output_path": "a.png", "manifest": TOKENS})
    assert out["params"]["manifest"] == INLINED
    assert "@bg" not in sent["code"] and "#0f1117" in sent["code"]


def test_run_recipe_reports_unknown_token(store, monkeypatch):
    monkeypatch.setattr(server, "_call", lambda *a, **k: pytest.fail("must not reach GIMP"))
    with pytest.raises(server.ToolError, match="unknown token '@missing'"):
        server.gimp_run_recipe("compose", {"output_path": "a.png", "manifest": {"brand": "example", "background": "@missing"}})


def test_brand_tool_set_checks_fonts(tmp_path, monkeypatch):
    monkeypatch.setenv("GIMP_AGENT_BRANDS_DIR", str(tmp_path))
    installed = {"Bahnschrift Bold"}

    def fake_call(op, params=None, timeout=None):
        assert op == "list_fonts"
        name = params["filter"].strip("^$").replace("\\", "")
        return {"fonts": [name] if name in installed else []}

    monkeypatch.setattr(server, "_call", fake_call)
    with pytest.raises(server.ToolError, match="Segoe UI Regular"):
        server.gimp_brand("set", profile=PROFILE)
    assert not (tmp_path / "example.json").exists()
    installed.add("Segoe UI Regular")
    saved = server.gimp_brand("set", profile=PROFILE)
    assert saved["fonts_checked"] is True and (tmp_path / "example.json").is_file()
    assert server.gimp_brand("get", name="example")["profile"] == PROFILE
    assert [p["name"] for p in server.gimp_brand("list")["profiles"]] == ["example"]
    assert server.gimp_brand("delete", name="example")["deleted"] is True
    assert server.gimp_brand("list")["profiles"] == []


def test_brand_tool_without_gimp_needs_explicit_skip(tmp_path, monkeypatch):
    monkeypatch.setenv("GIMP_AGENT_BRANDS_DIR", str(tmp_path))

    def offline(*_a, **_k):
        raise server.ToolError("GIMP Agent Bridge is not reachable")

    monkeypatch.setattr(server, "_call", offline)
    with pytest.raises(server.ToolError, match="check_fonts=False"):
        server.gimp_brand("set", profile=PROFILE)
    assert server.gimp_brand("set", profile=PROFILE, check_fonts=False)["fonts_checked"] is False


def test_brand_tool_rejects_invalid_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("GIMP_AGENT_BRANDS_DIR", str(tmp_path))
    with pytest.raises(server.ToolError, match="colors.bg"):
        server.gimp_brand("set", profile={"name": "x", "colors": {"bg": "nope"}}, check_fonts=False)


def test_help_documents_tokens():
    from gimp_agent_mcp import help as helpdoc

    text = helpdoc.get("compose")
    assert "@bg" in text and "gimp_brand" in text and "canvas" in text
