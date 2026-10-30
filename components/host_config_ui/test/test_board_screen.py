from __future__ import annotations

import curses
import unittest
from typing import Any

from components.host_config.api import fields
from components.host_config_ui.api import board_screen
from components.host_config_ui.src import board_screen as board_screen_src
from components.ui.api import input as ui_input_api


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

    def draw_wrapped(self, row: int, col: int, _width: int, text: str, *, max_lines: int) -> int:
        self.rows.append((row, col, text, None))
        return min(max_lines, 1)

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

    def add_board(self, port: Any, host: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("add-board", str(host.get("name", ""))))
        board = {"name": "new-board", "label": "new-board", "type": "", "commands": {}}
        host.setdefault("boards", []).append(board)
        return board

    def delete_board_host(self, port: Any, host: dict[str, Any]) -> None:
        self.calls.append(("delete", str(host.get("name", ""))))
        port.status = "deleted by controller"

    def delete_board(self, port: Any, host: dict[str, Any], board: dict[str, Any]) -> bool:
        self.calls.append(("delete-board", str(board.get("name", ""))))
        host["boards"] = [item for item in host.get("boards", []) if item is not board]
        return True

    def set_active_board_host(self, port: Any, host: dict[str, Any]) -> None:
        self.calls.append(("set-active", str(host.get("name", ""))))
        port.status = "active by controller"

    def set_active_board(self, port: Any, board: dict[str, Any]) -> None:
        self.calls.append(("set-active-board", str(board.get("name", ""))))

    def confirm_action(self, _title: str, _message: str) -> bool:
        return True


class FakeFieldActionController:
    def __init__(self) -> None:
        self.inline_calls: list[tuple[str, str, str]] = []
        self.toggle_calls: list[str] = []

    def apply_board_host_inline_value(self, _port: Any, host: dict[str, Any], key: str, value: str) -> None:
        self.inline_calls.append((str(host.get("name", "")), key, value))
        host[key] = value

    def toggle_board_host_direct_copy(self, _port: Any, host: dict[str, Any]) -> None:
        self.toggle_calls.append(str(host.get("name", "")))

    def apply_board_inline_value(self, _port: Any, board: dict[str, Any], key: str, value: str) -> None:
        self.inline_calls.append((str(board.get("name", "")), key, value))
        if key.startswith("command_"):
            command_id = key.removeprefix("command_")
            commands = board.setdefault("commands", {})
            if value:
                commands[command_id] = value
            else:
                commands.pop(command_id, None)
            return
        board[key] = value


class FakeBoardTypeService:
    def __init__(self, options: list[dict[str, str]]) -> None:
        self.options = options

    def available_board_type_options(self) -> list[dict[str, str]]:
        return self.options


def config_with_board_hosts() -> dict[str, Any]:
    return {
        "board_hosts": [
            {
                "name": "host-a", "label": "Host A", "user": "user", "host": "10.0.0.1", "direct_copy": "no",
                "boards": [{"name": "board-a", "label": "Board A", "type": "gen5_x5h", "commands": {}}],
            },
            {
                "name": "host-b", "label": "Host B", "user": "user", "host": "10.0.0.2", "direct_copy": "yes",
                "boards": [{"name": "board-b", "label": "Board B", "type": "gen5_x5h", "commands": {}}],
            },
        ],
        "active_board_host": "host-a",
        "active_board": "board-a",
    }


class BoardHostConfigurationScreenControllerTests(unittest.TestCase):
    def test_run_board_host_configurations_screen_quit_restores_timeout(self) -> None:
        port = FakeBoardConfigPort([ord("q")])

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
        )

        self.assertEqual(port.screen.timeouts[-1], 250)

    def test_run_board_host_configurations_screen_add_action_uses_controller(self) -> None:
        port = FakeBoardConfigPort([ord("a"), ord("q")])
        controller = FakeProfileActionController()

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
            profile_action_controller=controller,
        )

        self.assertEqual(controller.calls, [("add", "")])
        self.assertEqual(port.add_calls, 0)

    def test_run_board_host_configurations_screen_set_active_uses_selected_host(self) -> None:
        port = FakeBoardConfigPort([ord("j"), ord("l"), ord("s"), ord("q")])
        config = config_with_board_hosts()
        controller = FakeProfileActionController()

        board_screen.run_board_host_configurations_screen(
            port,
            config,
            profile_action_controller=controller,
        )

        self.assertEqual(controller.calls, [("set-active-board", "board-b")])

    def test_run_board_host_configurations_screen_uses_profile_action_controller_for_add(self) -> None:
        port = FakeBoardConfigPort([ord("a"), ord("q")])
        controller = FakeProfileActionController()

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
            profile_action_controller=controller,
        )

        self.assertEqual(controller.calls, [("add", "")])
        self.assertEqual(port.add_calls, 0)

    def test_run_board_host_configurations_screen_uses_profile_action_controller_for_selected_host(self) -> None:
        port = FakeBoardConfigPort([ord("j"), ord("d"), ord("q")])
        controller = FakeProfileActionController()

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
            profile_action_controller=controller,
        )

        self.assertEqual(controller.calls, [("delete", "host-b")])
        self.assertEqual(port.set_active_calls, [])
        self.assertEqual(port.delete_calls, [])

    def test_run_board_host_configurations_screen_uses_field_action_controller_for_inline_save(self) -> None:
        port = FakeBoardConfigPort([ord("e"), ord("j"), 10, ord("X"), 10, ord("q")])
        controller = FakeFieldActionController()
        config = config_with_board_hosts()

        board_screen.run_board_host_configurations_screen(
            port,
            config,
            field_action_controller=controller,
        )

        self.assertEqual(controller.inline_calls, [("host-a", "label", "Host AX")])
        self.assertEqual(config["board_hosts"][0]["label"], "Host AX")

    def test_russian_physical_key_opens_host_fields(self) -> None:
        port = FakeBoardConfigPort([ui_input_api.encode_text_key("у"), ord("q")])

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
            field_action_controller=FakeFieldActionController(),
        )

        self.assertTrue(any(row[2].strip() == "HOST PROFILE" for row in port.rows))

    def test_run_board_host_configurations_screen_selects_board_type_from_registry(self) -> None:
        port = FakeBoardConfigPort([ord("l"), 10, ord("j"), ord("j"), 10, 10, ord("q")])
        controller = FakeFieldActionController()
        config = config_with_board_hosts()
        config["board_hosts"][0]["boards"][0]["type"] = "unknown"

        board_screen.run_board_host_configurations_screen(
            port,
            config,
            field_action_controller=controller,
        )

        self.assertEqual(config["board_hosts"][0]["boards"][0]["type"], "gen5_x5h")

    def test_run_board_host_configurations_screen_uses_field_action_controller_for_board_type(self) -> None:
        port = FakeBoardConfigPort([ord("l"), 10, ord("j"), ord("j"), 10, 10, ord("q")])
        controller = FakeFieldActionController()
        config = config_with_board_hosts()
        config["board_hosts"][0]["boards"][0]["type"] = "unknown"

        board_screen.run_board_host_configurations_screen(
            port,
            config,
            field_action_controller=controller,
        )

        self.assertEqual(config["board_hosts"][0]["boards"][0]["type"], "gen5_x5h")
        self.assertEqual(controller.inline_calls, [("board-a", "type", "gen5_x5h")])
        self.assertEqual(port.updated_fields, [])

    def test_select_board_type_uses_list_navigation(self) -> None:
        port = FakeBoardConfigPort([ord("j"), 10])
        service = FakeBoardTypeService([
            {"type": "gen5_x5h", "label": "GEN5 X5H", "description": "Default board"},
            {"type": "other_board", "label": "Other Board", "description": "Other workflow"},
        ])

        result = board_screen_src.select_board_type(port, service, "gen5_x5h")  # type: ignore[arg-type]

        self.assertEqual(result, "other_board")
        self.assertEqual(port.status, "Board type: other_board")
        self.assertTrue(any("other_board" in row[2] for row in port.rows))

    def test_select_board_type_can_cancel(self) -> None:
        port = FakeBoardConfigPort([27])
        service = FakeBoardTypeService([
            {"type": "gen5_x5h", "label": "GEN5 X5H", "description": "Default board"},
        ])

        result = board_screen_src.select_board_type(port, service, "gen5_x5h")  # type: ignore[arg-type]

        self.assertIsNone(result)
        self.assertEqual(port.status, "Board type selection cancelled")

    def test_run_board_host_configurations_screen_toggles_direct_copy(self) -> None:
        port = FakeBoardConfigPort([ord("e"), *[ord("j")] * 5, 10, ord("q")])
        controller = FakeFieldActionController()

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
            field_action_controller=controller,
        )

        self.assertEqual(port.toggle_calls, [])
        self.assertEqual(controller.toggle_calls, ["host-a"])

    def test_run_board_host_configurations_screen_uses_field_action_controller_for_direct_copy(self) -> None:
        port = FakeBoardConfigPort([ord("e"), *[ord("j")] * 5, 10, ord("q")])
        controller = FakeFieldActionController()

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
            field_action_controller=controller,
        )

        self.assertEqual(controller.toggle_calls, ["host-a"])
        self.assertEqual(port.toggle_calls, [])

    def test_enter_drills_from_host_to_board_fields(self) -> None:
        port = FakeBoardConfigPort([10, 10, ord("q")])

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
        )

        self.assertTrue(any(row[2].strip() == "BOARD PROFILE" for row in port.rows))

    def test_escape_returns_one_navigation_level_at_a_time(self) -> None:
        port = FakeBoardConfigPort([10, 10, 27, 27, 27])

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
        )

        self.assertGreaterEqual(port.screen.refresh_count, 5)

    def test_board_commands_row_opens_and_returns_from_submenu(self) -> None:
        port = FakeBoardConfigPort([10, 10, *[ord("j")] * 9, 10, 27, ord("q")])

        board_screen.run_board_host_configurations_screen(
            port,
            config_with_board_hosts(),
            field_action_controller=FakeFieldActionController(),
        )

        self.assertTrue(any(box[4] == "Command overrides" for box in port.boxes))

    def test_board_commands_open_in_submenu_and_save_override(self) -> None:
        port = FakeBoardConfigPort([10, curses.KEY_F2, 27])
        port.screen.width = 70
        controller = FakeFieldActionController()
        board = config_with_board_hosts()["board_hosts"][0]["boards"][0]
        command = "labgrid-client -c /a/very/long/profile/path/ironhide-1.yaml -p ironhide-1 power off"
        board["commands"]["power_off"] = command

        board_screen_src.run_board_commands_screen(
            port,
            board,
            board_field_service=fields.board_host_field_service(),
            field_action_controller=controller,
        )

        self.assertEqual(
            controller.inline_calls,
            [("board-a", "command_power_off", command)],
        )
        self.assertTrue(any("..." in row[2] and "Power off" in row[2] for row in port.rows))
        self.assertTrue(any(row[2].strip() == "Edit board command" for row in port.rows))
        self.assertTrue(any("Effective command:" in row[2] for row in port.rows))

    def test_multiline_command_editor_wraps_text_and_supports_newlines(self) -> None:
        rows = board_screen_src._command_editor_rows("abcdef\ngh", 3)

        self.assertEqual(
            rows,
            [("abc", 0, 3), ("def", 3, 6), ("", 6, 6), ("gh", 7, 9)],
        )
        self.assertEqual(board_screen_src._command_editor_cursor(rows, 7), (3, 0))
        self.assertEqual(board_screen_src._move_command_editor_cursor(rows, 3, 1, -1), 6)


if __name__ == "__main__":
    unittest.main()
