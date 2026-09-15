from __future__ import annotations

import unittest
from typing import Any

from components.config_workflow.api import field_actions


class FakeFieldPort:
    def __init__(self) -> None:
        self.status = ""
        self.connection_state = "connected"
        self.board_connection_state = "connected"
        self.preflight = "ok"
        self.preflight_values = {"docker": "ok"}
        self.menu_dirty = False
        self.render_cache: dict[str, Any] = {"header": "cached"}
        self.docker_image = "old-image"
        self.prompt_values: dict[str, str] = {}

    def prompt(self, label: str, current: str) -> str:
        return self.prompt_values.get(label, current)


class Harness:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.save_count = 0
        self.reload_count = 0
        self.controller = field_actions.FieldActionController(
            config,
            save_config=self.save_config,
            reload_runtime=self.reload_runtime,
        )

    def save_config(self, _config: dict[str, Any]) -> None:
        self.save_count += 1

    def reload_runtime(self) -> None:
        self.reload_count += 1


def config() -> dict[str, Any]:
    return {
        "remotes": [
            {"name": "build", "host": "old", "projects_dir": "/old"},
            {"name": "other", "host": "other"},
        ],
        "active_remote": "build",
        "board_hosts": [
            {"name": "board", "host": "old", "direct_copy": "no"},
            {"name": "lab", "host": "lab"},
        ],
        "active_board_host": "board",
        "projects": [
            {"name": "prod", "project_dir": "old", "docker_image": "old-image"},
            {"name": "sdk", "project_dir": "sdk"},
        ],
        "active_project": "prod",
    }


class FieldActionControllerTests(unittest.TestCase):
    def test_board_host_inline_update_resets_active_board_connection(self) -> None:
        cfg = config()
        port = FakeFieldPort()
        harness = Harness(cfg)

        harness.controller.apply_board_host_inline_value(port, cfg["board_hosts"][0], "host", " 10.0.0.2 ")

        self.assertEqual(cfg["board_hosts"][0]["host"], "10.0.0.2")
        self.assertEqual(port.board_connection_state, "disconnected")
        self.assertEqual(port.status, "host updated")
        self.assertEqual(harness.save_count, 1)

    def test_board_host_inline_update_handles_missing_selection(self) -> None:
        cfg = config()
        port = FakeFieldPort()
        harness = Harness(cfg)

        harness.controller.apply_board_host_inline_value(port, None, "host", "10.0.0.2")

        self.assertEqual(port.status, "No board host selected")
        self.assertEqual(harness.save_count, 0)

    def test_board_host_direct_copy_toggle_saves_status(self) -> None:
        cfg = config()
        port = FakeFieldPort()
        harness = Harness(cfg)

        harness.controller.toggle_board_host_direct_copy(port, cfg["board_hosts"][0])

        self.assertEqual(cfg["board_hosts"][0]["direct_copy"], "yes")
        self.assertEqual(port.status, "Direct copy: yes")
        self.assertEqual(harness.save_count, 1)

    def test_remote_inline_update_resets_active_build_connection_and_preflight(self) -> None:
        cfg = config()
        port = FakeFieldPort()
        harness = Harness(cfg)

        harness.controller.apply_remote_inline_value(port, cfg["remotes"][0], "host", "10.0.0.3")

        self.assertEqual(cfg["remotes"][0]["host"], "10.0.0.3")
        self.assertEqual(port.connection_state, "disconnected")
        self.assertEqual(port.preflight, "not run")
        self.assertEqual(port.preflight_values, {})
        self.assertEqual(port.status, "host updated")
        self.assertEqual(harness.save_count, 1)

    def test_remote_inline_update_handles_missing_selection(self) -> None:
        cfg = config()
        port = FakeFieldPort()
        harness = Harness(cfg)

        harness.controller.apply_remote_inline_value(port, None, "host", "10.0.0.3")

        self.assertEqual(port.status, "No build host selected")
        self.assertEqual(harness.save_count, 0)

    def test_remote_prompt_edit_uses_label_status_and_resets_active_connection(self) -> None:
        cfg = config()
        port = FakeFieldPort()
        port.prompt_values["SSH host"] = "10.0.0.4"
        harness = Harness(cfg)

        harness.controller.edit_remote_value(port, cfg["remotes"][0], "host", "SSH host")

        self.assertEqual(cfg["remotes"][0]["host"], "10.0.0.4")
        self.assertEqual(port.connection_state, "disconnected")
        self.assertEqual(port.preflight, "not run")
        self.assertEqual(port.status, "SSH host updated")
        self.assertEqual(harness.save_count, 1)

    def test_remote_projects_dir_browse_updates_selection(self) -> None:
        cfg = config()
        port = FakeFieldPort()
        harness = Harness(cfg)
        browsed: list[str] = []

        harness.controller.edit_remote_projects_dir(
            port,
            cfg["remotes"][0],
            browse_project_directory=lambda start: browsed.append(start) or "/mnt/projects",
        )

        self.assertEqual(browsed, ["/old"])
        self.assertEqual(cfg["remotes"][0]["projects_dir"], "/mnt/projects")
        self.assertEqual(port.status, "Projects dir: /mnt/projects")
        self.assertEqual(harness.save_count, 1)

    def test_remote_projects_dir_browse_cancel_does_not_save(self) -> None:
        cfg = config()
        port = FakeFieldPort()
        harness = Harness(cfg)

        harness.controller.edit_remote_projects_dir(
            port,
            cfg["remotes"][0],
            browse_project_directory=lambda _start: None,
        )

        self.assertEqual(cfg["remotes"][0]["projects_dir"], "/old")
        self.assertEqual(harness.save_count, 0)

    def test_remote_projects_dir_browse_allows_connected_state(self) -> None:
        cfg = config()
        port = FakeFieldPort()
        port.connection_state = "connected"
        harness = Harness(cfg)

        harness.controller.edit_remote_projects_dir(
            port,
            cfg["remotes"][0],
            browse_project_directory=lambda _start: "/mnt/projects",
        )

        self.assertEqual(cfg["remotes"][0]["projects_dir"], "/mnt/projects")
        self.assertEqual(port.connection_state, "connected")
        self.assertEqual(port.status, "Projects dir: /mnt/projects")
        self.assertEqual(harness.save_count, 1)

    def test_project_inline_update_reloads_and_resets_active_project(self) -> None:
        cfg = config()
        port = FakeFieldPort()
        harness = Harness(cfg)

        harness.controller.apply_project_inline_value(port, cfg["projects"][0], "project_dir", " /mnt/storage/meta-prod ")

        self.assertEqual(cfg["projects"][0]["project_dir"], "meta-prod")
        self.assertEqual(harness.reload_count, 1)
        self.assertEqual(port.preflight, "not run")
        self.assertEqual(port.status, "project_dir updated")
        self.assertEqual(harness.save_count, 1)

    def test_project_inline_docker_image_updates_runtime_value_without_preflight_reset(self) -> None:
        cfg = config()
        port = FakeFieldPort()
        harness = Harness(cfg)

        harness.controller.apply_project_inline_value(port, cfg["projects"][0], "docker_image", " image ")

        self.assertEqual(cfg["projects"][0]["docker_image"], "image")
        self.assertEqual(port.docker_image, "image")
        self.assertEqual(port.preflight, "ok")
        self.assertEqual(harness.reload_count, 1)
        self.assertEqual(harness.save_count, 1)

    def test_project_inline_update_handles_missing_selection(self) -> None:
        cfg = config()
        port = FakeFieldPort()
        harness = Harness(cfg)

        harness.controller.apply_project_inline_value(port, None, "project_dir", "meta")

        self.assertEqual(port.status, "No project selected")
        self.assertEqual(harness.save_count, 0)


if __name__ == "__main__":
    unittest.main()
