from __future__ import annotations

import unittest

from components.config.api import profiles


class ConfigProfileBehaviorTests(unittest.TestCase):
    def test_legacy_remote_project_dir_splits_into_projects_dir_and_project_name(self) -> None:
        config = {
            "remote": {
                "name": "build",
                "label": "Build",
                "user": "builder",
                "host": "10.0.0.1",
                "project_dir": "/mnt/storage/user/projects/meta-product",
            },
            "local": {"project_dir": "workspace/project-overlay"},
        }

        profiles.normalize_remote_profiles(config)
        profiles.normalize_project_profiles(
            config,
            default_build_targets="",
            default_moulin_manifest="product.yaml",
            default_dockerfile="doc/Dockerfile",
        )

        self.assertEqual(profiles.active_remote(config)["projects_dir"], "/mnt/storage/user/projects")
        self.assertEqual(profiles.active_project(config)["project_dir"], "meta-product")
        self.assertEqual(config["project"], profiles.active_project(config))

    def test_board_host_defaults_from_active_remote_when_legacy_board_host_missing(self) -> None:
        config = {
            "remotes": [{"name": "build", "label": "Build", "user": "builder", "host": "10.0.0.1"}],
            "active_remote": "build",
        }

        profiles.normalize_board_host_profiles(config)

        self.assertEqual(
            profiles.active_board_host(config),
            {
                "name": "build",
                "label": "Build",
                "user": "builder",
                "host": "10.0.0.1",
                "work_dir": "~/moulin-board-work",
                "direct_copy": "no",
                "console_device": "",
                "ufs_loadaddr": "",
                "ufs_buffersize": "",
            },
        )

    def test_existing_project_profiles_get_defaults_and_copy_legacy_mappings(self) -> None:
        config = {
            "projects": [{"name": "p", "label": "P", "project_dir": "/remote/root/product", "parameters": "bad"}],
            "active_project": "missing",
            "mappings": [{"name": "layer", "remote": "layers/meta", "local": "layers/meta"}],
            "remote": {"name": "build", "user": "u", "host": "h"},
            "local": {"project_dir": "overlay"},
            "moulin": {"manifest": "prod.yaml"},
            "docker": {"dockerfile": "Dockerfile", "image": "img"},
        }

        profiles.normalize_remote_profiles(config)
        profiles.normalize_project_profiles(
            config,
            default_build_targets="",
            default_moulin_manifest="product.yaml",
            default_dockerfile="doc/Dockerfile",
        )

        project = profiles.active_project(config)
        self.assertEqual(config["active_project"], "p")
        self.assertEqual(project["project_dir"], "product")
        self.assertEqual(project["local_project_dir"], "overlay")
        self.assertEqual(project["moulin_manifest"], "prod.yaml")
        self.assertEqual(project["dockerfile"], "Dockerfile")
        self.assertEqual(project["docker_image"], "img")
        self.assertEqual(project["parameters"], {})
        self.assertEqual(project["mappings"], [{"name": "layer", "remote": "layers/meta", "local": "layers/meta"}])
        self.assertIsNot(project["mappings"], config["mappings"])

    def test_profile_component_defaults_for_new_config(self) -> None:
        config = {
            "remote": {"name": "build", "label": "Build", "user": "u", "host": "h"},
            "project": {"project_dir": "/projects/meta-product", "git_url": "git@example:repo"},
            "local": {"project_dir": "overlay"},
            "docker": {"dockerfile": "doc/Dockerfile", "image": "img"},
        }

        profiles.normalize_remote_profiles(config)
        profiles.normalize_board_host_profiles(config)
        profiles.normalize_project_profiles(
            config,
            default_build_targets="",
            default_moulin_manifest="product.yaml",
            default_dockerfile="doc/Dockerfile",
        )

        project = profiles.active_project(config)
        self.assertEqual(project["name"], "default")
        self.assertEqual(project["project_dir"], "meta-product")
        self.assertEqual(project["git_url"], "git@example:repo")
        self.assertEqual(project["local_project_dir"], "overlay")
        self.assertEqual(project["dockerfile"], "doc/Dockerfile")
        self.assertEqual(project["docker_image"], "img")

    def test_split_remote_project_path_matches_current_behavior(self) -> None:
        self.assertEqual(profiles.split_remote_project_path("/a/b/project/"), ("/a/b", "project"))
        self.assertEqual(profiles.split_remote_project_path("project"), ("", "project"))

    def test_active_profile_index_returns_matching_index_or_zero(self) -> None:
        items = [{"name": "one"}, {"name": "two"}]

        self.assertEqual(profiles.active_profile_index(items, "two"), 1)
        self.assertEqual(profiles.active_profile_index(items, "missing"), 0)
        self.assertEqual(profiles.active_profile_index([], "missing"), 0)
        self.assertEqual(profiles.first_profile_name(items), "one")
        self.assertEqual(profiles.first_profile_name([]), "")
        self.assertEqual(profiles.first_profile_name([{"label": "No name"}]), "")

    def test_project_picker_helpers_match_current_screen_rows(self) -> None:
        config = {"projects": [{"name": "one", "label": "One"}, "bad", {"name": "two"}]}

        self.assertEqual(profiles.project_profiles_for_config(config), [{"name": "one", "label": "One"}, {"name": "two"}])
        self.assertEqual(
            profiles.project_picker_row_model({"name": "one", "label": "One"}, active_project="one"),
            {"text": "* One", "active": True},
        )
        self.assertEqual(
            profiles.project_picker_row_model({"name": "two"}, active_project="one"),
            {"text": "  two", "active": False},
        )

    def test_profile_rename_helpers_match_current_behavior(self) -> None:
        self.assertEqual(profiles.profile_label_after_rename("", "old", "new"), "new")
        self.assertEqual(profiles.profile_label_after_rename("old", "old", "new"), "new")
        self.assertEqual(profiles.profile_label_after_rename("Custom", "old", "new"), "Custom")
        self.assertEqual(profiles.active_profile_name_after_rename("old", "old", "new"), "new")
        self.assertEqual(profiles.active_profile_name_after_rename("other", "old", "new"), "other")

    def test_next_profile_name_preserves_current_gap_behavior(self) -> None:
        items = [{"name": "remote-1"}, {"name": "custom"}, {"name": "remote-3"}]

        self.assertEqual(profiles.next_remote_name(items), "remote-4")
        self.assertEqual(profiles.next_board_host_name([{"name": "board-1"}]), "board-2")

    def test_remote_profile_mutations_preserve_current_behavior(self) -> None:
        config = {
            "remotes": [
                {"name": "one", "label": "One"},
                {"name": "two", "label": "Two"},
            ],
            "active_remote": "two",
        }

        created = profiles.add_remote_profile(config, "three")
        self.assertEqual(created["name"], "three")
        self.assertEqual(config["active_remote"], "two")
        self.assertTrue(profiles.set_active_remote_profile(config, "three"))
        self.assertFalse(profiles.set_active_remote_profile(config, "three"))
        self.assertEqual(profiles.active_remote(config)["name"], "three")

        with self.assertRaisesRegex(ValueError, "already exists"):
            profiles.add_remote_profile(config, "three")

        self.assertTrue(profiles.delete_remote_profile(config, "three"))
        self.assertEqual(config["active_remote"], "one")
        self.assertEqual(profiles.active_remote(config)["name"], "one")
        self.assertFalse(profiles.delete_remote_profile(config, "missing"))

    def test_add_host_profile_plans_preserve_current_status(self) -> None:
        config = {
            "remotes": [{"name": "one", "label": "One"}],
            "active_remote": "one",
            "board_hosts": [{"name": "board", "label": "Board"}],
            "active_board_host": "board",
        }

        self.assertEqual(
            profiles.apply_add_remote_profile_for_config(config, " two "),
            {"status": "Build host profile added: two"},
        )
        self.assertEqual(config["remotes"][1]["name"], "two")
        self.assertEqual(config["active_remote"], "one")

        self.assertEqual(
            profiles.apply_add_board_host_profile_for_config(config, " lab "),
            {"status": "Board host profile added: lab"},
        )
        self.assertEqual(config["board_hosts"][1]["name"], "lab")
        self.assertEqual(config["active_board_host"], "board")

    def test_remote_profile_field_update_renames_active_and_preserves_custom_label(self) -> None:
        config = {
            "remotes": [
                {"name": "build", "label": "Custom"},
                {"name": "other", "label": "Other"},
            ],
            "active_remote": "build",
        }
        remote = config["remotes"][0]

        profiles.update_remote_profile_field(config, remote, "name", "renamed")
        self.assertEqual(remote["name"], "renamed")
        self.assertEqual(remote["label"], "Custom")
        self.assertEqual(config["active_remote"], "renamed")
        self.assertEqual(profiles.active_remote(config), remote)

        profiles.update_remote_profile_field(config, remote, "host", "10.0.0.1")
        self.assertEqual(remote["host"], "10.0.0.1")
        self.assertEqual(config["remote"], remote)

        with self.assertRaisesRegex(ValueError, "already exists"):
            profiles.update_remote_profile_field(config, remote, "name", "other")

    def test_remote_profile_field_update_relabels_default_label(self) -> None:
        config = {"remotes": [{"name": "build", "label": "build"}], "active_remote": "build"}
        remote = config["remotes"][0]

        profiles.update_remote_profile_field(config, remote, "name", "renamed")

        self.assertEqual(remote["label"], "renamed")

    def test_board_host_profile_mutations_preserve_current_behavior(self) -> None:
        config = {
            "board_hosts": [
                {"name": "one", "label": "One"},
                {"name": "two", "label": "Two"},
            ],
            "active_board_host": "one",
        }

        created = profiles.add_board_host_profile(config, "three")
        self.assertEqual(created["name"], "three")
        self.assertEqual(config["active_board_host"], "one")
        self.assertTrue(profiles.set_active_board_host_profile(config, "two"))
        self.assertFalse(profiles.set_active_board_host_profile(config, "two"))
        self.assertEqual(profiles.active_board_host(config)["name"], "two")

        with self.assertRaisesRegex(ValueError, "already exists"):
            profiles.add_board_host_profile(config, "three")

        self.assertTrue(profiles.delete_board_host_profile(config, "two"))
        self.assertEqual(config["active_board_host"], "one")
        self.assertEqual(profiles.active_board_host(config)["name"], "one")
        self.assertFalse(profiles.delete_board_host_profile(config, "missing"))

    def test_board_host_profile_field_update_renames_active_and_preserves_custom_label(self) -> None:
        config = {
            "board_hosts": [
                {"name": "board", "label": "Custom"},
                {"name": "other", "label": "Other"},
            ],
            "active_board_host": "board",
        }
        host = config["board_hosts"][0]

        profiles.update_board_host_profile_field(config, host, "name", "renamed")
        self.assertEqual(host["name"], "renamed")
        self.assertEqual(host["label"], "Custom")
        self.assertEqual(config["active_board_host"], "renamed")
        self.assertEqual(profiles.active_board_host(config), host)

        profiles.update_board_host_profile_field(config, host, "work_dir", "/srv/tftp/vgon")
        self.assertEqual(host["work_dir"], "/srv/tftp/vgon")
        self.assertEqual(config["board_host"], host)

        with self.assertRaisesRegex(ValueError, "already exists"):
            profiles.update_board_host_profile_field(config, host, "name", "other")

    def test_board_host_profile_field_update_relabels_default_label(self) -> None:
        config = {"board_hosts": [{"name": "board", "label": "board"}], "active_board_host": "board"}
        host = config["board_hosts"][0]

        profiles.update_board_host_profile_field(config, host, "name", "renamed")

        self.assertEqual(host["label"], "renamed")

    def test_active_host_profile_plans_preserve_current_status_and_reset_policy(self) -> None:
        config = {
            "remotes": [{"name": "build"}, {"name": "other"}],
            "active_remote": "build",
            "board_hosts": [{"name": "board"}, {"name": "lab"}],
            "active_board_host": "board",
        }

        self.assertEqual(
            profiles.apply_active_remote_profile_for_config(config, config["remotes"][0]),
            {
                "changed": False,
                "status": "selected build host is already active",
                "connection_reset": False,
                "preflight_reset": False,
            },
        )
        self.assertEqual(
            profiles.apply_active_remote_profile_for_config(config, config["remotes"][1]),
            {
                "changed": True,
                "status": "Active build host: other",
                "connection_reset": True,
                "preflight_reset": True,
            },
        )
        self.assertEqual(config["active_remote"], "other")

        self.assertEqual(
            profiles.apply_active_board_host_profile_for_config(config, config["board_hosts"][0]),
            {
                "changed": False,
                "status": "selected board host is already active",
                "connection_reset": False,
            },
        )
        self.assertEqual(
            profiles.apply_active_board_host_profile_for_config(config, config["board_hosts"][1]),
            {
                "changed": True,
                "status": "Active board host: lab",
                "connection_reset": True,
            },
        )
        self.assertEqual(config["active_board_host"], "lab")

    def test_delete_host_profile_plans_preserve_current_status_and_reset_policy(self) -> None:
        config = {
            "remotes": [{"name": "build"}, {"name": "other"}],
            "active_remote": "build",
            "board_hosts": [{"name": "board"}, {"name": "lab"}],
            "active_board_host": "board",
        }

        self.assertEqual(
            profiles.apply_delete_remote_profile_for_config(config, config["remotes"][1]),
            {
                "status": "Build host profile deleted: other",
                "connection_reset": False,
                "preflight_reset": False,
            },
        )
        self.assertEqual(config["active_remote"], "build")
        self.assertEqual(
            profiles.apply_delete_remote_profile_for_config(config, config["remotes"][0]),
            {
                "status": "Build host profile deleted: build",
                "connection_reset": True,
                "preflight_reset": True,
            },
        )

        self.assertEqual(
            profiles.apply_delete_board_host_profile_for_config(config, config["board_hosts"][1]),
            {
                "status": "Board host profile deleted: lab",
                "connection_reset": False,
            },
        )
        self.assertEqual(config["active_board_host"], "board")
        self.assertEqual(
            profiles.apply_delete_board_host_profile_for_config(config, config["board_hosts"][0]),
            {
                "status": "Board host profile deleted: board",
                "connection_reset": True,
            },
        )

    def test_project_profile_mutations_preserve_current_behavior(self) -> None:
        config = {
            "remote": {"name": "build", "label": "Build", "projects_dir": "/projects"},
            "remotes": [{"name": "build", "label": "Build", "projects_dir": "/projects"}],
            "active_remote": "build",
            "projects": [
                {
                    "name": "one",
                    "label": "One",
                    "project_dir": "meta-one",
                    "local_project_dir": "overlay",
                    "parameters": {"A": "1"},
                    "targets": "old-target",
                    "board_artifacts": "old-artifact",
                    "docker_image": "old-image",
                },
                {"name": "two", "label": "Two", "project_dir": "meta-two"},
            ],
            "active_project": "one",
        }

        created = profiles.add_project_profile_from_current(
            config,
            "three",
            parameters={"B": "2"},
            targets="target",
            board_artifacts="artifact",
            docker_image="image",
        )
        self.assertEqual(created["name"], "three")
        self.assertEqual(created["project_dir"], "meta-one")
        self.assertEqual(created["parameters"], {"B": "2"})
        self.assertEqual(config["active_project"], "three")
        self.assertEqual(config["docker"]["image"], "image")
        self.assertTrue(profiles.can_delete_project_profile(config))

        self.assertTrue(profiles.set_active_project_profile(config, "two"))
        self.assertFalse(profiles.set_active_project_profile(config, "two"))
        self.assertEqual(profiles.active_project(config)["name"], "two")

        self.assertTrue(profiles.delete_project_profile(config, "two"))
        self.assertEqual(config["active_project"], "one")
        self.assertEqual(profiles.active_project(config)["name"], "one")
        self.assertFalse(profiles.delete_project_profile(config, "missing"))

        with self.assertRaisesRegex(ValueError, "already exists"):
            profiles.add_project_profile_from_current(
                config,
                "one",
                parameters={},
                targets="",
                board_artifacts="",
                docker_image="",
            )

    def test_add_project_profile_plan_preserves_status_and_reload_policy(self) -> None:
        config = {
            "remote": {"name": "build", "label": "Build", "projects_dir": "/projects"},
            "remotes": [{"name": "build", "label": "Build", "projects_dir": "/projects"}],
            "active_remote": "build",
            "projects": [
                {
                    "name": "one",
                    "label": "One",
                    "project_dir": "meta-one",
                    "parameters": {"A": "1"},
                },
            ],
            "active_project": "one",
        }

        plan = profiles.apply_add_project_profile_for_config(
            config,
            " two ",
            parameters={"B": "2"},
            targets="target",
            board_artifacts="artifact",
            docker_image="image",
        )

        self.assertEqual(plan, {"status": "Project added: two", "runtime_reload": True})
        self.assertEqual(config["projects"][1]["name"], "two")
        self.assertEqual(config["active_project"], "two")
        self.assertEqual(config["docker"]["image"], "image")

    def test_project_profile_field_update_renames_active_and_updates_remote_projects_dir(self) -> None:
        config = {
            "remote": {"name": "build", "label": "Build", "projects_dir": ""},
            "remotes": [{"name": "build", "label": "Build", "projects_dir": ""}],
            "active_remote": "build",
            "projects": [
                {"name": "project", "label": "project", "project_dir": "old"},
                {"name": "other", "label": "Other", "project_dir": "other-dir"},
            ],
            "active_project": "project",
        }
        project = config["projects"][0]

        profiles.update_project_profile_field(config, project, "name", "renamed")
        self.assertEqual(project["name"], "renamed")
        self.assertEqual(project["label"], "renamed")
        self.assertEqual(config["active_project"], "renamed")
        self.assertEqual(profiles.active_project(config), project)

        profiles.update_project_profile_field(
            config,
            project,
            "project_dir",
            "meta-product",
            projects_dir="/mnt/storage/user/projects",
        )
        self.assertEqual(project["project_dir"], "meta-product")
        self.assertEqual(profiles.active_remote(config)["projects_dir"], "/mnt/storage/user/projects")
        self.assertEqual(config["project"], project)

        with self.assertRaisesRegex(ValueError, "already exists"):
            profiles.update_project_profile_field(config, project, "name", "other")

    def test_active_project_profile_plan_preserves_status_and_reload_policy(self) -> None:
        config = {
            "projects": [
                {"name": "one", "label": "One"},
                {"name": "two", "label": "Two"},
            ],
            "active_project": "one",
        }

        self.assertEqual(
            profiles.apply_active_project_profile_for_config(config, config["projects"][0]),
            {
                "changed": False,
                "status": "selected project is already active",
                "runtime_reload": False,
                "preflight_reset": False,
            },
        )
        self.assertEqual(
            profiles.apply_active_project_profile_for_config(config, config["projects"][1]),
            {
                "changed": True,
                "status": "Active project: Two",
                "runtime_reload": True,
                "preflight_reset": True,
            },
        )
        self.assertEqual(config["active_project"], "two")

    def test_project_picker_selection_plan_preserves_current_screen_behavior(self) -> None:
        config = {
            "projects": [
                {"name": "one", "label": "One"},
                {"name": "two", "label": "Two"},
            ],
            "active_project": "one",
        }

        self.assertEqual(
            profiles.apply_project_picker_selection_for_config(config, config["projects"][0]),
            {"status": "Active project: One", "runtime_reload": True, "save": True},
        )
        self.assertEqual(config["active_project"], "one")
        self.assertEqual(
            profiles.apply_project_picker_selection_for_config(config, config["projects"][1]),
            {"status": "Active project: Two", "runtime_reload": True, "save": True},
        )
        self.assertEqual(config["active_project"], "two")

    def test_delete_project_profile_plan_preserves_status_and_reload_policy(self) -> None:
        config = {
            "projects": [
                {"name": "one", "label": "One"},
                {"name": "two", "label": "Two"},
                {"name": "three", "label": "Three"},
            ],
            "active_project": "one",
        }

        self.assertEqual(
            profiles.apply_delete_project_profile_for_config(config, config["projects"][1]),
            {
                "status": "Project deleted: two",
                "runtime_reload": False,
                "preflight_reset": False,
            },
        )
        self.assertEqual(config["active_project"], "one")
        self.assertEqual(
            profiles.apply_delete_project_profile_for_config(config, config["projects"][0]),
            {
                "status": "Project deleted: one",
                "runtime_reload": True,
                "preflight_reset": True,
            },
        )
        self.assertEqual(config["active_project"], "three")

    def test_project_profile_delete_rejects_single_project(self) -> None:
        config = {"projects": [{"name": "only"}], "active_project": "only"}

        self.assertFalse(profiles.can_delete_project_profile(config))
        with self.assertRaisesRegex(ValueError, "Cannot delete"):
            profiles.delete_project_profile(config, "only")

    def test_active_project_target_helpers_sync_legacy_project_view(self) -> None:
        config = {
            "projects": [{"name": "prod", "targets": "old", "board_artifacts": "old-artifact"}],
            "active_project": "prod",
        }

        profiles.set_active_project_targets(config, "image boot")
        profiles.set_active_project_board_artifacts(config, "boot_artifacts full_ufs.img.gz")

        self.assertEqual(profiles.active_project(config)["targets"], "image boot")
        self.assertEqual(profiles.active_project(config)["board_artifacts"], "boot_artifacts full_ufs.img.gz")
        self.assertEqual(config["project"], profiles.active_project(config))

    def test_active_project_target_plans_preserve_status_and_reload_policy(self) -> None:
        config = {
            "projects": [{"name": "prod", "targets": "old", "board_artifacts": "old-artifact"}],
            "active_project": "prod",
        }

        self.assertEqual(
            profiles.apply_active_project_targets_for_config(config, "image boot"),
            {"status": "Build target selection saved", "runtime_reload": True},
        )
        self.assertEqual(profiles.active_project(config)["targets"], "image boot")
        self.assertEqual(
            profiles.apply_active_project_board_artifacts_for_config(config, "boot_artifacts full_ufs.img.gz"),
            {"status": "Board artifact selection saved", "runtime_reload": True},
        )
        self.assertEqual(profiles.active_project(config)["board_artifacts"], "boot_artifacts full_ufs.img.gz")


if __name__ == "__main__":
    unittest.main()
