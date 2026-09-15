from __future__ import annotations

import curses
import unittest
from typing import Any
from unittest.mock import patch

from components.host_config_ui.api import remote_screen


class FakeScreen:
    def __init__(self, keys: list[int], *, height: int = 30, width: int = 120) -> None:
        self.keys = keys
        self.height = height
        self.width = width
        self.timeouts: list[int] = []
        self.clear_count = 0
        self.erase_count = 0
        self.refresh_count = 0

    def timeout(self, value: int) -> None:
        self.timeouts.append(value)

    def clear(self) -> None:
        self.clear_count += 1

    def erase(self) -> None:
        self.erase_count += 1

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def refresh(self) -> None:
        self.refresh_count += 1

    def move(self, _row: int, _col: int) -> None:
        return None


class FakeRemoteConfigPort:
    def __init__(self, keys: list[int], prompts: list[str] | None = None) -> None:
        self.screen = FakeScreen(keys)
        self.status = ""
        self.connection_state = "disconnected"
        self.prompts = list(prompts or [])
        self.rows: list[tuple[int, int, str, int | None]] = []
        self.boxes: list[tuple[int, int, int, int, str]] = []
        self.cursor_states: list[bool] = []
        self.add_calls = 0
        self.set_active_calls: list[str] = []
        self.delete_calls: list[str] = []
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

    def draw_wrapped(self, row: int, _col: int, _width: int, text: str, _attr: int = 0, *, max_lines: int = 3) -> int:
        return row + min(max(1, len(text) // 80 + 1), max_lines)

    def prompt(self, _label: str, current: str = "") -> str:
        if not self.prompts:
            return current
        return self.prompts.pop(0)

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

    def add_empty_remote(self) -> None:
        self.add_calls += 1

    def delete_remote(self, remote: dict[str, Any]) -> None:
        self.delete_calls.append(str(remote.get("name", "")))

    def set_active_remote(self, remote: dict[str, Any]) -> None:
        self.set_active_calls.append(str(remote.get("name", "")))

    def apply_remote_inline_value(self, remote: dict[str, Any], key: str, value: str) -> None:
        remote[key] = value
        self.updated_fields.append((str(remote.get("name", "")), key, value))

    def select_remote_moulin_manifest(self) -> None:
        return None

    def select_remote_dockerfile(self) -> None:
        return None


class FakeRemoteFileSelector:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def select_moulin_manifest(self, _port: Any) -> None:
        self.calls.append("manifest")

    def select_dockerfile(self, _port: Any) -> None:
        self.calls.append("dockerfile")


class FakeProfileActionController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def add_remote(self, port: Any) -> None:
        self.calls.append(("add", ""))
        port.status = "added by controller"

    def delete_remote(self, port: Any, remote: dict[str, Any]) -> None:
        self.calls.append(("delete", str(remote.get("name", ""))))
        port.status = "deleted by controller"

    def set_active_remote(self, port: Any, remote: dict[str, Any]) -> None:
        self.calls.append(("set-active", str(remote.get("name", ""))))
        port.status = "active by controller"


class FakeFieldActionController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.project_dir_calls: list[str] = []
        self.edit_value_calls: list[tuple[str, str, str]] = []

    def apply_remote_inline_value(self, _port: Any, remote: dict[str, Any], key: str, value: str) -> None:
        self.calls.append((str(remote.get("name", "")), key, value))
        remote[key] = value

    def edit_remote_projects_dir(self, _port: Any, remote: dict[str, Any], *, browse_project_directory: Any) -> None:
        self.project_dir_calls.append(str(remote.get("name", "")))
        selected = browse_project_directory(str(remote.get("projects_dir", "")))
        if selected:
            remote["projects_dir"] = selected

    def edit_remote_value(self, _port: Any, remote: dict[str, Any], key: str, label: str) -> None:
        self.edit_value_calls.append((str(remote.get("name", "")), key, label))


def config_with_remotes() -> dict[str, Any]:
    return {
        "remotes": [
            {"name": "build-a", "label": "Build A", "user": "user", "host": "10.0.0.1", "projects_dir": "/mnt/a"},
            {"name": "build-b", "label": "Build B", "user": "user", "host": "10.0.0.2", "projects_dir": "/mnt/b"},
        ],
        "active_remote": "build-a",
    }


class RemoteConfigurationScreenControllerTests(unittest.TestCase):
    def test_run_remote_configurations_screen_quit_saves_config(self) -> None:
        port = FakeRemoteConfigPort([ord("q")])
        saved: list[dict[str, Any]] = []

        remote_screen.run_remote_configurations_screen(
            port,
            config_with_remotes(),
            save_config=saved.append,
        )

        self.assertEqual(len(saved), 1)
        self.assertEqual(port.screen.timeouts[-1], 250)

    def test_run_remote_configurations_screen_add_action_uses_port(self) -> None:
        port = FakeRemoteConfigPort([ord("a"), ord("q")])

        remote_screen.run_remote_configurations_screen(
            port,
            config_with_remotes(),
            save_config=lambda _config: None,
        )

        self.assertEqual(port.add_calls, 1)

    def test_run_remote_configurations_screen_set_active_uses_selected_remote(self) -> None:
        port = FakeRemoteConfigPort([ord("j"), ord("s"), ord("q")])

        remote_screen.run_remote_configurations_screen(
            port,
            config_with_remotes(),
            save_config=lambda _config: None,
        )

        self.assertEqual(port.set_active_calls, ["build-b"])

    def test_run_remote_configurations_screen_uses_profile_action_controller_for_add(self) -> None:
        port = FakeRemoteConfigPort([ord("a"), ord("q")])
        controller = FakeProfileActionController()

        remote_screen.run_remote_configurations_screen(
            port,
            config_with_remotes(),
            save_config=lambda _config: None,
            profile_action_controller=controller,
        )

        self.assertEqual(controller.calls, [("add", "")])
        self.assertEqual(port.add_calls, 0)

    def test_run_remote_configurations_screen_uses_profile_action_controller_for_selected_remote(self) -> None:
        port = FakeRemoteConfigPort([ord("j"), ord("s"), ord("d"), ord("q")])
        controller = FakeProfileActionController()

        remote_screen.run_remote_configurations_screen(
            port,
            config_with_remotes(),
            save_config=lambda _config: None,
            profile_action_controller=controller,
        )

        self.assertEqual(controller.calls, [("set-active", "build-b"), ("delete", "build-b")])
        self.assertEqual(port.set_active_calls, [])
        self.assertEqual(port.delete_calls, [])

    def test_run_remote_configurations_screen_uses_field_action_controller_for_inline_save(self) -> None:
        port = FakeRemoteConfigPort([ord("l"), ord("j"), 10, ord("X"), 10, ord("q")])
        controller = FakeFieldActionController()
        config = config_with_remotes()

        remote_screen.run_remote_configurations_screen(
            port,
            config,
            save_config=lambda _config: None,
            field_action_controller=controller,
        )

        self.assertEqual(controller.calls, [("build-a", "label", "Build AX")])
        self.assertEqual(config["remotes"][0]["label"], "Build AX")

    def test_run_remote_configurations_screen_uses_remote_file_selection_service(self) -> None:
        port = FakeRemoteConfigPort([curses.KEY_RIGHT, 10, ord("q")])
        port.connection_state = "connected"
        selector = FakeRemoteFileSelector()

        with patch(
            "components.host_config_ui.src.remote_screen.config_field_api.remote_fields",
            return_value=[("Moulin manifest", "moulin_manifest")],
        ):
            remote_screen.run_remote_configurations_screen(
                port,
                config_with_remotes(),
                save_config=lambda _config: None,
                remote_file_selection_controller=selector,
            )

        self.assertEqual(selector.calls, ["manifest"])

    def test_run_edit_remote_screen_uses_profile_action_controller_for_set_active(self) -> None:
        port = FakeRemoteConfigPort([ord("s"), ord("q")])
        profile_actions = FakeProfileActionController()
        field_actions = FakeFieldActionController()
        saved: list[dict[str, Any]] = []
        config = config_with_remotes()

        remote_screen.run_edit_remote_screen(
            port,
            config,
            config["remotes"][0],
            save_config=saved.append,
            profile_action_controller=profile_actions,
            field_action_controller=field_actions,
            browse_project_directory=lambda _start: None,
        )

        self.assertEqual(profile_actions.calls, [("set-active", "build-a")])
        self.assertEqual(len(saved), 1)

    def test_run_edit_remote_screen_uses_field_action_controller_for_projects_dir(self) -> None:
        port = FakeRemoteConfigPort([ord("b"), ord("q")])
        profile_actions = FakeProfileActionController()
        field_actions = FakeFieldActionController()
        config = config_with_remotes()

        remote_screen.run_edit_remote_screen(
            port,
            config,
            config["remotes"][0],
            save_config=lambda _config: None,
            profile_action_controller=profile_actions,
            field_action_controller=field_actions,
            browse_project_directory=lambda _start: "/mnt/new",
        )

        self.assertEqual(field_actions.project_dir_calls, ["build-a"])
        self.assertEqual(config["remotes"][0]["projects_dir"], "/mnt/new")

    def test_run_edit_remote_screen_uses_field_action_controller_for_scalar_edit(self) -> None:
        port = FakeRemoteConfigPort([10, ord("q")])
        profile_actions = FakeProfileActionController()
        field_actions = FakeFieldActionController()
        config = config_with_remotes()

        remote_screen.run_edit_remote_screen(
            port,
            config,
            config["remotes"][0],
            save_config=lambda _config: None,
            profile_action_controller=profile_actions,
            field_action_controller=field_actions,
            browse_project_directory=lambda _start: None,
        )

        self.assertEqual(field_actions.edit_value_calls, [("build-a", "name", "Profile name")])

    def test_run_add_remote_screen_creates_profile_and_resets_state(self) -> None:
        keys = [10, ord("j"), ord("j"), 10, ord("j"), 10, ord("j"), 10]
        port = FakeRemoteConfigPort(keys, prompts=["new-build", "new-user", "10.0.0.3"])
        saved: list[dict[str, Any]] = []
        reset_calls: list[bool] = []
        config = config_with_remotes()

        remote_screen.run_add_remote_screen(
            port,
            config,
            save_config=saved.append,
            reset_preflight=lambda: reset_calls.append(True),
        )

        self.assertEqual(config["active_remote"], "new-build")
        self.assertEqual(config["remotes"][-1]["label"], "new-build")
        self.assertEqual(config["remotes"][-1]["user"], "new-user")
        self.assertEqual(config["remotes"][-1]["host"], "10.0.0.3")
        self.assertEqual(port.connection_state, "disconnected")
        self.assertEqual(reset_calls, [True])
        self.assertEqual(len(saved), 1)
        self.assertEqual(port.status, "Remote profile added: new-build")


if __name__ == "__main__":
    unittest.main()
