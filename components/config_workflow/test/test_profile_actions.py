from __future__ import annotations

import unittest
from typing import Any

from components.config_workflow.api import profile_actions


class FakeProfilePort:
    def __init__(self) -> None:
        self.status = ""
        self.connection_state = "connected"
        self.board_connection_state = "connected"
        self.preflight = "ok"
        self.preflight_values = {"docker": "ok"}
        self.menu_dirty = False
        self.render_cache: dict[str, Any] = {"header": "cached"}
        self.build_params = {"ENABLE_ANDROID": "yes"}
        self.build_targets = ["full_ufs.img.gz"]
        self.board_artifacts = ["full_ufs.img.gz"]
        self.docker_image = "builder:latest"
        self.prompt_values: dict[str, str] = {}

    def prompt(self, label: str, current: str) -> str:
        return self.prompt_values.get(label, current)


class Harness:
    def __init__(self, config: dict[str, Any], *, confirm: bool = True) -> None:
        self.config = config
        self.confirm = confirm
        self.confirm_requests: list[tuple[str, str]] = []
        self.save_count = 0
        self.reload_count = 0
        self.restore_count = 0
        self.controller = profile_actions.ProfileActionController(
            config,
            save_config=self.save_config,
            confirm_action=self.confirm_action,
            reload_runtime=self.reload_runtime,
            restore_project_menu_input=self.restore_project_menu_input,
        )

    def save_config(self, _config: dict[str, Any]) -> None:
        self.save_count += 1

    def confirm_action(self, label: str, description: str) -> bool:
        self.confirm_requests.append((label, description))
        return self.confirm

    def reload_runtime(self) -> None:
        self.reload_count += 1

    def restore_project_menu_input(self) -> None:
        self.restore_count += 1


def config() -> dict[str, Any]:
    return {
        "remotes": [{"name": "build"}, {"name": "other"}],
        "active_remote": "build",
        "board_hosts": [{"name": "board"}, {"name": "lab"}],
        "active_board_host": "board",
        "projects": [{"name": "one"}, {"name": "two"}],
        "active_project": "one",
    }


class ProfileActionControllerTests(unittest.TestCase):
    def test_add_remote_prompts_next_name_saves_and_reports_status(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        port.prompt_values["Build host profile name"] = " new-build "
        harness = Harness(cfg)

        harness.controller.add_remote(port)

        self.assertEqual(cfg["active_remote"], "build")
        self.assertEqual(cfg["remotes"][-1]["name"], "new-build")
        self.assertEqual(port.status, "Build host profile added: new-build")
        self.assertEqual(harness.save_count, 1)

    def test_add_remote_cancel_preserves_config(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        port.prompt_values["Build host profile name"] = " "
        harness = Harness(cfg)

        harness.controller.add_remote(port)

        self.assertEqual(len(cfg["remotes"]), 2)
        self.assertEqual(port.status, "Build host add cancelled")
        self.assertEqual(harness.save_count, 0)

    def test_add_board_host_prompts_next_name_saves_and_reports_status(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        port.prompt_values["Board host profile name"] = " lab2 "
        harness = Harness(cfg)

        harness.controller.add_board_host(port)

        self.assertEqual(cfg["active_board_host"], "board")
        self.assertEqual(cfg["board_hosts"][-1]["name"], "lab2")
        self.assertEqual(port.status, "Board host profile added: lab2")
        self.assertEqual(harness.save_count, 1)

    def test_add_project_profile_uses_current_runtime_context(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        port.prompt_values["Project profile name"] = " copy "
        harness = Harness(cfg)

        harness.controller.add_project_profile(port)

        self.assertEqual(cfg["active_project"], "copy")
        self.assertEqual(cfg["projects"][-1]["name"], "copy")
        self.assertEqual(port.status, "Project added: copy")
        self.assertEqual(harness.reload_count, 1)
        self.assertEqual(harness.save_count, 1)

    def test_add_project_profile_cancel_preserves_config(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        port.prompt_values["Project profile name"] = ""
        harness = Harness(cfg)

        harness.controller.add_project_profile(port)

        self.assertEqual(len(cfg["projects"]), 2)
        self.assertEqual(port.status, "Project add cancelled: empty name")
        self.assertEqual(harness.save_count, 0)

    def test_delete_active_remote_resets_connection_and_preflight(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        harness = Harness(cfg)

        harness.controller.delete_remote(port, cfg["remotes"][0])

        self.assertEqual(port.connection_state, "disconnected")
        self.assertEqual(port.preflight, "not run")
        self.assertEqual(port.preflight_values, {})
        self.assertEqual(port.status, "Build host profile deleted: build")
        self.assertEqual(harness.save_count, 1)

    def test_delete_remote_cancel_preserves_state(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        harness = Harness(cfg, confirm=False)

        harness.controller.delete_remote(port, cfg["remotes"][0])

        self.assertEqual(port.connection_state, "connected")
        self.assertEqual(port.status, "Build host delete cancelled")
        self.assertEqual(harness.save_count, 0)

    def test_set_active_remote_saves_only_changed_selection(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        harness = Harness(cfg)

        harness.controller.set_active_remote(port, cfg["remotes"][1])

        self.assertEqual(cfg["active_remote"], "other")
        self.assertEqual(port.connection_state, "disconnected")
        self.assertEqual(port.preflight, "not run")
        self.assertEqual(port.status, "Active build host: other")
        self.assertEqual(harness.save_count, 1)

    def test_delete_active_board_host_resets_board_connection(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        harness = Harness(cfg)

        harness.controller.delete_board_host(port, cfg["board_hosts"][0])

        self.assertEqual(port.board_connection_state, "disconnected")
        self.assertEqual(port.status, "Board host profile deleted: board")
        self.assertEqual(harness.save_count, 1)

    def test_set_active_board_host_saves_only_changed_selection(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        harness = Harness(cfg)

        harness.controller.set_active_board_host(port, cfg["board_hosts"][1])

        self.assertEqual(cfg["active_board_host"], "lab")
        self.assertEqual(port.board_connection_state, "disconnected")
        self.assertEqual(port.status, "Active board host: lab")
        self.assertEqual(harness.save_count, 1)

    def test_delete_project_profile_reloads_and_resets_preflight_for_active_project(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        harness = Harness(cfg)

        harness.controller.delete_project_profile(port, cfg["projects"][0])

        self.assertEqual(cfg["active_project"], "two")
        self.assertEqual(port.preflight, "not run")
        self.assertEqual(port.status, "Project deleted: one")
        self.assertEqual(harness.reload_count, 1)
        self.assertEqual(harness.restore_count, 1)
        self.assertEqual(harness.save_count, 1)

    def test_set_active_project_saves_reloads_and_resets_preflight(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        harness = Harness(cfg)

        harness.controller.set_active_project(port, cfg["projects"][1])

        self.assertEqual(cfg["active_project"], "two")
        self.assertEqual(port.preflight, "not run")
        self.assertEqual(port.status, "Active project: two")
        self.assertEqual(harness.reload_count, 1)
        self.assertEqual(harness.save_count, 1)

    def test_set_active_project_does_not_save_unchanged_selection(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        harness = Harness(cfg)

        harness.controller.set_active_project(port, cfg["projects"][0])

        self.assertEqual(port.status, "selected project is already active")
        self.assertEqual(harness.reload_count, 0)
        self.assertEqual(harness.save_count, 0)

    def test_delete_project_profile_cancel_restores_project_menu_input(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        harness = Harness(cfg, confirm=False)

        harness.controller.delete_project_profile(port, cfg["projects"][0])

        self.assertEqual(port.status, "Project delete cancelled")
        self.assertEqual(harness.restore_count, 1)
        self.assertEqual(harness.save_count, 0)

    def test_delete_active_project_profile_preserves_existing_preflight_behavior(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        harness = Harness(cfg)

        harness.controller.delete_active_project_profile(port)

        self.assertEqual(cfg["active_project"], "two")
        self.assertEqual(port.preflight, "ok")
        self.assertEqual(port.status, "Project deleted: one")
        self.assertEqual(harness.reload_count, 1)
        self.assertEqual(harness.restore_count, 1)
        self.assertEqual(harness.save_count, 1)

    def test_delete_last_project_is_rejected(self) -> None:
        cfg = {"projects": [{"name": "only"}], "active_project": "only"}
        port = FakeProfilePort()
        harness = Harness(cfg)

        harness.controller.delete_active_project_profile(port)

        self.assertEqual(port.status, "Cannot delete the only project")
        self.assertEqual(harness.confirm_requests, [])
        self.assertEqual(harness.save_count, 0)


if __name__ == "__main__":
    unittest.main()
