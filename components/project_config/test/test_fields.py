from __future__ import annotations

import unittest

from components.project_config.api import fields


class ProjectConfigFieldBehaviorTests(unittest.TestCase):
    def test_project_profile_row_model_matches_current_screen_text_and_states(self) -> None:
        project = {
            "name": "gen5-product-profile",
            "moulin_manifest": "prod-devel-rcar-gen5.yaml",
            "targets": "boot_artifacts full_ufs.img.gz",
        }

        self.assertEqual(
            fields.project_profile_row_model(project, active_name="gen5-product-profile", selected=True),
            {
                "text": "* gen5-product-profi prod-devel-rcar-gen5.yaml      boot_artifacts full_ufs.img.gz  ACTIVE",
                "state": "selected-active",
                "active": True,
                "selected": True,
            },
        )
        self.assertEqual(
            fields.project_profile_row_model(project, active_name="other", selected=True)["state"],
            "selected",
        )
        self.assertEqual(
            fields.project_profile_row_model(project, active_name="gen5-product-profile", selected=False)["state"],
            "active",
        )

    def test_project_field_value_uses_param_defaults_and_overrides(self) -> None:
        project = {"name": "prod", "parameters": {"ENABLE_ANDROID": "yes"}, "project_dir": "meta"}
        param_field = {"kind": "param", "key": "param:ENABLE_ANDROID", "param": {"default": "no"}}
        fallback_param = {"kind": "param", "key": "param:ENABLE_DOMU", "param": {"default": "no"}}

        self.assertTrue(fields.project_is_active(project, "prod"))
        self.assertFalse(fields.project_is_active(project, "other"))
        self.assertEqual(fields.project_field_value(project, param_field), "yes")
        self.assertEqual(fields.project_field_value(project, fallback_param), "no")
        self.assertEqual(fields.project_field_value(project, {"kind": "text", "key": "project_dir"}), "meta")

    def test_active_project_file_selection_plan_preserves_status_and_side_effect_flags(self) -> None:
        config = {
            "projects": [{"name": "prod", "moulin_manifest": "old.yaml", "dockerfile": "old/Dockerfile"}],
            "active_project": "prod",
        }

        self.assertEqual(
            fields.apply_active_project_file_selection_for_config(config, "moulin_manifest", "product.yaml"),
            {
                "status": "Moulin manifest: product.yaml",
                "manifest_cache_reset": True,
                "build_params_reload": True,
                "preflight_reset": True,
            },
        )
        self.assertEqual(config["project"]["moulin_manifest"], "product.yaml")
        self.assertEqual(
            fields.apply_active_project_file_selection_for_config(config, "dockerfile", "doc/Dockerfile"),
            {
                "status": "Dockerfile: doc/Dockerfile",
                "manifest_cache_reset": False,
                "build_params_reload": False,
                "preflight_reset": True,
            },
        )
        self.assertEqual(config["project"]["dockerfile"], "doc/Dockerfile")

    def test_active_project_settings_field_plan_preserves_current_side_effects(self) -> None:
        config = {
            "projects": [{"name": "prod", "local_project_dir": "old", "git_url": "old", "docker_image": "old"}],
            "active_project": "prod",
        }

        self.assertEqual(
            fields.apply_active_project_settings_field_for_config(config, "local_project_dir", " overlay "),
            {"value": "overlay", "preflight_reset": False, "docker_image": None},
        )
        self.assertEqual(config["project"]["local_project_dir"], "overlay")
        self.assertEqual(
            fields.apply_active_project_settings_field_for_config(config, "git_url", " https://example/repo "),
            {"value": "https://example/repo", "preflight_reset": True, "docker_image": None},
        )
        self.assertEqual(config["project"]["git_url"], "https://example/repo")
        self.assertEqual(
            fields.apply_active_project_settings_field_for_config(config, "docker_image", " image "),
            {"value": "image", "preflight_reset": False, "docker_image": "image"},
        )
        self.assertEqual(config["project"]["docker_image"], "image")

    def test_project_field_update_helpers_match_current_behavior(self) -> None:
        self.assertEqual(fields.normalize_project_field_value("git_ref", "  mirror  "), "mirror")
        self.assertEqual(fields.project_dir_field_update("project_dir", "/mnt/storage/proj/"), ("proj", "/mnt/storage"))
        self.assertEqual(fields.project_dir_field_update("project_dir", "proj"), ("proj", ""))
        self.assertEqual(fields.project_dir_field_update("git_url", "/mnt/storage/proj"), ("/mnt/storage/proj", ""))

        for key in ("project_dir", "docker_image", "board_artifacts"):
            self.assertTrue(fields.project_runtime_reload_needed(key))
        self.assertFalse(fields.project_runtime_reload_needed("local_project_dir"))
        self.assertFalse(fields.project_runtime_reload_needed("git_ref"))

        for key in ("project_dir", "git_url", "git_ref"):
            self.assertTrue(fields.project_preflight_reset_needed(key))
        self.assertFalse(fields.project_preflight_reset_needed("docker_image"))

        self.assertTrue(fields.project_docker_image_update_needed("docker_image"))
        self.assertFalse(fields.project_docker_image_update_needed("project_dir"))

    def test_project_inline_update_plan_mutates_config_and_reports_side_effects(self) -> None:
        config = {
            "remote": {"name": "build", "projects_dir": ""},
            "remotes": [{"name": "build", "projects_dir": ""}],
            "active_remote": "build",
            "projects": [
                {"name": "active", "project_dir": "old", "docker_image": "old-image"},
                {"name": "other", "project_dir": "other", "docker_image": "other-image"},
            ],
            "active_project": "active",
        }
        active = config["projects"][0]
        other = config["projects"][1]

        plan = fields.apply_project_inline_field_update_for_config(
            config,
            active,
            "project_dir",
            " /mnt/storage/meta-prod ",
        )

        self.assertEqual(active["project_dir"], "meta-prod")
        self.assertEqual(config["remote"]["projects_dir"], "/mnt/storage")
        self.assertEqual(
            plan,
            {
                "value": "meta-prod",
                "status": "project_dir updated",
                "runtime_reload": True,
                "preflight_reset": True,
                "docker_image": None,
            },
        )

        plan = fields.apply_project_inline_field_update_for_config(config, active, "docker_image", " image ")
        self.assertEqual(active["docker_image"], "image")
        self.assertEqual(plan["docker_image"], "image")
        self.assertTrue(plan["runtime_reload"])
        self.assertFalse(plan["preflight_reset"])

        plan = fields.apply_project_inline_field_update_for_config(config, other, "git_ref", "mirror")
        self.assertEqual(other["git_ref"], "mirror")
        self.assertFalse(plan["runtime_reload"])
        self.assertFalse(plan["preflight_reset"])
        self.assertIsNone(plan["docker_image"])

    def test_project_field_enabled_matches_current_behavior(self) -> None:
        project = {"name": "prod"}
        base = {
            "project": project,
            "active_project": "prod",
            "connected": True,
            "remote_has_ssh": True,
            "remote_has_project_dir": True,
        }

        self.assertTrue(fields.project_field_enabled({"kind": "text"}, **base))
        self.assertTrue(fields.project_field_enabled({"kind": "git_ref"}, **base))
        self.assertTrue(fields.project_field_enabled({"kind": "param"}, **base))
        self.assertTrue(fields.project_field_enabled({"kind": "targets"}, **base))
        self.assertTrue(fields.project_field_enabled({"kind": "board_artifacts"}, **base))
        self.assertTrue(fields.project_field_enabled({"kind": "remote_dir"}, **base))
        self.assertTrue(fields.project_field_enabled({"kind": "manifest"}, **base))
        self.assertFalse(fields.project_field_enabled({"kind": "manifest"}, **{**base, "connected": False}))
        self.assertFalse(fields.project_field_enabled({"kind": "remote_dir"}, **{**base, "remote_has_ssh": False}))
        self.assertFalse(fields.project_field_enabled({"kind": "manifest"}, **{**base, "remote_has_project_dir": False}))
        self.assertFalse(fields.project_field_enabled({"kind": "param"}, **{**base, "active_project": "other"}))

    def test_project_field_disabled_reason_order_matches_current_behavior(self) -> None:
        project = {"name": "prod"}
        field = {"kind": "manifest"}

        self.assertEqual(
            fields.project_field_disabled_reason(
                field,
                project,
                active_project="other",
                remote_has_user=True,
                remote_has_host=True,
                remote_has_project_dir=True,
            ),
            "set this project active first",
        )
        self.assertEqual(
            fields.project_field_disabled_reason(
                field,
                project,
                active_project="prod",
                remote_has_user=False,
                remote_has_host=False,
                remote_has_project_dir=False,
            ),
            "set SSH user first",
        )
        self.assertEqual(
            fields.project_field_disabled_reason(
                field,
                project,
                active_project="prod",
                remote_has_user=True,
                remote_has_host=False,
                remote_has_project_dir=False,
            ),
            "set SSH host first",
        )
        self.assertEqual(
            fields.project_field_disabled_reason(
                field,
                project,
                active_project="prod",
                remote_has_user=True,
                remote_has_host=True,
                remote_has_project_dir=False,
            ),
            "select remote project directory first",
        )
        self.assertEqual(
            fields.project_field_disabled_reason(
                {"kind": "remote_dir"},
                project,
                active_project="prod",
                remote_has_user=True,
                remote_has_host=True,
                remote_has_project_dir=False,
            ),
            "connect to the build host first",
        )

    def test_project_field_enter_action_matches_current_screen_dispatch(self) -> None:
        config = {
            "remote": {"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"},
            "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
            "active_remote": "build",
            "projects": [{"name": "prod", "project_dir": "meta-prod", "docker_image": "img"}],
            "active_project": "prod",
        }
        project = config["projects"][0]

        self.assertEqual(
            fields.project_field_enter_action_for_config(
                {"kind": "manifest", "key": "moulin_manifest"},
                project,
                config,
                connected=False,
            ),
            {"action": "status", "status": "connect to the build host first"},
        )
        cases = [
            ({"kind": "manifest", "key": "moulin_manifest"}, {"action": "select-moulin-manifest"}),
            ({"kind": "dockerfile", "key": "dockerfile"}, {"action": "select-dockerfile"}),
            ({"kind": "remote_dir", "key": "project_dir"}, {"action": "edit-project-remote-dir"}),
            ({"kind": "git_ref", "key": "git_ref"}, {"action": "edit-project-git-ref"}),
            ({"kind": "targets", "key": "targets"}, {"action": "select-build-targets"}),
            ({"kind": "board_artifacts", "key": "board_artifacts"}, {"action": "select-board-artifacts"}),
            (
                {"kind": "param", "key": "param:ENABLE_ANDROID", "param": {"name": "ENABLE_ANDROID"}},
                {"action": "cycle-parameter", "param": {"name": "ENABLE_ANDROID"}},
            ),
            (
                {"kind": "text", "key": "project_dir", "label": "Project dir"},
                {"action": "edit-text", "key": "project_dir", "value": "meta-prod", "label": "Project dir"},
            ),
        ]
        for field, expected in cases:
            self.assertEqual(
                fields.project_field_enter_action_for_config(field, project, config, connected=True),
                expected,
            )

    def test_project_field_hints_preserve_current_text(self) -> None:
        self.assertIn(
            "Projects dir (/mnt/projects)",
            fields.project_field_hint({"kind": "text", "key": "project_dir"}, build_host_projects_dir="/mnt/projects", app_dir="/app"),
        )
        self.assertIn(
            "Relative paths are resolved from /app",
            fields.project_field_hint({"kind": "text", "key": "local_project_dir"}, build_host_projects_dir="", app_dir="/app"),
        )
        self.assertEqual(
            fields.project_field_hint(
                {"kind": "param", "key": "param:ENABLE_ANDROID", "param": {"desc": "Android"}},
                build_host_projects_dir="",
                app_dir="/app",
            ),
            "Android",
        )

    def test_settings_action_label_and_description_preserve_current_text(self) -> None:
        context = {
            "active_project": {"name": "prod", "label": "Prod"},
            "build_params": {"ENABLE_ANDROID": "yes"},
            "local_project_dir": "/overlay",
            "moulin_manifest_name": "prod.yaml",
            "project_git_url": "",
            "configured_dockerfile": "doc/Dockerfile",
            "build_targets": "boot full",
            "board_artifacts": "",
            "docker_image": "prod-img",
        }

        self.assertEqual(fields.settings_action_label({"kind": "select_project"}, **context), "Active project: Prod")
        self.assertEqual(
            fields.settings_action_label(
                {"kind": "param", "param": {"name": "ENABLE_ANDROID", "default": "no", "choices": ["no", "yes"]}},
                **context,
            ),
            "Edit ENABLE_ANDROID: yes (no/yes)",
        )
        self.assertEqual(fields.settings_action_label({"kind": "git_url"}, **context), "Edit project Git URL: <not set>")
        self.assertEqual(fields.settings_action_label({"kind": "board_artifacts"}, **context), "Select board artifacts: boot full")
        self.assertIn("Moulin parameter", fields.settings_action_description({"kind": "param", "param": {}}))
        self.assertIn("Dockerfiles", fields.settings_action_description({"kind": "dockerfile"}))

    def test_ordered_targets_preserves_current_selection_order(self) -> None:
        candidates = [
            {"target": "boot", "source": "manifest", "desc": ""},
            {"target": "full", "source": "manifest", "desc": ""},
            {"target": "extra", "source": "override", "desc": ""},
        ]

        self.assertEqual(
            fields.ordered_targets(candidates, {"boot", "extra"}, "extra old boot"),
            ["extra", "boot"],
        )
        self.assertEqual(
            fields.ordered_targets(candidates, {"boot", "full", "extra"}, "boot"),
            ["boot", "full", "extra"],
        )

    def test_target_selection_model_preserves_current_behavior(self) -> None:
        candidates = [
            {"target": "boot", "source": "manifest", "desc": ""},
            {"target": "full image", "source": "manifest", "desc": ""},
            {"target": "extra", "source": "override", "desc": ""},
        ]

        selected = fields.selected_targets_from_text("extra 'full image'")
        actions = fields.target_actions(candidates)

        self.assertEqual(selected, {"extra", "full image"})
        self.assertEqual(actions, [{"kind": "target", "candidate": candidate} for candidate in candidates])
        self.assertEqual(
            fields.target_text_for_selection(
                candidates,
                selected,
                current_text="extra boot 'full image'",
                default_text="boot",
            ),
            "extra full image",
        )
        self.assertEqual(
            fields.target_display_text(
                candidates,
                set(),
                current_text="",
                default_text="boot",
            ),
            "none",
        )

        selected, status = fields.toggle_target_selection(actions[0], selected)
        self.assertEqual(selected, {"boot", "extra", "full image"})
        self.assertEqual(status, "boot: selected")

        selected, status = fields.toggle_target_selection(actions[0], selected)
        self.assertEqual(selected, {"extra", "full image"})
        self.assertEqual(status, "boot: removed")

    def test_build_target_action_text_preserves_current_shape(self) -> None:
        action = {"kind": "target", "candidate": {"target": "boot", "source": "manifest", "desc": ""}}
        desc_action = {"kind": "target", "candidate": {"target": "full", "source": "manifest", "desc": "Full image"}}

        self.assertEqual(fields.build_target_action_label(action, {"boot"}), "[x] boot (manifest)")
        self.assertEqual(fields.build_target_action_label(action, set()), "[ ] boot (manifest)")
        self.assertEqual(fields.build_target_action_label({"kind": "save"}, set()), "save")
        self.assertEqual(fields.build_target_action_description(action), "Toggle Ninja target boot.")
        self.assertEqual(fields.build_target_action_description(desc_action), "Full image")
        self.assertEqual(fields.build_target_action_description({"kind": "save"}), "")

    def test_next_parameter_value_cycles_choices(self) -> None:
        param = {"name": "ENABLE_ANDROID", "default": "no", "choices": ["no", "yes"]}

        self.assertEqual(fields.next_parameter_value(param, "no"), "yes")
        self.assertEqual(fields.next_parameter_value(param, "yes"), "no")
        self.assertEqual(fields.next_parameter_value(param, "unexpected"), "no")
        self.assertIsNone(fields.next_parameter_value({"choices": []}, "no"))


if __name__ == "__main__":
    unittest.main()
