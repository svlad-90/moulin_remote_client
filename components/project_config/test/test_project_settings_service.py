from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from components.project_config.api import project_settings_service


def config() -> dict[str, Any]:
    return {
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


class Harness:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.save_count = 0
        self.runtime_saves: list[dict[str, Any]] = []
        self.service = project_settings_service.ProjectSettingsService(
            cfg,
            app_dir=Path("/app"),
            default_config_path=Path("/app/config.json"),
            save_config=self.save_config,
            save_runtime_settings=self.save_runtime_settings,
        )

    def save_config(self, _config: dict[str, Any]) -> None:
        self.save_count += 1

    def save_runtime_settings(self, cfg: dict[str, Any], **kwargs: Any) -> None:
        self.runtime_saves.append({"config": cfg, **kwargs})


class ProjectSettingsServiceTests(unittest.TestCase):
    def test_cycle_parameter_updates_build_params_and_returns_status(self) -> None:
        harness = Harness(config())
        params = {"ENABLE_ANDROID": "yes"}

        status = harness.service.cycle_parameter(
            params,
            {"name": "ENABLE_ANDROID", "default": "no", "choices": ["no", "yes"]},
        )

        self.assertEqual(params["ENABLE_ANDROID"], "no")
        self.assertEqual(status, "ENABLE_ANDROID=no")

    def test_cycle_parameter_keeps_state_when_choices_are_empty(self) -> None:
        harness = Harness(config())
        params = {"ENABLE_ANDROID": "yes"}

        status = harness.service.cycle_parameter(
            params,
            {"name": "ENABLE_ANDROID", "default": "no", "choices": []},
        )

        self.assertEqual(params["ENABLE_ANDROID"], "yes")
        self.assertIsNone(status)

    def test_project_field_updates_keep_existing_field_plans(self) -> None:
        cfg = config()
        harness = Harness(cfg)

        harness.service.apply_local_project_dir("/new-overlay")
        git_plan = harness.service.apply_git_url("new-url")
        docker_image = harness.service.apply_docker_image("new-image")

        project = cfg["projects"][0]
        self.assertEqual(project["local_project_dir"], "/new-overlay")
        self.assertEqual(project["git_url"], "new-url")
        self.assertTrue(git_plan["preflight_reset"])
        self.assertEqual(project["docker_image"], "new-image")
        self.assertEqual(docker_image, "new-image")

    def test_save_project_settings_persists_runtime_then_config(self) -> None:
        cfg = config()
        harness = Harness(cfg)
        params = {"ENABLE_ANDROID": "yes"}
        targets = ["full_ufs.img.gz"]

        harness.service.save_project_settings(parameters=params, targets=targets, docker_image="image")

        self.assertEqual(len(harness.runtime_saves), 1)
        self.assertEqual(harness.runtime_saves[0]["config"], cfg)
        self.assertEqual(harness.runtime_saves[0]["parameters"], params)
        self.assertEqual(harness.runtime_saves[0]["targets"], targets)
        self.assertEqual(harness.runtime_saves[0]["docker_image"], "image")
        self.assertEqual(harness.save_count, 1)


if __name__ == "__main__":
    unittest.main()
