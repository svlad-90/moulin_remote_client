from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from components.config_workflow.api import workflow


class FakePort:
    def __init__(self) -> None:
        self.connection_state = "disconnected"
        self.status = ""


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


if __name__ == "__main__":
    unittest.main()
