from __future__ import annotations

import unittest
from typing import Any

from components.host_config_ui.api import remote_edit_workflow


class FakePort:
    def __init__(self) -> None:
        self.status = ""
        self.connection_state = "disconnected"


class FakeProfileActionController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def set_active_remote(self, port: Any, remote: dict[str, Any]) -> None:
        self.calls.append(("set-active", str(remote.get("name", ""))))
        port.status = "active by controller"


class FakeFieldActionController:
    def __init__(self) -> None:
        self.edit_value_calls: list[tuple[str, str, str]] = []
        self.project_dir_calls: list[str] = []

    def edit_remote_value(self, _port: Any, remote: dict[str, Any], key: str, label: str) -> None:
        self.edit_value_calls.append((str(remote.get("name", "")), key, label))

    def edit_remote_projects_dir(
        self,
        _port: Any,
        remote: dict[str, Any],
        *,
        browse_project_directory: Any,
    ) -> None:
        self.project_dir_calls.append(str(remote.get("name", "")))
        selected = browse_project_directory(str(remote.get("projects_dir", "")))
        if selected:
            remote["projects_dir"] = selected


def config() -> dict[str, Any]:
    return {
        "remotes": [
            {"name": "build-a", "label": "Build A", "user": "user", "host": "10.0.0.1", "projects_dir": "/mnt/a"},
        ],
        "active_remote": "build-a",
    }


class RemoteEditWorkflowServiceTests(unittest.TestCase):
    def test_enter_selected_scalar_field_uses_field_action_controller(self) -> None:
        cfg = config()
        profile_actions = FakeProfileActionController()
        field_actions = FakeFieldActionController()
        service = remote_edit_workflow.RemoteEditWorkflowService(
            cfg,
            cfg["remotes"][0],
            save_config=lambda _config: None,
            profile_action_controller=profile_actions,
            field_action_controller=field_actions,
            browse_project_directory=lambda _start: None,
        )

        closed = service.handle_enter(FakePort())

        self.assertFalse(closed)
        self.assertEqual(field_actions.edit_value_calls, [("build-a", "name", "Profile name")])

    def test_projects_dir_browse_uses_injected_browser(self) -> None:
        cfg = config()
        field_actions = FakeFieldActionController()
        service = remote_edit_workflow.RemoteEditWorkflowService(
            cfg,
            cfg["remotes"][0],
            save_config=lambda _config: None,
            profile_action_controller=FakeProfileActionController(),
            field_action_controller=field_actions,
            browse_project_directory=lambda _start: "/mnt/new",
        )
        service.index = 4

        closed = service.handle_enter(FakePort())

        self.assertFalse(closed)
        self.assertEqual(field_actions.project_dir_calls, ["build-a"])
        self.assertEqual(cfg["remotes"][0]["projects_dir"], "/mnt/new")

    def test_disabled_host_edit_reports_status(self) -> None:
        cfg = config()
        cfg["remotes"][0]["user"] = ""
        service = remote_edit_workflow.RemoteEditWorkflowService(
            cfg,
            cfg["remotes"][0],
            save_config=lambda _config: None,
            profile_action_controller=FakeProfileActionController(),
            field_action_controller=FakeFieldActionController(),
            browse_project_directory=lambda _start: None,
        )
        service.index = 3
        port = FakePort()

        closed = service.handle_enter(port)

        self.assertFalse(closed)
        self.assertEqual(port.status, "set SSH user first")

    def test_back_and_quit_save_config(self) -> None:
        cfg = config()
        saves: list[dict[str, Any]] = []
        service = remote_edit_workflow.RemoteEditWorkflowService(
            cfg,
            cfg["remotes"][0],
            save_config=saves.append,
            profile_action_controller=FakeProfileActionController(),
            field_action_controller=FakeFieldActionController(),
            browse_project_directory=lambda _start: None,
        )
        service.index = 5

        self.assertTrue(service.handle_enter(FakePort()))
        service.save_and_close()
        self.assertEqual(saves, [cfg, cfg])

    def test_set_active_delegates_to_profile_action_controller(self) -> None:
        cfg = config()
        profile_actions = FakeProfileActionController()
        service = remote_edit_workflow.RemoteEditWorkflowService(
            cfg,
            cfg["remotes"][0],
            save_config=lambda _config: None,
            profile_action_controller=profile_actions,
            field_action_controller=FakeFieldActionController(),
            browse_project_directory=lambda _start: None,
        )
        port = FakePort()

        service.set_active(port)

        self.assertEqual(profile_actions.calls, [("set-active", "build-a")])
        self.assertEqual(port.status, "active by controller")


if __name__ == "__main__":
    unittest.main()
