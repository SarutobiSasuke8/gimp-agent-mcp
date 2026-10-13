import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


class FakeImage:
    def __init__(self, image_id, *, selected=(), dirty=False, selection=(False, 0, 0, 0, 0)):
        self.image_id = image_id
        self.selected = selected
        self.dirty = dirty
        self.selection = selection

    def get_id(self):
        return self.image_id

    def is_valid(self):
        return True

    def get_name(self):
        return f"Image {self.image_id}"

    def get_width(self):
        return 100

    def get_height(self):
        return 80

    def get_base_type(self):
        return SimpleNamespace(value_nick="rgb")

    def get_precision(self):
        return SimpleNamespace(value_nick="u8-non-linear")

    def get_file(self):
        return None

    def is_dirty(self):
        return self.dirty

    def get_layers(self):
        return []

    def get_selected_layers(self):
        return [SimpleNamespace(get_id=lambda layer_id=layer_id: layer_id) for layer_id in self.selected]


def _load_bridge(monkeypatch, user_context):
    repo_root = Path(__file__).resolve().parents[1]
    bridge_path = repo_root / "src" / "gimp_agent_mcp" / "plugin" / "gimp-agent-bridge.py"
    gimp = SimpleNamespace(
        Image=FakeImage,
        Item=type("FakeItem", (), {}),
        Selection=SimpleNamespace(bounds=lambda image: image.selection),
        get_user_context=lambda: user_context,
        main=lambda *_args: None,
        PlugIn=type("FakePlugIn", (), {"__gtype__": object()}),
    )
    repository = types.ModuleType("gi.repository")
    repository.Gimp = gimp
    repository.Gegl = SimpleNamespace()
    repository.Gio = SimpleNamespace()
    repository.GLib = SimpleNamespace()
    repository.GObject = SimpleNamespace()
    gi = types.ModuleType("gi")
    gi.require_version = lambda *_args: None
    gi.repository = repository
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)

    spec = importlib.util.spec_from_file_location("gimp_agent_bridge_test", bridge_path)
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)
    return bridge


def test_active_context_with_no_open_images(monkeypatch):
    bridge = _load_bridge(monkeypatch, None)

    assert bridge._active_image_context([]) == {
        "active_image_id": None,
        "active_layer_ids": [],
        "selection": None,
        "active_image_dirty": None,
    }


@pytest.mark.parametrize(
    ("images", "active", "expected"),
    [
        (
            [FakeImage(4, selected=[9], selection=(False, 0, 0, 0, 0))],
            4,
            {
                "active_image_id": 4,
                "active_layer_ids": [9],
                "selection": {"non_empty": False, "x1": 0, "y1": 0, "x2": 0, "y2": 0},
                "active_image_dirty": False,
            },
        ),
        (
            [FakeImage(2), FakeImage(7, selected=[18, 19], dirty=True, selection=(True, 10, 20, 50, 60))],
            7,
            {
                "active_image_id": 7,
                "active_layer_ids": [18, 19],
                "selection": {"non_empty": True, "x1": 10, "y1": 20, "x2": 50, "y2": 60},
                "active_image_dirty": True,
            },
        ),
    ],
)
def test_active_context_uses_mocked_user_display_not_image_order(monkeypatch, images, active, expected):
    display = SimpleNamespace(is_valid=lambda: True)
    user_context = SimpleNamespace(get_display=lambda: display, get_image=lambda: next(i for i in images if i.get_id() == active))
    bridge = _load_bridge(monkeypatch, user_context)

    assert bridge._active_image_context(images) == expected
