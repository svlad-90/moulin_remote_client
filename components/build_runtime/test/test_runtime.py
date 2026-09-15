from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from components.config.api import profiles
from components.build_runtime.api import runtime


class ConfigRuntimeBehaviorTests(unittest.TestCase):
    def test_load_runtime_config_uses_example_and_legacy_build_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            config_path = app_dir / "config.json"
            example_path = app_dir / "example.json"
            legacy_path = app_dir / "state" / "build-settings.json"
            legacy_path.parent.mkdir()
            legacy_path.write_text(
                json.dumps({"parameters": {"ENABLE_ANDROID": "yes"}, "targets": "legacy_target"}),
                encoding="utf-8",
            )
            example_path.write_text(
                json.dumps(
                    {
                        "remote": {"name": "build", "label": "Build", "user": "u", "host": "h"},
                        "project": {"project_dir": "/projects/meta-product"},
                        "local": {"project_dir": "overlay"},
                        "state": {"build_settings": str(legacy_path)},
                    }
                ),
                encoding="utf-8",
            )

            config = runtime.load_runtime_config(
                config_path,
                example_path,
                app_dir=app_dir,
                env={},
                default_build_targets="default_target",
                default_moulin_manifest="prod.yaml",
                default_dockerfile="doc/Dockerfile",
            )

            self.assertEqual(config["__config_path"], str(config_path))
            self.assertEqual(profiles.active_project(config)["parameters"], {"ENABLE_ANDROID": "yes"})
            self.assertEqual(profiles.active_project(config)["targets"], "legacy_target")
            self.assertEqual(profiles.active_project(config)["moulin_manifest"], "prod.yaml")

    def test_load_runtime_config_for_env_applies_env_build_target_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            config_path = app_dir / "config.json"
            example_path = app_dir / "example.json"
            example_path.write_text(
                json.dumps(
                    {
                        "remote": {"name": "build", "user": "u", "host": "h"},
                        "project": {"project_dir": "/projects/meta-product"},
                        "local": {"project_dir": "overlay"},
                    }
                ),
                encoding="utf-8",
            )

            config = runtime.load_runtime_config_for_env(
                config_path,
                example_path,
                app_dir=app_dir,
                env={"MOULIN_REMOTE_BUILD_TARGETS": "env_target"},
                default_build_targets="default_target",
                default_moulin_manifest="prod.yaml",
                default_dockerfile="doc/Dockerfile",
            )

            self.assertEqual(profiles.active_project(config)["targets"], "env_target")

    def test_runtime_build_settings_save_updates_project_and_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            config_path = app_dir / "config.json"
            settings_path = app_dir / "state" / "build-settings.json"
            config = {
                "__config_path": str(config_path),
                "state": {"build_settings": str(settings_path)},
                "remotes": [{"name": "build", "user": "u", "host": "h"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }
            profiles.normalize_remote_profiles(config)
            profiles.normalize_project_profiles(config)
            runtime.save_runtime_config(config, config_path)

            runtime.save_runtime_build_settings(
                config,
                {"parameters": {"ENABLE_DOMU": "yes"}, "targets": "target", "docker_image": "img"},
                app_dir,
                config_path,
            )

            self.assertEqual(profiles.active_project(config)["parameters"], {"ENABLE_DOMU": "yes"})
            self.assertEqual(profiles.active_project(config)["targets"], "target")
            self.assertEqual(json.loads(settings_path.read_text(encoding="utf-8"))["docker_image"], "img")

    def test_current_runtime_build_settings_helper_builds_settings_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            config_path = app_dir / "config.json"
            settings_path = app_dir / "state" / "build-settings.json"
            config = {
                "__config_path": str(config_path),
                "state": {"build_settings": str(settings_path)},
                "remotes": [{"name": "build", "user": "u", "host": "h"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }
            profiles.normalize_remote_profiles(config)
            profiles.normalize_project_profiles(config)

            runtime.save_current_runtime_build_settings(
                config,
                parameters={"ENABLE_ANDROID": "yes"},
                targets="android_only.img.gz",
                docker_image="prod-image",
                app_dir=app_dir,
                default_path=config_path,
            )

            self.assertEqual(profiles.active_project(config)["parameters"], {"ENABLE_ANDROID": "yes"})
            self.assertEqual(profiles.active_project(config)["targets"], "android_only.img.gz")
            self.assertEqual(profiles.active_project(config)["docker_image"], "prod-image")
            self.assertEqual(json.loads(settings_path.read_text(encoding="utf-8"))["targets"], "android_only.img.gz")

    def test_build_runtime_context_merges_config_settings_and_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            config = {
                "state": {"build_settings": str(app_dir / "state" / "build-settings.json")},
                "docker": {"image": "config-image"},
                "remotes": [{"name": "build", "user": "u", "host": "h"}],
                "active_remote": "build",
                "projects": [
                    {
                        "name": "prod",
                        "project_dir": "meta-product",
                        "parameters": {"ENABLE_ANDROID": "yes"},
                        "targets": "project-target",
                        "board_artifacts": "boot_artifacts",
                    }
                ],
                "active_project": "prod",
            }
            profiles.normalize_remote_profiles(config)
            profiles.normalize_project_profiles(config)

            context = runtime.build_runtime_context_for_config(
                config,
                app_dir=app_dir,
                env={"MOULIN_REMOTE_BUILD_TARGETS": "env-target"},
                default_docker_image="default-image",
                default_build_targets="default-target",
                default_parameters=lambda: {"ENABLE_DOMU": "no"},
            )

            self.assertEqual(context["docker_image"], "config-image")
            self.assertEqual(context["build_params"], {"ENABLE_DOMU": "no", "ENABLE_ANDROID": "yes"})
            self.assertEqual(context["build_targets"], "env-target")
            self.assertEqual(context["board_artifacts"], "boot_artifacts")


if __name__ == "__main__":
    unittest.main()
