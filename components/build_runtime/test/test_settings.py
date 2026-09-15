from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from components.config.api import profiles
from components.build_runtime.api import runtime as config_runtime
from components.build_runtime.api import settings as config_settings


class ConfigSettingsBehaviorTests(unittest.TestCase):
    def test_build_settings_merge_project_overrides_legacy_parameters(self) -> None:
        project = {
            "parameters": {"ENABLE_ANDROID": "yes"},
            "targets": "full_ufs.img.gz",
            "docker_image": "project_img",
        }
        legacy = {
            "parameters": {"ENABLE_ANDROID": "no", "ENABLE_DOMU": "yes"},
            "targets": "legacy_target",
            "docker_image": "legacy_img",
        }

        self.assertEqual(
            config_settings.build_settings_from_project(project, legacy, "default_target"),
            {
                "parameters": {"ENABLE_ANDROID": "yes", "ENABLE_DOMU": "yes"},
                "targets": "full_ufs.img.gz",
                "docker_image": "project_img",
            },
        )

    def test_build_settings_falls_back_to_legacy_when_project_values_are_empty(self) -> None:
        project = {"parameters": {}, "targets": "", "docker_image": ""}
        legacy = {"parameters": {"mode": "debug"}, "targets": "legacy_target", "docker_image": "legacy_img"}

        self.assertEqual(
            config_settings.build_settings_from_project(project, legacy, "default_target"),
            {
                "parameters": {"mode": "debug"},
                "targets": "legacy_target",
                "docker_image": "legacy_img",
            },
        )

    def test_apply_build_settings_to_project_matches_client_save_project_mutation(self) -> None:
        project = {"parameters": {"old": "value"}, "targets": "old", "docker_image": "old_img"}
        settings = {"parameters": {"new": "value"}, "targets": "target", "docker_image": "image"}

        config_settings.apply_build_settings_to_project(project, settings)

        self.assertEqual(project["parameters"], {"new": "value"})
        self.assertEqual(project["targets"], "target")
        self.assertEqual(project["docker_image"], "image")

    def test_runtime_load_build_settings_uses_component_model(self) -> None:
        config = {
            "projects": [
                {
                    "name": "prod",
                    "parameters": {"ENABLE_ANDROID": "yes"},
                    "targets": "full_ufs.img.gz",
                    "docker_image": "project_img",
                }
            ],
            "active_project": "prod",
            "remotes": [{"name": "build", "user": "u", "host": "h"}],
            "active_remote": "build",
        }
        profiles.normalize_remote_profiles(config)
        profiles.normalize_project_profiles(config)

        self.assertEqual(
            config_runtime.load_runtime_build_settings(config, Path("/tmp/app"), ""),
            config_settings.build_settings_from_project(profiles.active_project(config), {}, ""),
        )

    def test_build_settings_file_read_write_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state" / "settings.json"
            settings = {"parameters": {"ENABLE_ANDROID": "yes"}, "targets": "target", "docker_image": "img"}

            config_settings.write_build_settings_file(path, settings)

            self.assertEqual(config_settings.read_build_settings_file(path), settings)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), settings)

    def test_build_settings_file_read_returns_empty_for_missing_or_non_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"

            self.assertEqual(config_settings.read_build_settings_file(path), {})
            path.write_text("[1, 2]\n", encoding="utf-8")
            self.assertEqual(config_settings.read_build_settings_file(path), {})

    def test_legacy_build_settings_file_reader_ignores_bad_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            path.write_text("{bad json\n", encoding="utf-8")

            self.assertEqual(config_settings.read_legacy_build_settings_file(path), {})


if __name__ == "__main__":
    unittest.main()
