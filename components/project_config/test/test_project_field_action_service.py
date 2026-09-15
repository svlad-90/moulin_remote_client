from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from components.project_config.api import project_field_action_service


class FakePort:
    def __init__(self) -> None:
        self.status = ""
        self.connection_state = "connected"
        self.build_params: dict[str, str] = {}
        self.build_targets = ["full_ufs.img.gz"]
        self.docker_image = "image"
        self.calls: list[str] = []

    def apply_project_inline_value(self, project: dict[str, Any], key: str, value: str) -> None:
        self.calls.append(f"apply:{key}:{value}")
        project[key] = value

    def select_remote_moulin_manifest(self) -> None:
        self.calls.append("manifest")

    def select_remote_dockerfile(self) -> None:
        self.calls.append("dockerfile")

    def edit_project_remote_dir(self, _project: dict[str, Any]) -> None:
        self.calls.append("remote-dir")

    def edit_project_git_ref(self, _project: dict[str, Any]) -> None:
        self.calls.append("git-ref")

    def select_build_targets_screen(self) -> None:
        self.calls.append("targets")

    def select_board_artifacts_screen(self) -> None:
        self.calls.append("board-artifacts")

    def cycle_parameter(self, param: dict[str, Any]) -> None:
        self.calls.append(f"param:{param['name']}")
        self.build_params[str(param["name"])] = "yes"


class FakeFieldController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def apply_project_inline_value(self, _port: Any, project: dict[str, Any], key: str, value: str) -> None:
        self.calls.append((str(project.get("name", "")), key, value))
        project[key] = value


def config() -> dict[str, Any]:
    return {
        "active_project": "prod",
        "projects": [{"name": "prod", "label": "Prod", "project_dir": "meta"}],
    }


class ProjectFieldActionServiceTests(unittest.TestCase):
    def test_text_field_returns_edit_request_and_status(self) -> None:
        service = project_field_action_service.ProjectFieldActionService(
            config(),
            app_dir=Path("/app"),
            default_config_path=Path("/app/config.json"),
        )
        port = FakePort()
        project = {"name": "prod", "label": "Prod"}

        result = service.handle_enter_field(port, {"label": "Display label", "key": "label", "kind": "text"}, project)

        self.assertEqual(result, {"action": "edit-text", "key": "label", "value": "Prod"})
        self.assertEqual(port.status, "Editing Display label")

    def test_apply_project_value_uses_injected_field_controller(self) -> None:
        cfg = config()
        field_controller = FakeFieldController()
        service = project_field_action_service.ProjectFieldActionService(
            cfg,
            app_dir=Path("/app"),
            default_config_path=Path("/app/config.json"),
            field_action_controller=field_controller,
        )
        port = FakePort()
        project = {"name": "prod", "label": "Prod"}

        service.apply_project_value(port, project, "label", "New")

        self.assertEqual(project["label"], "New")
        self.assertEqual(field_controller.calls, [("prod", "label", "New")])
        self.assertEqual(port.calls, [])

    def test_parameter_field_cycles_and_persists_runtime_settings(self) -> None:
        cfg = config()
        runtime_saves: list[dict[str, Any]] = []
        service = project_field_action_service.ProjectFieldActionService(
            cfg,
            app_dir=Path("/app"),
            default_config_path=Path("/app/config.json"),
            save_runtime_settings=lambda _config, **kwargs: runtime_saves.append(kwargs),
        )
        port = FakePort()
        project = cfg["projects"][0]

        result = service.handle_enter_field(
            port,
            {"label": "ENABLE_ANDROID", "key": "param:ENABLE_ANDROID", "kind": "param", "param": {"name": "ENABLE_ANDROID"}},
            project,
        )

        self.assertEqual(result, {"action": "handled"})
        self.assertEqual(port.calls, ["param:ENABLE_ANDROID"])
        self.assertEqual(runtime_saves[0]["parameters"], port.build_params)
        self.assertEqual(runtime_saves[0]["targets"], port.build_targets)
        self.assertEqual(runtime_saves[0]["docker_image"], port.docker_image)


if __name__ == "__main__":
    unittest.main()
