from __future__ import annotations

import unittest

from components.build_runtime.api import env as config_env
from components.config.api import profiles


def sample_config() -> dict[str, object]:
    config: dict[str, object] = {
        "remotes": [{"name": "build", "label": "Build", "user": "", "host": ""}],
        "active_remote": "build",
        "projects": [{"name": "prod", "project_dir": "meta-product"}],
        "active_project": "prod",
        "local": {"project_dir": "overlay"},
    }
    profiles.normalize_remote_profiles(config)
    profiles.normalize_project_profiles(config)
    return config


class ConfigEnvBehaviorTests(unittest.TestCase):
    def test_env_default_helpers_read_env_or_default(self) -> None:
        self.assertEqual(config_env.docker_image_from_env({}, "default-image"), "default-image")
        self.assertEqual(
            config_env.docker_image_from_env({"MOULIN_REMOTE_DOCKER_IMAGE": "custom-image"}, "default-image"),
            "custom-image",
        )
        self.assertEqual(config_env.build_targets_from_env({}, "default-target"), "default-target")
        self.assertEqual(
            config_env.build_targets_from_env({"MOULIN_REMOTE_BUILD_TARGETS": "image boot"}, "default-target"),
            "image boot",
        )

    def test_auto_connect_enabled_matches_current_env_policy(self) -> None:
        for value in ("0", "false", "no", "off", " OFF "):
            self.assertFalse(config_env.auto_connect_enabled({"MOULIN_REMOTE_AUTO_CONNECT": value}))
        self.assertTrue(config_env.auto_connect_enabled({}))
        self.assertTrue(config_env.auto_connect_enabled({"MOULIN_REMOTE_AUTO_CONNECT": "yes"}))

    def test_apply_env_overrides_updates_active_remote_and_project(self) -> None:
        config = sample_config()
        config_env.apply_env_overrides(
            config,
            {
                "MOULIN_REMOTE_SSH_USER": "builder",
                "MOULIN_REMOTE_SSH_HOST": "10.0.0.1",
                "MOULIN_REMOTE_PROJECT_DIR": "meta-product",
                "MOULIN_REMOTE_PROJECT_GIT_URL": "git@example:prod",
                "MOULIN_REMOTE_PROJECT_GIT_REF": "mirror",
            },
        )

        self.assertEqual(profiles.active_remote(config)["user"], "builder")
        self.assertEqual(profiles.active_remote(config)["host"], "10.0.0.1")
        self.assertEqual(profiles.active_project(config)["project_dir"], "meta-product")
        self.assertEqual(profiles.active_project(config)["git_url"], "git@example:prod")
        self.assertEqual(profiles.active_project(config)["git_ref"], "mirror")

    def test_apply_env_overrides_ignores_empty_values(self) -> None:
        config = sample_config()
        profiles.active_remote(config)["user"] = "existing"
        profiles.sync_active_remote(config)
        original_user = profiles.active_remote(config).get("user")

        config_env.apply_env_overrides(config, {"MOULIN_REMOTE_SSH_USER": ""})

        self.assertEqual(profiles.active_remote(config).get("user"), original_user)


if __name__ == "__main__":
    unittest.main()
