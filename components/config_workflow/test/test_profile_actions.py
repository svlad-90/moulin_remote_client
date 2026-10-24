from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import Mock

from components.config.api import entities as config_entities
from components.config.api import store as config_store
from components.config_workflow.api import profile_actions
from plugins.cts_vts import config_entities as cts_vts_config_entities


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
        self.prompt_cancelled = False
        self.active_job = None
        self.board_job = None
        self.action_running = False
        self.connection_workflow_service = Mock()
        self.plugin_runtime = Mock(return_value=None)

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
        self.store = config_store.config_store(config, save=self.save_config)
        self.store.initialize([
            config_entities.core_profile_contributor(),
            cts_vts_config_entities.config_contributor(),
        ])
        self.controller = profile_actions.ProfileActionController(
            config,
            config_store=self.store,
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
        "remotes": [{"id": "build-id", "name": "build"}, {"id": "other-id", "name": "other"}],
        "active_remote": "build-id",
        "board_hosts": [{"id": "board-host-id", "name": "board"}, {"id": "lab-host-id", "name": "lab"}],
        "active_board_host": "board-host-id",
        "projects": [{"id": "project-one-id", "name": "one"}, {"id": "project-two-id", "name": "two"}],
        "active_project": "project-one-id",
    }


class ProfileActionControllerTests(unittest.TestCase):
    def test_add_remote_prompts_next_name_saves_and_reports_status(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        port.prompt_values["Build host profile name"] = " new-build "
        harness = Harness(cfg)

        harness.controller.add_remote(port)

        self.assertEqual(cfg["active_remote"], "build-id")
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

        self.assertEqual(cfg["active_board_host"], "board-host-id")
        self.assertEqual(cfg["board_hosts"][-1]["name"], "lab2")
        self.assertEqual(port.status, "Board host profile added: lab2")
        self.assertEqual(harness.save_count, 1)

    def test_add_board_adds_physical_board_to_selected_host(self) -> None:
        cfg = config()
        host = cfg["board_hosts"][0]
        port = FakeProfilePort()
        port.prompt_values["Board name"] = "board-a"
        harness = Harness(cfg)

        board = harness.controller.add_board(port, host)

        self.assertEqual(board["name"], "board-a")
        self.assertEqual(host["boards"][0]["name"], "board-a")
        self.assertEqual(port.status, "Board added: board-a")
        self.assertEqual(harness.save_count, 1)

    def test_delete_board_updates_plugin_references(self) -> None:
        cfg = config()
        host = cfg["board_hosts"][0]
        board = {"id": "board-a-id", "board_host_id": "board-host-id", "name": "board-a", "type": "gen5_x5h"}
        host["boards"] = [board]
        cfg["active_board"] = "board-a-id"
        cfg["plugins"] = {
            "cts-vts": {
                "enabled": True,
                "config": {
                    "board_profiles": [
                        {
                            "id": "profile-id",
                            "name": "lab",
                            "devices": [{"board_id": "board-a-id"}],
                        }
                    ]
                },
            }
        }
        port = FakeProfilePort()
        harness = Harness(cfg)
        port.config_store = config_store.config_store(cfg, save=harness.save_config)
        port.config_store.initialize(
            [
                config_entities.core_profile_contributor(),
                cts_vts_config_entities.config_contributor(),
            ]
        )

        deleted = harness.controller.delete_board(port, host, board)

        self.assertTrue(deleted)
        self.assertEqual(cfg["board_hosts"][0]["boards"], [])
        self.assertEqual(cfg["plugins"]["cts-vts"]["config"]["board_profiles"][0]["devices"], [])
        self.assertIn("CTS/VTS board profile lab", harness.confirm_requests[0][1])
        self.assertEqual(harness.save_count, 1)

    def test_switching_boards_on_same_host_preserves_connection(self) -> None:
        cfg = config()
        host = cfg["board_hosts"][0]
        host["boards"] = [
            {"id": "board-a-id", "board_host_id": "board-host-id", "name": "board-a"},
            {"id": "board-b-id", "board_host_id": "board-host-id", "name": "board-b"},
        ]
        cfg["active_board_host"] = "board-host-id"
        cfg["active_board"] = "board-a-id"
        port = FakeProfilePort()
        harness = Harness(cfg)

        harness.controller.set_active_board(port, host["boards"][1])

        self.assertEqual(cfg["active_board"], "board-b-id")
        self.assertEqual(port.board_connection_state, "connected")
        port.connection_workflow_service.assert_not_called()
        self.assertEqual(harness.save_count, 1)

    def test_add_project_profile_uses_current_runtime_context(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        port.prompt_values["Project profile name"] = " copy "
        harness = Harness(cfg)

        harness.controller.add_project_profile(port)

        self.assertEqual(cfg["active_project"], cfg["projects"][-1]["id"])
        self.assertEqual(cfg["projects"][-1]["name"], "copy")
        self.assertEqual(port.status, "Project added: copy")
        self.assertEqual(harness.reload_count, 1)
        self.assertEqual(harness.save_count, 1)

    def test_add_project_profile_disconnected_saves_without_runtime_reload(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        port.connection_state = "disconnected"
        port.prompt_values["Project profile name"] = " copy "
        harness = Harness(cfg)

        harness.controller.add_project_profile(port)

        self.assertEqual(cfg["active_project"], cfg["projects"][-1]["id"])
        self.assertEqual(port.status, "Project added: copy")
        self.assertEqual(harness.reload_count, 0)
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

    def test_add_profile_prompts_cancel_when_escape_cancelled(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        port.prompt_cancelled = True
        harness = Harness(cfg)

        harness.controller.add_project_profile(port)
        harness.controller.add_remote(port)
        harness.controller.add_board_host(port)

        self.assertEqual([project["name"] for project in cfg["projects"]], ["one", "two"])
        self.assertEqual([remote["name"] for remote in cfg["remotes"]], ["build", "other"])
        self.assertEqual([host["name"] for host in cfg["board_hosts"]], ["board", "lab"])
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

        self.assertEqual(cfg["active_remote"], "other-id")
        self.assertEqual(port.connection_state, "disconnected")
        self.assertEqual(port.preflight, "not run")
        self.assertEqual(port.status, "Active build host: other")
        self.assertEqual(harness.save_count, 1)

    def test_host_switch_reconnects_after_saving_and_resetting_state(self) -> None:
        cases = (
            ("remotes", "active_remote", "set_active_remote", "start_build_host_connect"),
            ("board_hosts", "active_board_host", "set_active_board_host", "start_board_host_connect"),
        )
        for profiles, active, select, connect in cases:
            with self.subTest(host=active):
                cfg = config()
                target = cfg[profiles][1]
                target.update(user="tester", host="new-host")
                port = FakeProfilePort()
                harness = Harness(cfg)
                service = port.connection_workflow_service.return_value

                def check_state(_port: Any) -> None:
                    self.assertIs(_port, port)
                    self.assertEqual(cfg[active], target["id"])
                    self.assertEqual(harness.save_count, 1)
                    if profiles == "remotes":
                        self.assertEqual(port.connection_state, "disconnected")
                        self.assertEqual(port.preflight, "not run")
                        self.assertEqual(port.board_connection_state, "connected")
                        port.connection_state = "connecting"
                    else:
                        self.assertEqual(port.board_connection_state, "disconnected")
                        self.assertEqual(port.connection_state, "connected")
                        self.assertEqual(port.preflight, "ok")
                        port.board_connection_state = "connecting"

                getattr(service, connect).side_effect = check_state
                getattr(harness.controller, select)(port, target)

                getattr(service, connect).assert_called_once_with(port)
                other = "start_board_host_connect" if profiles == "remotes" else "start_build_host_connect"
                getattr(service, other).assert_not_called()
                getattr(harness.controller, select)(port, target)
                getattr(service, connect).assert_called_once_with(port)
                self.assertEqual(harness.save_count, 1)

    def test_host_switch_does_not_connect_incomplete_profiles(self) -> None:
        for profiles, select in (
            ("remotes", "set_active_remote"),
            ("board_hosts", "set_active_board_host"),
        ):
            with self.subTest(host=profiles):
                cfg = config()
                port = FakeProfilePort()
                harness = Harness(cfg)

                getattr(harness.controller, select)(port, cfg[profiles][1])

                self.assertEqual(harness.save_count, 1)
                port.connection_workflow_service.assert_not_called()

    def test_host_switch_preserves_config_and_state_while_busy(self) -> None:
        for busy in ("active_job", "board_job", "action_running"):
            for profiles, active, select in (
                ("remotes", "active_remote", "set_active_remote"),
                ("board_hosts", "active_board_host", "set_active_board_host"),
            ):
                with self.subTest(busy=busy, host=active):
                    cfg = config()
                    port = FakeProfilePort()
                    setattr(port, busy, True if busy == "action_running" else {})
                    harness = Harness(cfg)
                    original = cfg[active]

                    getattr(harness.controller, select)(port, cfg[profiles][1])

                    self.assertEqual(cfg[active], original)
                    self.assertEqual(port.connection_state, "connected")
                    self.assertEqual(port.board_connection_state, "connected")
                    self.assertEqual(port.preflight, "ok")
                    self.assertIn("before switching hosts", port.status)
                    self.assertEqual(harness.save_count, 0)
                    port.connection_workflow_service.assert_not_called()

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

        self.assertEqual(cfg["active_board_host"], "lab-host-id")
        self.assertEqual(port.board_connection_state, "disconnected")
        self.assertEqual(port.status, "Active board host: lab")
        self.assertEqual(harness.save_count, 1)

    def test_delete_project_profile_reloads_and_resets_preflight_for_active_project(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        harness = Harness(cfg)

        harness.controller.delete_project_profile(port, cfg["projects"][0])

        self.assertEqual(cfg["active_project"], "project-two-id")
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

        self.assertEqual(cfg["active_project"], "project-two-id")
        self.assertEqual(port.preflight, "not run")
        self.assertEqual(port.status, "Active project: two")
        self.assertEqual(harness.reload_count, 1)
        self.assertEqual(harness.save_count, 1)

    def test_set_active_project_disconnected_saves_without_runtime_reload(self) -> None:
        cfg = config()
        port = FakeProfilePort()
        port.connection_state = "disconnected"
        harness = Harness(cfg)

        harness.controller.set_active_project(port, cfg["projects"][1])

        self.assertEqual(cfg["active_project"], "project-two-id")
        self.assertEqual(port.preflight, "not run")
        self.assertEqual(port.status, "Active project: two")
        self.assertEqual(harness.reload_count, 0)
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

        self.assertEqual(cfg["active_project"], "project-two-id")
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
