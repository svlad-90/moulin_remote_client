from __future__ import annotations

import unittest
from typing import Any

from components.host_config_ui.api import board_screen


class FakeScreen:
    def __init__(self, keys: list[int], *, height: int = 30, width: int = 120) -> None:
        self.keys = keys
        self.height = height
        self.width = width
        self.timeouts: list[int] = []
        self.clear_count = 0
        self.refresh_count = 0

    def timeout(self, value: int) -> None:
        self.timeouts.append(value)

    def clear(self) -> None:
        self.clear_count += 1

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def refresh(self) -> None:
        self.refresh_count += 1

    def move(self, _row: int, _col: int) -> None:
        return None


class FakeBoardConfigPort:
    def __init__(self, keys: list[int]) -> None:
        self.screen = FakeScreen(keys)
        self.status = ""
        self.board_connection_state = "disconnected"
        self.rows: list[tuple[int, int, str, int | None]] = []
        self.boxes: list[tuple[int, int, int, int, str]] = []
        self.cursor_states: list[bool] = []
        self.add_calls = 0
        self.set_active_calls: list[str] = []
        self.delete_calls: list[str] = []
        self.toggle_calls: list[str] = []
        self.updated_fields: list[tuple[str, str, str]] = []

    def read_key(self) -> int:
        if not self.screen.keys:
            raise AssertionError("fake key queue is empty")
        return self.screen.keys.pop(0)

    def read_queued_text(self, _first_char: int) -> str:
        if 32 <= _first_char < 127:
            return chr(_first_char)
        return ""

    def add(self, row: int, col: int, text: str, attr: int | None = None) -> None:
        self.rows.append((row, col, text, attr))

    def draw_box(self, top: int, left: int, height: int, width: int, title: str) -> None:
        self.boxes.append((top, left, height, width, title))

    def set_cursor(self, value: bool) -> None:
        self.cursor_states.append(value)

    def selected_active_attr(self) -> int:
        return 1

    def selected_attr(self) -> int:
        return 2

    def active_row_attr(self) -> int:
        return 3

    def accent_attr(self) -> int:
        return 4

    def disabled_attr(self) -> int:
        return 5

    def warn_attr(self) -> int:
        return 6

    def editing_attr(self) -> int:
        return 7

    def selected_disabled_attr(self) -> int:
        return 8

    def add_empty_board_host(self) -> None:
        self.add_calls += 1

    def delete_board_host(self, host: dict[str, Any]) -> None:
        self.delete_calls.append(str(host.get("name", "")))

    def set_active_board_host(self, host: dict[str, Any]) -> None:
        self.set_active_calls.append(str(host.get("name", "")))

    def apply_board_host_inline_value(self, host: dict[str, Any], key: str, value: str) -> None:
        host[key] = value
        self.updated_fields.append((str(host.get("name", "")), key, value))

    def toggle_board_host_direct_copy(self, host: dict[str, Any]) -> None:
        self.toggle_calls.append(str(host.get("name", "")))


class FakeProfileActionController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def add_board_host(self, port: Any) -> None:
        self.calls.append(("add", ""))
        port.status = "added by controller"

    def delete_board_host(self, port: Any, host: dict[str, Any]) -> None:
        self.calls.append(("delete", str(host.get("name", ""))))
        port.status = "deleted by controller"

    def set_active_board_host(self, port: Any, host: dict[str, Any]) -> None:
        self.calls.append(("set-active", str(host.get("name", ""))))
        port.status = "active by controller"


class FakeFieldActionController:
    def __init__(self) -> None:
        self.inline_calls: list[tuple[str, str, str]] = []
        self.toggle_calls: list[str] = []

    def apply_board_host_inline_value(self, _port: Any, host: dict[str, Any], key: str, value: str) -> None:
        self.inline_calls.append((str(host.get("name", "")), key, value))
        host[key] = value

    def toggle_board_host_direct_copy(self, _port: Any, host: dict[str, Any]) -> None:
        self.toggle_calls.append(str(host.get("name", "")))


def config_with_board_hosts() -> dict[str, Any]:
    return {
        "board_hosts": [
            {"name": "board-a", "label": "Board A", "user": "user", "host": "10.0.0.1", "direct_copy": "no"},
            {"name": "board-b", "label": "Board B", "user": "user", "host": "10.0.0.2", "direct_copy": "yes"},
        ],
        "active_board_host": "board-a",
    }


class BoardHostConfigurationScreenControllerTests(unittest.TestCase):
    def test_run_board_host_configurations_screen_quit_saves_config(self) -> None:
        port = FakeBoardConfigPort([ord("q")])
        saved: list[dict[str, Any]] = []

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
            save_config=saved.append,
        )

        self.assertEqual(len(saved), 1)
        self.assertEqual(port.screen.timeouts[-1], 250)

    def test_run_board_host_configurations_screen_add_action_uses_port(self) -> None:
        port = FakeBoardConfigPort([ord("a"), ord("q")])

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
            save_config=lambda _config: None,
        )

        self.assertEqual(port.add_calls, 1)

    def test_run_board_host_configurations_screen_set_active_uses_selected_host(self) -> None:
        port = FakeBoardConfigPort([ord("j"), ord("s"), ord("q")])

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
            save_config=lambda _config: None,
        )

        self.assertEqual(port.set_active_calls, ["board-b"])

    def test_run_board_host_configurations_screen_uses_profile_action_controller_for_add(self) -> None:
        port = FakeBoardConfigPort([ord("a"), ord("q")])
        controller = FakeProfileActionController()

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
            save_config=lambda _config: None,
            profile_action_controller=controller,
        )

        self.assertEqual(controller.calls, [("add", "")])
        self.assertEqual(port.add_calls, 0)

    def test_run_board_host_configurations_screen_uses_profile_action_controller_for_selected_host(self) -> None:
        port = FakeBoardConfigPort([ord("j"), ord("s"), ord("d"), ord("q")])
        controller = FakeProfileActionController()

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
            save_config=lambda _config: None,
            profile_action_controller=controller,
        )

        self.assertEqual(controller.calls, [("set-active", "board-b"), ("delete", "board-b")])
        self.assertEqual(port.set_active_calls, [])
        self.assertEqual(port.delete_calls, [])

    def test_run_board_host_configurations_screen_uses_field_action_controller_for_inline_save(self) -> None:
        port = FakeBoardConfigPort([ord("l"), ord("j"), 10, ord("X"), 10, ord("q")])
        controller = FakeFieldActionController()
        config = config_with_board_hosts()

        board_screen.run_board_host_configurations_screen(
            port,
            config,
            save_config=lambda _config: None,
            field_action_controller=controller,
        )

        self.assertEqual(controller.inline_calls, [("board-a", "label", "Board AX")])
        self.assertEqual(config["board_hosts"][0]["label"], "Board AX")

    def test_run_board_host_configurations_screen_toggles_direct_copy(self) -> None:
        port = FakeBoardConfigPort([ord("l"), ord("j"), ord("j"), ord("j"), ord("j"), ord("j"), ord("j"), ord("j"), ord("j"), ord(" "), ord("q")])

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
            save_config=lambda _config: None,
        )

        self.assertEqual(port.toggle_calls, ["board-a"])

    def test_run_board_host_configurations_screen_uses_field_action_controller_for_direct_copy(self) -> None:
        port = FakeBoardConfigPort([ord("l"), ord("j"), ord("j"), ord("j"), ord("j"), ord("j"), ord("j"), ord("j"), ord("j"), ord(" "), ord("q")])
        controller = FakeFieldActionController()

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
            save_config=lambda _config: None,
            field_action_controller=controller,
        )

        self.assertEqual(controller.toggle_calls, ["board-a"])
        self.assertEqual(port.toggle_calls, [])


if __name__ == "__main__":
    unittest.main()
