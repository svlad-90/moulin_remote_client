from __future__ import annotations

import curses
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from components.config_workflow.api import workflow


class FakeScreen:
    def __init__(self) -> None:
        self.keys: list[int] = []
        self.timeout_value: int | None = None
        self.erased = False
        self.refreshed = False

    def timeout(self, value: int) -> None:
        self.timeout_value = value

    def erase(self) -> None:
        self.erased = True

    def refresh(self) -> None:
        self.refreshed = True

    def getmaxyx(self) -> tuple[int, int]:
        return (24, 100)


class FakePort:
    def __init__(self) -> None:
        self.connection_state = "disconnected"
        self.board_connection_state = "disconnected"
        self.status = ""
        self.screen = FakeScreen()
        self.rows: list[tuple[int, int, str, int]] = []
        self.prompt_values: dict[str, str] = {}
        self.prompt_cancelled = False

    def prompt(self, label: str, current: str = "") -> str:
        return self.prompt_values.get(label, current)

    def read_key(self) -> int:
        return self.screen.keys.pop(0)

    def add(self, row: int, col: int, text: str, attr: int = 0) -> None:
        self.rows.append((row, col, text, attr))

    def draw_box(self, row: int, col: int, height: int, width: int, title: str = "") -> None:
        self.rows.append((row, col, title, 0))

    def selected_attr(self) -> int:
        return 1

    def accent_attr(self) -> int:
        return 2

    def warn_attr(self) -> int:
        return 3


def make_controller(config: dict[str, Any] | None = None) -> workflow.ConfigWorkflowController:
    return workflow.config_workflow_controller(
        config or {},
        app_dir=Path("/app"),
        default_config_path=Path("/app/config.json"),
        default_build_targets="target-a",
        default_moulin_manifest="product.yaml",
        default_dockerfile="doc/Dockerfile",
        save_config=Mock(),
        capture_command=Mock(return_value=""),
        remote_read_project_file=Mock(return_value=""),
        manifest_cache={},
        confirm_action=Mock(return_value=True),
        reload_runtime=Mock(),
        restore_project_menu_input=Mock(),
        reset_preflight=Mock(),
    )


class ConfigWorkflowControllerTests(unittest.TestCase):
    def test_remote_project_config_ready_updates_port_status(self) -> None:
        controller = make_controller()
        port = FakePort()

        with patch(
            "components.config_workflow.src.workflow.config_accessor_api.remote_project_config_ready_plan",
            return_value={"ready": False, "status": "missing project"},
        ):
            self.assertFalse(controller.remote_project_config_ready(port))

        self.assertEqual(port.status, "missing project")

    def test_run_board_host_screen_wires_profile_and_field_controllers(self) -> None:
        controller = make_controller()
        port = FakePort()
        profile_controller = object()
        field_controller = object()

        with (
            patch(
                "components.config_workflow.src.workflow.config_profile_actions_api.profile_action_controller",
                return_value=profile_controller,
            ) as profile_factory,
            patch(
                "components.config_workflow.src.workflow.config_field_actions_api.field_action_controller",
                return_value=field_controller,
            ) as field_factory,
            patch(
                "components.config_workflow.src.workflow.config_board_screen_api.run_board_host_configurations_screen",
            ) as run_screen,
        ):
            controller.run_board_host_configurations_screen(port)

        profile_factory.assert_called_once()
        field_factory.assert_called_once()
        run_screen.assert_called_once_with(
            port,
            controller.config,
            save_config=controller.save_config,
            profile_action_controller=profile_controller,
            field_action_controller=field_controller,
        )

    def test_run_settings_action_uses_project_settings_controller(self) -> None:
        controller = make_controller()
        port = FakePort()
        settings_controller = Mock()
        settings_controller.run_action.return_value = True
        action = {"kind": "save"}

        with patch(
            "components.config_workflow.src.workflow.config_project_settings_actions_api.project_settings_action_controller",
            return_value=settings_controller,
        ) as settings_factory:
            result = controller.run_settings_action(port, action)

        self.assertTrue(result)
        settings_factory.assert_called_once()
        settings_controller.run_action.assert_called_once_with(port, action)

    def test_select_active_remote_uses_profile_picker(self) -> None:
        cfg = {
            "active_remote": "build-a",
            "remotes": [{"name": "build-a", "host": "10.0.0.1"}, {"name": "build-b", "host": "10.0.0.2"}],
        }
        controller = make_controller(cfg)
        port = FakePort()
        port.screen.keys = [curses.KEY_DOWN, 10]

        controller.select_active_remote(port)

        self.assertEqual(cfg["active_remote"], "build-b")
        self.assertEqual(port.status, "Active build host: build-b")
        controller.save_config.assert_called_once_with(cfg)
        rendered_text = "\n".join(row[2] for row in port.rows)
        self.assertIn("Select build host", rendered_text)
        self.assertIn("* build-a", rendered_text)
        self.assertIn("build-b", rendered_text)

    def test_select_active_board_host_uses_profile_picker(self) -> None:
        cfg = {
            "active_board_host": "board-a",
            "board_hosts": [{"name": "board-a", "host": "10.0.0.3"}, {"name": "board-b", "host": "10.0.0.4"}],
        }
        controller = make_controller(cfg)
        port = FakePort()
        port.screen.keys = [curses.KEY_DOWN, 10]

        controller.select_active_board_host(port)

        self.assertEqual(cfg["active_board_host"], "board-b")
        self.assertEqual(port.status, "Active board host: board-b")
        controller.save_config.assert_called_once_with(cfg)

    def test_select_active_remote_cancel_keeps_current_profile(self) -> None:
        cfg = {"active_remote": "build-a", "remotes": [{"name": "build-a"}]}
        controller = make_controller(cfg)
        port = FakePort()
        port.screen.keys = [27]

        controller.select_active_remote(port)

        self.assertEqual(cfg["active_remote"], "build-a")
        self.assertEqual(port.status, "Select build host cancelled")
        controller.save_config.assert_not_called()

    def test_select_active_remote_reports_missing_profiles(self) -> None:
        cfg = {"active_remote": "build-a", "remotes": []}
        controller = make_controller(cfg)
        port = FakePort()

        controller.select_active_remote(port)

        self.assertEqual(cfg["active_remote"], "build-a")
        self.assertEqual(port.status, "Select build host: no profiles configured")
        controller.save_config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
