from __future__ import annotations

import unittest
from typing import Any

from components.project_config.api import project_profile_screen_service


class FakePort:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.calls: list[str] = []

    def add_project_profile(self) -> None:
        self.calls.append("add")
        self.config["projects"].append({"name": "sdk"})
        self.config["active_project"] = "sdk"

    def delete_project_profile(self, project: dict[str, Any]) -> None:
        self.calls.append(f"delete:{project['name']}")
        self.config["projects"] = [item for item in self.config["projects"] if item["name"] != project["name"]]

    def set_active_project(self, project: dict[str, Any]) -> None:
        self.calls.append(f"set-active:{project['name']}")
        self.config["active_project"] = project["name"]


class FakeProfileActionController:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.calls: list[str] = []

    def add_project_profile(self, _port: Any) -> None:
        self.calls.append("add")
        self.config["projects"].append({"name": "sdk"})
        self.config["active_project"] = "sdk"

    def delete_project_profile(self, _port: Any, project: dict[str, Any]) -> None:
        self.calls.append(f"delete:{project['name']}")
        self.config["projects"] = [item for item in self.config["projects"] if item["name"] != project["name"]]

    def set_active_project(self, _port: Any, project: dict[str, Any]) -> None:
        self.calls.append(f"set-active:{project['name']}")
        self.config["active_project"] = project["name"]


def config() -> dict[str, Any]:
    return {
        "active_project": "prod",
        "projects": [{"name": "prod"}, {"name": "base"}],
    }


class ProjectProfileScreenServiceTests(unittest.TestCase):
    def test_add_project_uses_port_and_focuses_fields_for_new_active_project(self) -> None:
        cfg = config()
        port = FakePort(cfg)
        service = project_profile_screen_service.ProjectProfileScreenService(cfg)

        result = service.add_project(port)

        self.assertEqual(port.calls, ["add"])
        self.assertEqual([project["name"] for project in result["projects"]], ["prod", "base", "sdk"])
        self.assertEqual(result["project_index"], 2)
        self.assertEqual(result["focus"], "fields")

    def test_delete_project_uses_injected_controller_and_clamps_index(self) -> None:
        cfg = config()
        port = FakePort(cfg)
        controller = FakeProfileActionController(cfg)
        service = project_profile_screen_service.ProjectProfileScreenService(
            cfg,
            profile_action_controller=controller,
        )

        result = service.delete_project(port, cfg["projects"][1], current_index=1)

        self.assertEqual(controller.calls, ["delete:base"])
        self.assertEqual([project["name"] for project in result["projects"]], ["prod"])
        self.assertEqual(result["project_index"], 0)
        self.assertEqual(result["focus"], "projects")

    def test_set_active_project_delegates_to_injected_controller(self) -> None:
        cfg = config()
        port = FakePort(cfg)
        controller = FakeProfileActionController(cfg)
        service = project_profile_screen_service.ProjectProfileScreenService(
            cfg,
            profile_action_controller=controller,
        )

        service.set_active_project(port, cfg["projects"][1])

        self.assertEqual(controller.calls, ["set-active:base"])
        self.assertEqual(cfg["active_project"], "base")
        self.assertEqual(port.calls, [])


if __name__ == "__main__":
    unittest.main()
