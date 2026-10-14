"""Undo group bookkeeping runs without GIMP or gi."""

import pytest

from gimp_agent_mcp.plugin.agent_bridge_core import UndoGroupRegistry


class FakeImage:
    def __init__(self, image_id=7):
        self.image_id = image_id
        self.starts = 0
        self.ends = 0

    def get_id(self):
        return self.image_id

    def undo_is_enabled(self):
        return True

    def undo_group_start(self):
        self.starts += 1
        return True

    def undo_group_end(self):
        self.ends += 1
        return True


def test_held_group_suppresses_nested_per_operation_groups():
    groups, image = UndoGroupRegistry(), FakeImage()
    groups.start(image, "client-a", "agent: sticker pass")
    with pytest.raises(ValueError, match="already has an open"):
        groups.start(image, "client-a", "second group")
    groups.begin_op(image, "client-a")
    groups.begin_op(image, "client-a")
    groups.end_op(image)
    groups.end_op(image)
    assert image.starts == 1 and image.ends == 0
    assert groups.open_groups() == [{"image_id": 7, "name": "agent: sticker pass"}]
    groups.end(7, "client-a")
    assert image.ends == 1
    assert groups.open_groups() == []


def test_end_without_start_and_other_client_are_rejected():
    groups, image = UndoGroupRegistry(), FakeImage()
    with pytest.raises(ValueError, match="no open agent undo group"):
        groups.end(7, "client-a")
    groups.start(image, "client-a", "agent: pass")
    with pytest.raises(ValueError, match="only the client"):
        groups.end(7, "client-b")
    with pytest.raises(ValueError, match="another client"):
        groups.begin_op(image, "client-b")
    assert image.ends == 0


def test_disconnect_closes_only_the_departing_clients_groups():
    groups, first, second = UndoGroupRegistry(), FakeImage(7), FakeImage(8)
    groups.start(first, "client-a", "first")
    groups.start(second, "client-b", "second")
    assert groups.close_owner("client-a") == [7]
    assert first.ends == 1 and second.ends == 0
    assert groups.open_groups() == [{"image_id": 8, "name": "second"}]
    assert groups.close_owner("client-b") == [8]
    assert second.ends == 1
