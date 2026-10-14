import random

import pytest

from gimp_agent_mcp import recipes

social = recipes.get_recipe("social_crop")
plan_crop = social.plan_crop


def _assert_plan(plan, src_w, src_h, out_w, out_h, fx, fy):
    sw, sh = plan["scaled_width"], plan["scaled_height"]
    assert (plan["width"], plan["height"]) == (out_w, out_h)
    assert sw >= out_w and sh >= out_h
    assert 0 <= plan["x"] <= sw - out_w and 0 <= plan["y"] <= sh - out_h
    # The focus pixel's centre, mapped into the scaled image, lies inside the kept rectangle.
    cx, cy = (fx + 0.5) * sw / src_w, (fy + 0.5) * sh / src_h
    assert plan["x"] <= cx < plan["x"] + out_w and plan["y"] <= cy < plan["y"] + out_h
    after = plan["focus_after"]
    assert 0 <= after["x"] < out_w and 0 <= after["y"] < out_h
    assert after == {"x": int(cx - plan["x"]), "y": int(cy - plan["y"])}


def test_profiles_have_their_declared_sizes():
    assert {name: (w, h) for name, (w, h, _use) in social.SOCIAL_PROFILES.items()} == {
        "open_graph": (1200, 630),
        "x_landscape": (1600, 900),
        "instagram_square": (1080, 1080),
        "instagram_portrait": (1080, 1350),
        "story_reel": (1080, 1920),
        "youtube_thumbnail": (1280, 720),
    }
    assert [p[0] for p in social.resolve_profiles("all")] == list(social.SOCIAL_PROFILES)
    assert social.resolve_profiles(["open_graph", {"name": "banner", "width": 1500, "height": 500}]) == [
        ("open_graph", 1200, 630), ("banner", 1500, 500)]


@pytest.mark.parametrize("bad,match", [
    (["nope"], "unknown social profile"),
    ([], "non-empty"),
    ([{"name": "x y", "width": 10, "height": 10}], "custom profile name"),
    ([{"name": "big", "width": 20000, "height": 10}], "1..16384"),
    ([{"name": "f", "width": 10.5, "height": 10}], "integer width"),
    (["open_graph", "open_graph"], "unique"),
    ([3], "names or objects"),
])
def test_bad_profiles_are_refused(bad, match):
    with pytest.raises(ValueError, match=match):
        social.resolve_profiles(bad)


def test_crop_mode_matches_the_documented_example():
    # docs/ASSET_WORKFLOWS.md: 2400x1800 source, focus (1680, 420), Open Graph crop at (1080, 105).
    plan = plan_crop(2400, 1800, 1200, 630, 1680, 420, fit="crop")
    assert (plan["x"], plan["y"], plan["scale"]) == (1080, 105, 1.0)
    assert plan["focus_after"] == {"x": 600, "y": 315}
    corner = plan_crop(2400, 1800, 1200, 630, 10, 10, fit="crop")
    assert (corner["x"], corner["y"]) == (0, 0) and corner["focus_after"] == {"x": 10, "y": 10}
    with pytest.raises(ValueError, match="does not fit"):
        plan_crop(2400, 1800, 1080, 1920, 1200, 900, fit="crop")


def test_cover_scales_down_to_cover_then_crops_around_focus():
    plan = plan_crop(3000, 2400, 1080, 1920, 2100, 560)
    assert plan["scaled_height"] == 1920 and plan["scaled_width"] == 2400
    assert plan["y"] == 0 and plan["upscaled"] is False
    _assert_plan(plan, 3000, 2400, 1080, 1920, 2100, 560)
    same = plan_crop(1200, 630, 1200, 630, 5, 5)
    assert (same["scale"], same["x"], same["y"]) == (1.0, 0, 0)


def test_cover_refuses_upscaling_unless_allowed():
    with pytest.raises(ValueError, match="allow_upscale"):
        plan_crop(800, 600, 1200, 630, 400, 300)
    plan = plan_crop(800, 600, 1200, 630, 400, 300, allow_upscale=True)
    assert plan["upscaled"] is True and plan["scaled_width"] == 1200
    _assert_plan(plan, 800, 600, 1200, 630, 400, 300)


def test_focus_outside_source_and_bad_fit_are_refused():
    with pytest.raises(ValueError, match="outside"):
        plan_crop(100, 100, 50, 50, 100, 10)
    with pytest.raises(ValueError, match="fit must be"):
        plan_crop(100, 100, 50, 50, 10, 10, fit="stretch")


def test_focus_always_stays_in_frame_for_random_cases():
    rng = random.Random(9)
    for _ in range(4000):
        src_w, src_h = rng.randint(1, 5000), rng.randint(1, 5000)
        out_w, out_h = rng.randint(1, 3000), rng.randint(1, 3000)
        fx, fy = rng.randrange(src_w), rng.randrange(src_h)
        fit = rng.choice(["cover", "crop"])
        try:
            plan = plan_crop(src_w, src_h, out_w, out_h, fx, fy, fit=fit, allow_upscale=True)
        except ValueError as exc:
            assert fit == "crop" and (out_w > src_w or out_h > src_h), exc
            continue
        _assert_plan(plan, src_w, src_h, out_w, out_h, fx, fy)
        if fit == "cover":
            # The binding axis matches the profile exactly; the other axis is at least as large.
            assert plan["scaled_width"] == out_w or plan["scaled_height"] == out_h


def test_validate_runs_before_gimp():
    base = {"input_path": "a.png", "output_dir": "out"}
    assert recipes.resolve_params("social_crop", base)["profiles"] == ["open_graph"]
    for extra, match in [
        ({"image_id": 3}, "exactly one"),
        ({"input_path": ""}, "exactly one"),
        ({"profiles": ["tiktok"]}, "unknown social profile"),
        ({"fit": "stretch"}, "fit"),
        ({"format": "gif"}, "format"),
        ({"focus": {"x": 1.5, "y": 2}}, "focus"),
        ({"focus": {"x": 1}}, "focus"),
    ]:
        with pytest.raises(ValueError, match=match):
            recipes.resolve_params("social_crop", {**base, **extra})
    assert recipes.resolve_params("social_crop", {"image_id": 4, "output_dir": "out", "profiles": ["all"]})["image_id"] == 4


def test_atlas_validate_needs_exactly_one_input():
    with pytest.raises(ValueError, match="exactly one"):
        recipes.resolve_params("sprite_atlas_pack", {"output_path": "out.png"})
    with pytest.raises(ValueError, match="exactly one"):
        recipes.resolve_params("sprite_atlas_pack", {"input_paths": ["a.png"], "input_layer_ids": [3], "output_path": "out.png"})
    with pytest.raises(ValueError, match="power_of_two"):
        recipes.resolve_params("sprite_atlas_pack", {"input_paths": ["a.png"], "output_path": "o.png", "power_of_two": True, "max_width": 1000})


@pytest.mark.parametrize("seed", range(6))
def test_atlas_packer_random_mixed_sizes(seed):
    rng = random.Random(seed)
    pack = recipes.get_recipe("sprite_atlas_pack").pack_rects
    padding = rng.choice([0, 1, 2, 3, 8])
    sizes = [(rng.randint(1, 120), rng.randint(1, 120)) for _ in range(rng.randint(1, 60))]
    positions, width, height = pack(sizes, 512, padding)
    rects = [(x, y, w, h) for (x, y), (w, h) in zip(positions, sizes, strict=True)]
    assert width <= 512
    for i, (x, y, w, h) in enumerate(rects):
        assert x >= padding and y >= padding and x + w + padding <= width and y + h + padding <= height
        for x2, y2, w2, h2 in rects[i + 1:]:
            assert x + w + padding <= x2 or x2 + w2 + padding <= x or y + h + padding <= y2 or y2 + h2 + padding <= y
    assert sum(w * h for w, h in sizes) <= width * height
