from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import Mock

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
        self.batch_calls: list[dict[str, Any]] = []

    def apply_project_inline_value(self, _port: Any, project: dict[str, Any], key: str, value: str) -> None:
        self.calls.append((str(project.get("name", "")), key, value))
        project[key] = value

    def apply_project_values(
        self,
        port: Any,
        project: dict[str, Any],
        changes: dict[str, Any],
        *,
        status: str,
    ) -> bool:
        self.batch_calls.append(changes)
        project.update(changes)
        port.status = status
        return True


class FakeSettingsController:
    def cycle_parameter(self, port: Any, param: dict[str, Any]) -> None:
        port.calls.append(f"param:{param['name']}")
        port.build_params[str(param["name"])] = "yes"


def service(
    cfg: dict[str, Any],
    *,
    field_controller: FakeFieldController | None = None,
    product_type_selector: Any = None,
) -> project_field_action_service.ProjectFieldActionService:
    return project_field_action_service.ProjectFieldActionService(
        cfg,
        target_selection_controller_factory=Mock(),
        project_settings_controller=FakeSettingsController(),
        remote_file_selection_controller=Mock(),
        project_remote_dir_editor=Mock(),
        project_git_ref_selector=Mock(),
        field_action_controller=field_controller or FakeFieldController(),
        reload_runtime=Mock(),
        product_type_selector=product_type_selector,
    )


def config() -> dict[str, Any]:
    return {
        "active_project": "prod",
        "projects": [{"name": "prod", "label": "Prod", "project_dir": "meta"}],
    }


class ProjectFieldActionServiceTests(unittest.TestCase):
    def test_product_type_field_selects_a_registered_adapter(self) -> None:
        cfg = config()
        field_controller = FakeFieldController()
        action_service = service(cfg, field_controller=field_controller)
        port = FakePort()
        project = cfg["projects"][0]

        result = action_service.handle_enter_field(
            port,
            {"label": "Product type", "key": "product_type", "kind": "product_type"},
            project,
        )

        self.assertEqual(result, {"action": "handled"})
        self.assertEqual(project["product_type"], "gen5_xen_android")
        self.assertEqual(field_controller.calls, [("prod", "product_type", "gen5_xen_android")])
        self.assertEqual(port.status, "Product type: gen5_xen_android")

    def test_product_type_field_uses_injected_selector(self) -> None:
        cfg = config()
        selections: list[tuple[str, str]] = []

        def select_product_type(_port: Any, _service: Any, current: str) -> str:
            selections.append(("select", current))
            return "other_product"

        field_controller = FakeFieldController()
        action_service = service(
            cfg,
            field_controller=field_controller,
            product_type_selector=select_product_type,
        )
        port = FakePort()
        project = {"name": "prod", "product_type": "gen5_xen_android"}

        result = action_service.handle_enter_field(
            port,
            {"label": "Product type", "key": "product_type", "kind": "product_type"},
            project,
        )

        self.assertEqual(result, {"action": "handled"})
        self.assertEqual(selections, [("select", "gen5_xen_android")])
        self.assertEqual(project["product_type"], "other_product")
        self.assertEqual(port.status, "Product type: other_product")

    def test_text_field_returns_edit_request_and_status(self) -> None:
        action_service = service(config())
        port = FakePort()
        project = {"name": "prod", "label": "Prod"}

        result = action_service.handle_enter_field(port, {"label": "Display label", "key": "label", "kind": "text"}, project)

        self.assertEqual(result, {"action": "edit-text", "key": "label", "value": "Prod"})
        self.assertEqual(port.status, "Editing Display label")

    def test_apply_project_value_uses_injected_field_controller(self) -> None:
        cfg = config()
        field_controller = FakeFieldController()
        action_service = service(cfg, field_controller=field_controller)
        port = FakePort()
        project = {"name": "prod", "label": "Prod"}

        action_service.apply_project_value(port, project, "label", "New")

        self.assertEqual(project["label"], "New")
        self.assertEqual(field_controller.calls, [("prod", "label", "New")])
        self.assertEqual(port.calls, [])

    def test_parameter_field_cycles_and_persists_runtime_settings(self) -> None:
        cfg = config()
        field_controller = FakeFieldController()
        action_service = service(cfg, field_controller=field_controller)
        port = FakePort()
        project = cfg["projects"][0]

        result = action_service.handle_enter_field(
            port,
            {"label": "ENABLE_ANDROID", "key": "param:ENABLE_ANDROID", "kind": "param", "param": {"name": "ENABLE_ANDROID"}},
            project,
        )

        self.assertEqual(result, {"action": "handled"})
        self.assertEqual(port.calls, ["param:ENABLE_ANDROID"])
        self.assertEqual(field_controller.batch_calls[0]["parameters"], port.build_params)
        self.assertEqual(field_controller.batch_calls[0]["targets"], port.build_targets)
        self.assertEqual(field_controller.batch_calls[0]["docker_image"], port.docker_image)


if __name__ == "__main__":
    unittest.main()
