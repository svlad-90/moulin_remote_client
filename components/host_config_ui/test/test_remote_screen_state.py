from __future__ import annotations

import unittest
from typing import Any

from components.host_config_ui.api import remote_screen_state


class FakePort:
    def __init__(self) -> None:
        self.status = ""
        self.cursor_states: list[bool] = []
        self.queued_text = ""

    def read_queued_text(self, _first_char: int) -> str:
        return self.queued_text

    def set_cursor(self, value: bool) -> None:
        self.cursor_states.append(value)


def config() -> dict[str, Any]:
    return {
        "active_remote": "build-b",
        "remotes": [{"name": "build-a"}, {"name": "build-b"}],
    }


class RemoteScreenStateControllerTests(unittest.TestCase):
    def test_sync_selection_initializes_from_active_remote(self) -> None:
        controller = remote_screen_state.RemoteScreenStateController(config())

        controller.sync_selection(controller.remotes(), [("Name", "name")])

        self.assertEqual(controller.state.remote_index, 1)
        self.assertEqual(controller.state.field_index, 0)
        self.assertEqual(controller.state.focus, "remotes")

    def test_navigation_action_moves_focus_and_indexes(self) -> None:
        controller = remote_screen_state.RemoteScreenStateController(config())
        port = FakePort()

        controller.apply_navigation_action(port, {"action": "focus-fields"}, field_count=2, remote_count=2)
        controller.apply_navigation_action(port, {"action": "move-field", "delta": 1}, field_count=2, remote_count=2)
        controller.apply_navigation_action(port, {"action": "move-list", "delta": 1}, field_count=2, remote_count=2)

        self.assertEqual(controller.state.focus, "fields")
        self.assertEqual(controller.state.field_index, 1)
        self.assertEqual(controller.state.remote_index, 1)

    def test_inline_edit_updates_value_then_saves_through_callback(self) -> None:
        controller = remote_screen_state.RemoteScreenStateController(config())
        port = FakePort()
        remote = {"name": "build-a", "label": "Build A"}
        calls: list[tuple[str, str]] = []
        controller.begin_inline_edit("label", "Build A")
        port.queued_text = "X"

        controller.handle_inline_edit_key(
            port,
            ord("X"),
            remote,
            lambda _port, target, key, value: calls.append((key, value)),
        )
        controller.handle_inline_edit_key(
            port,
            10,
            remote,
            lambda _port, target, key, value: calls.append((key, value)),
        )

        self.assertEqual(calls, [("label", "Build AX")])
        self.assertEqual(controller.state.editing_key, "")
        self.assertEqual(port.cursor_states, [False])

    def test_add_and_delete_state_update_focus_and_index(self) -> None:
        cfg = config()
        controller = remote_screen_state.RemoteScreenStateController(cfg)
        cfg["remotes"].append({"name": "build-c"})

        controller.apply_add_state()
        self.assertEqual(controller.state.remote_index, 2)
        self.assertEqual(controller.state.focus, "fields")

        cfg["remotes"].pop()
        controller.apply_delete_state()
        self.assertEqual(controller.state.remote_index, 1)
        self.assertEqual(controller.state.focus, "remotes")


if __name__ == "__main__":
    unittest.main()
