from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from components.project_config.api import project_settings_actions


class FakeSettingsPort:
    def __init__(self) -> None:
        self.status = ""
        self.preflight = "ok"
        self.preflight_values = {"docker": "ok"}
        self.menu_dirty = False
        self.render_cache: dict[str, Any] = {"header": "cached"}
        self.docker_image = "old-image"
        self.build_params = {"ENABLE_ANDROID": "yes"}
        self.build_targets = ["full_ufs.img.gz"]
        self.calls: list[str] = []
        self.prompts: dict[str, str] = {}

    def select_project_screen(self) -> None:
        self.calls.append("select_project")

    def add_project_profile(self) -> None:
        self.calls.append("add_project")

    def delete_active_project_profile(self) -> None:
        self.calls.append("delete_project")

    def select_remote_moulin_manifest(self) -> None:
        self.calls.append("manifest")

    def select_remote_dockerfile(self) -> None:
        self.calls.append("dockerfile")

    def select_build_targets_screen(self) -> None:
        self.calls.append("targets")

    def select_board_artifacts_screen(self) -> None:
        self.calls.append("board_artifacts")

    def prompt(self, label: str, current: str) -> str:
        self.calls.append(f"prompt:{label}:{current}")
        return self.prompts.get(label, current)


class Harness:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.save_count = 0
        self.runtime_saves: list[dict[str, Any]] = []
        self.controller = project_settings_actions.ProjectSettingsActionController(
            config,
            app_dir=Path("/app"),
            default_config_path=Path("/app/config.json"),
            save_config=self.save_config,
            save_runtime_settings=self.save_runtime_settings,
        )

    def save_config(self, _config: dict[str, Any]) -> None:
        self.save_count += 1

    def save_runtime_settings(self, config: dict[str, Any], **kwargs: Any) -> None:
        self.runtime_saves.append({"config": config, **kwargs})


class FakeTargetSelector:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.reload_runtime: Any = None

    def select_build_targets(self, _port: Any, *, reload_runtime: Any) -> None:
        self.calls.append("targets")
        self.reload_runtime = reload_runtime

    def select_board_artifacts(self, _port: Any, *, reload_runtime: Any) -> None:
        self.calls.append("board_artifacts")
        self.reload_runtime = reload_runtime


class FakeRemoteFileSelector:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def select_moulin_manifest(self, _port: Any) -> None:
        self.calls.append("manifest")

    def select_dockerfile(self, _port: Any) -> None:
        self.calls.append("dockerfile")


class FakeProfileActionController:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def add_project_profile(self, _port: Any) -> None:
        self.calls.append("add")

    def delete_active_project_profile(self, _port: Any) -> None:
        self.calls.append("delete-active")


class FakeProjectPickerController:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.reload_runtime: Any = None

    def select_project(self, _port: Any, *, reload_runtime: Any) -> None:
        self.calls.append("select_project")
        self.reload_runtime = reload_runtime


def config() -> dict[str, Any]:
    return {
        "remote": {"name": "build"},
        "active_remote": "build",
        "remotes": [{"name": "build"}],
        "active_project": "prod",
        "projects": [
            {
                "name": "prod",
                "local_project_dir": "/overlay",
                "git_url": "old-url",
                "docker_image": "old-image",
            }
        ],
    }


class ProjectSettingsActionControllerTests(unittest.TestCase):
    def test_navigation_actions_delegate_to_port_and_keep_screen_open(self) -> None:
        cfg = config()
        port = FakeSettingsPort()
        harness = Harness(cfg)

        for kind in ("select_project", "add_project", "delete_project", "manifest", "dockerfile", "targets", "board_artifacts"):
            with self.subTest(kind=kind):
                self.assertFalse(harness.controller.run_action(port, {"kind": kind}))

        self.assertEqual(
            port.calls,
            ["select_project", "add_project", "delete_project", "manifest", "dockerfile", "targets", "board_artifacts"],
        )

    def test_target_actions_use_injected_target_selection_service(self) -> None:
        cfg = config()
        port = FakeSettingsPort()
        selector = FakeTargetSelector()
        reloaded: list[bool] = []
        controller = project_settings_actions.ProjectSettingsActionController(
            cfg,
            app_dir=Path("/app"),
            default_config_path=Path("/app/config.json"),
            save_config=lambda _config: None,
            target_selection_controller_factory=lambda: selector,
            reload_runtime=lambda: reloaded.append(True),
        )

        self.assertFalse(controller.run_action(port, {"kind": "targets"}))
        self.assertFalse(controller.run_action(port, {"kind": "board_artifacts"}))
        selector.reload_runtime()

        self.assertEqual(selector.calls, ["targets", "board_artifacts"])
        self.assertEqual(reloaded, [True])
        self.assertNotIn("targets", port.calls)
        self.assertNotIn("board_artifacts", port.calls)

    def test_remote_file_actions_use_injected_remote_file_selection_service(self) -> None:
        cfg = config()
        port = FakeSettingsPort()
        selector = FakeRemoteFileSelector()
        controller = project_settings_actions.ProjectSettingsActionController(
            cfg,
            app_dir=Path("/app"),
            default_config_path=Path("/app/config.json"),
            save_config=lambda _config: None,
            remote_file_selection_controller=selector,
        )

        self.assertFalse(controller.run_action(port, {"kind": "manifest"}))
        self.assertFalse(controller.run_action(port, {"kind": "dockerfile"}))

        self.assertEqual(selector.calls, ["manifest", "dockerfile"])
        self.assertNotIn("manifest", port.calls)
        self.assertNotIn("dockerfile", port.calls)

    def test_project_profile_actions_use_injected_profile_action_service(self) -> None:
        cfg = config()
        port = FakeSettingsPort()
        profile_actions = FakeProfileActionController()
        controller = project_settings_actions.ProjectSettingsActionController(
            cfg,
            app_dir=Path("/app"),
            default_config_path=Path("/app/config.json"),
            save_config=lambda _config: None,
            profile_action_controller=profile_actions,
        )

        self.assertFalse(controller.run_action(port, {"kind": "add_project"}))
        self.assertFalse(controller.run_action(port, {"kind": "delete_project"}))

        self.assertEqual(profile_actions.calls, ["add", "delete-active"])
        self.assertNotIn("add_project", port.calls)
        self.assertNotIn("delete_project", port.calls)

    def test_select_project_uses_injected_project_picker_service(self) -> None:
        cfg = config()
        port = FakeSettingsPort()
        picker = FakeProjectPickerController()
        reloaded: list[bool] = []
        controller = project_settings_actions.ProjectSettingsActionController(
            cfg,
            app_dir=Path("/app"),
            default_config_path=Path("/app/config.json"),
            save_config=lambda _config: None,
            project_picker_controller=picker,
            reload_runtime=lambda: reloaded.append(True),
        )

        self.assertFalse(controller.run_action(port, {"kind": "select_project"}))
        picker.reload_runtime()

        self.assertEqual(picker.calls, ["select_project"])
        self.assertEqual(reloaded, [True])
        self.assertNotIn("select_project", port.calls)

    def test_parameter_action_cycles_build_parameter(self) -> None:
        port = FakeSettingsPort()
        harness = Harness(config())

        result = harness.controller.run_action(
            port,
            {"kind": "param", "param": {"name": "ENABLE_ANDROID", "default": "no", "choices": ["no", "yes"]}},
        )

        self.assertFalse(result)
        self.assertEqual(port.build_params["ENABLE_ANDROID"], "no")
        self.assertEqual(port.status, "ENABLE_ANDROID=no")

    def test_parameter_action_keeps_state_when_choices_are_empty(self) -> None:
        port = FakeSettingsPort()
        harness = Harness(config())

        result = harness.controller.run_action(
            port,
            {"kind": "param", "param": {"name": "ENABLE_ANDROID", "default": "no", "choices": []}},
        )

        self.assertFalse(result)
        self.assertEqual(port.build_params["ENABLE_ANDROID"], "yes")
        self.assertEqual(port.status, "")

    def test_local_project_dir_updates_active_project_without_preflight_reset(self) -> None:
        cfg = config()
        port = FakeSettingsPort()
        port.prompts["Local overlay dir"] = "/new-overlay"
        harness = Harness(cfg)

        result = harness.controller.run_action(port, {"kind": "local_project_dir"})

        self.assertFalse(result)
        self.assertEqual(cfg["projects"][0]["local_project_dir"], "/new-overlay")
        self.assertEqual(port.preflight, "ok")

    def test_git_url_updates_active_project_and_resets_preflight(self) -> None:
        cfg = config()
        port = FakeSettingsPort()
        port.prompts["Project Git URL"] = "new-url"
        harness = Harness(cfg)

        result = harness.controller.run_action(port, {"kind": "git_url"})

        self.assertFalse(result)
        self.assertEqual(cfg["projects"][0]["git_url"], "new-url")
        self.assertEqual(port.preflight, "not run")
        self.assertEqual(port.preflight_values, {})
        self.assertNotIn("header", port.render_cache)

    def test_docker_image_updates_active_project_and_port_runtime_value(self) -> None:
        cfg = config()
        port = FakeSettingsPort()
        port.prompts["Docker image name"] = "new-image"
        harness = Harness(cfg)

        result = harness.controller.run_action(port, {"kind": "docker"})

        self.assertFalse(result)
        self.assertEqual(cfg["projects"][0]["docker_image"], "new-image")
        self.assertEqual(port.docker_image, "new-image")

    def test_save_persists_runtime_settings_and_closes_screen(self) -> None:
        cfg = config()
        port = FakeSettingsPort()
        harness = Harness(cfg)

        result = harness.controller.run_action(port, {"kind": "save"})

        self.assertTrue(result)
        self.assertEqual(len(harness.runtime_saves), 1)
        self.assertEqual(harness.runtime_saves[0]["parameters"], port.build_params)
        self.assertEqual(harness.runtime_saves[0]["targets"], port.build_targets)
        self.assertEqual(harness.runtime_saves[0]["docker_image"], port.docker_image)
        self.assertEqual(harness.save_count, 1)
        self.assertEqual(port.status, "Project saved")

    def test_back_keeps_changes_in_memory_and_closes_screen(self) -> None:
        port = FakeSettingsPort()
        harness = Harness(config())

        result = harness.controller.run_action(port, {"kind": "back"})

        self.assertTrue(result)
        self.assertEqual(port.status, "Project changes kept in memory, not saved")
        self.assertEqual(harness.save_count, 0)

    def test_unknown_action_keeps_screen_open(self) -> None:
        port = FakeSettingsPort()
        harness = Harness(config())

        self.assertFalse(harness.controller.run_action(port, {"kind": "unknown"}))


if __name__ == "__main__":
    unittest.main()
