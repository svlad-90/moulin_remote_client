from __future__ import annotations

import unittest

from components.host_config_ui.api import board_screen_state


class FakePort:
    def __init__(self) -> None:
        self.status = ""
        self.cursor_states: list[bool] = []
        self.queued_text = ""

    def read_queued_text(self, _first_char: int) -> str:
        return self.queued_text

    def set_cursor(self, value: bool) -> None:
        self.cursor_states.append(value)


def config() -> dict[str, object]:
    return {
        "active_board_host": "board-b",
        "board_hosts": [{"name": "board-a"}, {"name": "board-b"}],
    }


class BoardScreenStateControllerTests(unittest.TestCase):
    def test_sync_selection_initializes_from_active_board_host(self) -> None:
        controller = board_screen_state.BoardScreenStateController(config())

        controller.sync_selection(controller.hosts(), [("Name", "name")])

        self.assertEqual(controller.state.host_index, 1)
        self.assertEqual(controller.state.field_index, 0)
        self.assertEqual(controller.state.focus, "hosts")

    def test_navigation_action_moves_focus_and_indexes(self) -> None:
        controller = board_screen_state.BoardScreenStateController(config())
        port = FakePort()

        controller.apply_navigation_action(port, {"action": "focus-fields"}, field_count=2, host_count=2)
        controller.apply_navigation_action(port, {"action": "move-field", "delta": 1}, field_count=2, host_count=2)
        controller.apply_navigation_action(port, {"action": "move-list", "delta": 1}, field_count=2, host_count=2)

        self.assertEqual(controller.state.focus, "fields")
        self.assertEqual(controller.state.field_index, 1)
        self.assertEqual(controller.state.host_index, 1)

    def test_inline_edit_updates_value_then_saves_through_callback(self) -> None:
        controller = board_screen_state.BoardScreenStateController(config())
        port = FakePort()
        host = {"name": "board-a", "label": "Board A"}
        calls: list[tuple[str, str]] = []
        controller.begin_inline_edit("label", "Board A")
        port.queued_text = "X"

        controller.handle_inline_edit_key(
            port,
            ord("X"),
            host,
            lambda _port, target, key, value: calls.append((key, value)),
        )
        controller.handle_inline_edit_key(
            port,
            10,
            host,
            lambda _port, target, key, value: calls.append((key, value)),
        )

        self.assertEqual(calls, [("label", "Board AX")])
        self.assertEqual(controller.state.editing_key, "")
        self.assertEqual(port.cursor_states, [False])

    def test_add_and_delete_state_update_focus_and_index(self) -> None:
        cfg = config()
        controller = board_screen_state.BoardScreenStateController(cfg)
        cfg["board_hosts"].append({"name": "board-c"})  # type: ignore[index, union-attr]

        controller.apply_add_state()
        self.assertEqual(controller.state.host_index, 2)
        self.assertEqual(controller.state.focus, "fields")

        cfg["board_hosts"].pop()  # type: ignore[index, union-attr]
        controller.apply_delete_state()
        self.assertEqual(controller.state.host_index, 1)
        self.assertEqual(controller.state.focus, "hosts")


if __name__ == "__main__":
    unittest.main()
