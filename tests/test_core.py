import json

import pytest

from gimp_agent_mcp.plugin import agent_bridge_core as core


def test_encode_decode_roundtrip():
    payload = {"id": "1", "op": "ping", "params": {"x": 1, "text": "héllo"}}
    line = core.encode_message(payload)
    assert line.endswith(b"\n")
    assert b"\n" not in line[:-1]
    assert core.decode_message(line) == payload


def test_decode_rejects_non_object():
    with pytest.raises(ValueError):
        core.decode_message(b"[1,2,3]\n")
    with pytest.raises(ValueError):
        core.decode_message(b"\n")


@pytest.mark.parametrize(
    "value, expected",
    [
        ("white", (1.0, 1.0, 1.0, 1.0)),
        ("#000", (0.0, 0.0, 0.0, 1.0)),
        ("#ff8800", (1.0, 0x88 / 255, 0.0, 1.0)),
        ("#ff880080", (1.0, 0x88 / 255, 0.0, 0x80 / 255)),
        ("rgb(255, 0, 0)", (1.0, 0.0, 0.0, 1.0)),
        ("rgba(0, 0, 255, 0.5)", (0.0, 0.0, 1.0, 0.5)),
        ("rgb(1.0, 0.5, 0)", (1.0, 0.5, 0.0, 1.0)),
        ([255, 128, 0], (1.0, 128 / 255, 0.0, 1.0)),
        ([0.2, 0.4, 0.6, 0.8], (0.2, 0.4, 0.6, 0.8)),
        ({"r": 1, "g": 1, "b": 1, "a": 0.25}, (1.0, 1.0, 1.0, 0.25)),
        ("transparent", (0.0, 0.0, 0.0, 0.0)),
    ],
)
def test_parse_color(value, expected):
    got = core.parse_color(value)
    assert got == pytest.approx(expected)


def test_parse_color_rejects_garbage():
    with pytest.raises(ValueError):
        core.parse_color("not-a-colour")
    with pytest.raises(ValueError):
        core.parse_color([1, 2])
    with pytest.raises(ValueError):
        core.parse_color(42)


def test_srgb_transfer_roundtrip():
    for v in (0.0, 0.002, 0.05, 0.2, 0.5, 0.8, 1.0):
        assert core.srgb_to_linear(core.linear_to_srgb(v)) == pytest.approx(v, abs=1e-6)
    assert core.linear_to_srgb(0.2140) == pytest.approx(0.5, abs=0.002)
    assert core.srgb_to_linear(0.5) == pytest.approx(0.2140, abs=0.001)


def test_color_to_hex_drops_opaque_alpha():
    assert core.color_to_hex((1.0, 0.0, 0.0, 1.0)) == "#ff0000"
    assert core.color_to_hex((0.0, 0.0, 0.0, 0.5)) == "#00000080"


def test_key_matching_treats_dash_and_underscore_alike():
    names = ["new-width", "new-height", "run-mode"]
    assert core.match_key("new_width", names) == "new-width"
    assert core.match_key("RUN-MODE", names) == "run-mode"
    assert core.match_key("width", names) is None
    assert core.normalise_enum_nick("CLIP_TO_IMAGE") == "clip-to-image"


def test_bridge_file_roundtrip_and_token_reuse(tmp_path):
    path = str(tmp_path / "agent-bridge.json")
    assert core.read_bridge_file(path) is None
    token = core.load_or_create_token(path)
    assert len(token) >= 32
    data = core.write_bridge_file(path, port=9877, token=token, pid=123, gimp_version="3.2.4", mode="headless")
    assert data["token"] == token
    assert core.read_bridge_file(path)["port"] == 9877
    # A restart reuses the previous token so connected clients keep working.
    assert core.load_or_create_token(path) == token
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh)["mode"] == "headless"


def test_read_bridge_file_rejects_incomplete(tmp_path):
    path = tmp_path / "agent-bridge.json"
    path.write_text('{"port": 1}', encoding="utf-8")
    assert core.read_bridge_file(str(path)) is None


def test_truncate():
    assert core.truncate("abc", 10) == "abc"
    out = core.truncate("x" * 50, 10)
    assert out.startswith("x" * 10) and "truncated 40" in out
