from __future__ import annotations

import unittest
from pathlib import Path

from components.config.api import accessors
from components.config.api import profiles


class ConfigAccessorBehaviorTests(unittest.TestCase):
    def test_remote_project_dir_uses_projects_dir_and_project_name(self) -> None:
        remote = {"projects_dir": "/mnt/storage/user/projects"}
        project = {"project_dir": "meta-product"}

        self.assertEqual(accessors.remote_project_dir(remote, project), "/mnt/storage/user/projects/meta-product")

    def test_remote_project_dir_preserves_absolute_project_dir(self) -> None:
        remote = {"projects_dir": "/mnt/storage/user/projects"}
        project = {"project_dir": "/other/root/product/"}

        self.assertEqual(accessors.remote_project_dir(remote, project), "/other/root/product")

    def test_remote_project_dir_falls_back_to_legacy_remote_project_dir(self) -> None:
        remote = {"project_dir": "/legacy/root/product"}
        project = {"project_dir": ""}

        self.assertEqual(accessors.build_host_projects_dir(remote), "/legacy/root")
        self.assertEqual(accessors.remote_project_dir(remote, project), "/legacy/root/product")

    def test_board_accessors_for_config_match_profile_accessors(self) -> None:
        config = {
            "board_hosts": [
                {
                    "name": "board",
                    "label": "Board",
                    "type": "custom",
                    "user": "u",
                    "host": "h",
                    "work_dir": "~/work/",
                    "direct_copy": "yes",
                    "console_device": "/dev/GEN5_CONSOLE",
                    "ufs_loadaddr": "0x50000000",
                    "ufs_buffersize": "0x4000000",
                }
            ],
            "active_board_host": "board",
        }
        profiles.normalize_board_host_profiles(config)
        host = profiles.active_board_host(config)

        self.assertEqual(accessors.board_work_dir_for_config(config), accessors.board_work_dir(host))
        self.assertEqual(accessors.board_type_for_config(config), accessors.board_type(host))
        self.assertEqual(
            accessors.board_artifacts_dir_for_config(config),
            accessors.board_artifacts_dir(accessors.board_work_dir(host)),
        )
        self.assertEqual(accessors.board_direct_copy_enabled_for_config(config), accessors.board_direct_copy_enabled(host))
        self.assertEqual(accessors.board_console_device_for_config(config), accessors.board_console_device(host))
        self.assertEqual(accessors.board_ufs_loadaddr_for_config(config), accessors.board_ufs_loadaddr(host))
        self.assertEqual(accessors.board_ufs_buffersize_for_config(config), accessors.board_ufs_buffersize(host))

    def test_project_and_remote_accessors_for_config_match_profile_accessors(self) -> None:
        config = {
            "remotes": [
                {
                    "name": "build",
                    "label": "Build",
                    "user": "builder",
                    "host": "10.0.0.1",
                    "projects_dir": "/mnt/projects",
                    "git_url": "git@example:fallback",
                    "docker_image": "remote_img",
                    "dockerfile": "remote.Dockerfile",
                    "moulin_manifest": "remote.yaml",
                }
            ],
            "active_remote": "build",
            "projects": [
                {
                    "name": "prod",
                    "label": "Prod",
                    "project_dir": "meta-product",
                    "git_ref": "mirror",
                    "git_url": "",
                    "docker_image": "",
                    "dockerfile": "",
                    "moulin_manifest": "",
                }
            ],
            "active_project": "prod",
        }
        profiles.normalize_remote_profiles(config)
        profiles.normalize_project_profiles(config)
        remote = profiles.active_remote(config)
        project = profiles.active_project(config)

        self.assertEqual(accessors.remote_spec_for_config(config), accessors.host_spec(remote))
        self.assertEqual(accessors.remote_project_dir_for_config(config), accessors.remote_project_dir(remote, project))
        self.assertEqual(accessors.project_git_url_for_config(config), accessors.project_git_url(project, remote))
        self.assertEqual(accessors.project_git_ref_for_config(config), accessors.project_git_ref(project))
        self.assertEqual(
            accessors.configured_docker_image_for_config(config),
            accessors.configured_docker_image(config, project, remote, ""),
        )
        self.assertEqual(
            accessors.configured_dockerfile_for_config(config),
            accessors.configured_dockerfile(config, project, remote, "doc/Dockerfile"),
        )
        self.assertEqual(
            accessors.moulin_manifest_name_for_config(config),
            accessors.moulin_manifest_name(config, project, remote, "product.yaml"),
        )

    def test_remote_project_config_ready_plan_matches_current_status_order(self) -> None:
        config = {
            "remotes": [{"name": "build", "projects_dir": "/projects"}],
            "active_remote": "build",
            "projects": [{"name": "prod", "project_dir": "meta"}],
            "active_project": "prod",
        }
        profiles.normalize_remote_profiles(config)
        profiles.normalize_project_profiles(config)

        self.assertEqual(
            accessors.remote_project_config_ready_plan(config, connected=False),
            {"ready": False, "status": "connect to the build host first"},
        )
        config["projects"][0]["project_dir"] = ""
        self.assertEqual(
            accessors.remote_project_config_ready_plan(config, connected=True),
            {"ready": False, "status": "select remote project directory first"},
        )
        config["projects"][0]["project_dir"] = "meta"
        self.assertEqual(
            accessors.remote_project_config_ready_plan(config, connected=True),
            {"ready": True, "status": ""},
        )

    def test_relative_paths_resolve_against_app_dir(self) -> None:
        config = {
            "inventory": {
                "output": "workspace/inventory.txt",
                "selection": "workspace/selection.txt",
                "mapping_selection": "workspace/selected-mappings.txt",
            },
            "state": {"build_settings": "workspace/build-settings.json"},
            "local": {"project_dir": "workspace/project-overlay"},
        }
        app_dir = Path("/tmp/app")

        self.assertEqual(accessors.config_path(config, "output", app_dir, "inventory"), app_dir / "workspace/inventory.txt")
        self.assertEqual(accessors.inventory_output_path_for_config(config, app_dir), app_dir / "workspace/inventory.txt")
        self.assertEqual(accessors.inventory_selection_path_for_config(config, app_dir), app_dir / "workspace/selection.txt")
        self.assertEqual(accessors.mapping_selection_path_for_config(config, app_dir), app_dir / "workspace/selected-mappings.txt")
        self.assertEqual(
            accessors.config_path(config, "build_settings", app_dir, "state"),
            app_dir / "workspace/build-settings.json",
        )
        self.assertEqual(accessors.local_project_dir(config, {}, app_dir), app_dir / "workspace/project-overlay")


if __name__ == "__main__":
    unittest.main()
