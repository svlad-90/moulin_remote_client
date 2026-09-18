from __future__ import annotations

import unittest

from components.host_config.api import fields


class HostConfigFieldBehaviorTests(unittest.TestCase):
    def test_build_and_board_host_field_lists_match_current_screens(self) -> None:
        self.assertEqual(
            fields.board_host_fields(),
            [
                ("Profile name", "name"),
                ("Display label", "label"),
                ("Board type", "type"),
                ("SSH user", "user"),
                ("SSH host", "host"),
                ("Working dir", "work_dir"),
                ("Console device", "console_device"),
                ("UFS load addr", "ufs_loadaddr"),
                ("UFS buffer size", "ufs_buffersize"),
                ("TFTP root", "tftp_root"),
                ("NFS root", "nfs_root"),
                ("Deploy subdir", "deploy_subdir"),
                ("TFTP server IP", "server_ip"),
                ("Target board IP", "board_ip"),
                ("Direct copy", "direct_copy"),
            ],
        )
        self.assertEqual(
            fields.remote_fields(),
            [
                ("Profile name", "name"),
                ("Display label", "label"),
                ("SSH user", "user"),
                ("SSH host", "host"),
                ("Projects dir", "projects_dir"),
            ],
        )

    def test_host_profile_row_models_match_current_screen_text_and_states(self) -> None:
        profile = {"name": "build-profile-with-long-name", "user": "builder", "host": "10.0.0.1"}

        self.assertEqual(
            fields.host_profile_row_model(profile, active_name="build-profile-with-long-name", selected=True),
            {
                "text": "* build-profile-with builder@10.0.0.1  ACTIVE",
                "state": "selected-active",
                "active": True,
                "selected": True,
            },
        )
        self.assertEqual(
            fields.host_profile_row_model(profile, active_name="other", selected=True)["state"],
            "selected",
        )
        self.assertEqual(
            fields.host_profile_row_model(profile, active_name="build-profile-with-long-name", selected=False)["state"],
            "active",
        )
        self.assertEqual(fields.host_profile_page_scroll(5, 10, 3), 3)
        self.assertEqual(fields.host_profile_page_scroll(0, 2, 5), 0)
        self.assertEqual(fields.host_profile_count_label(1, 4, "build hosts"), "2/4 build hosts")

    def test_host_field_row_model_matches_current_display_policy(self) -> None:
        profile = {"host": "10.0.0.1"}

        self.assertEqual(
            fields.host_field_row_model(
                label="SSH host",
                key="host",
                profile=profile,
                value="10.0.0.1",
                enabled=True,
                selected=True,
                editing=False,
            ),
            {
                "key": "host",
                "label": "SSH host",
                "value": "10.0.0.1",
                "text": "SSH host:           10.0.0.1",
                "state": "selected",
                "enabled": True,
                "selected": True,
                "editing": False,
                "raw": "10.0.0.1",
            },
        )
        self.assertEqual(
            fields.host_field_row_model(
                label="SSH host",
                key="host",
                profile={},
                value="",
                enabled=False,
                selected=True,
                editing=False,
            )["state"],
            "selected-disabled",
        )
        self.assertEqual(
            fields.host_field_row_model(
                label="SSH host",
                key="host",
                profile={},
                value="draft",
                enabled=True,
                selected=True,
                editing=True,
            )["state"],
            "editing",
        )
        self.assertEqual(
            fields.host_field_row_model(
                label="Project dir",
                key="project_dir",
                profile={"project_dir": "meta-product"},
                value="meta-product",
                enabled=True,
                selected=False,
                editing=False,
                label_width=22,
            )["text"],
            "Project dir:          meta-product",
        )

    def test_configuration_screen_key_action_matches_current_focus_policy(self) -> None:
        self.assertEqual(
            fields.configuration_screen_key_action(
                focus="hosts",
                list_focus="hosts",
                selected_exists=True,
                fields_exist=True,
                left=True,
            ),
            {"action": "focus-list", "focus": "hosts"},
        )
        self.assertEqual(
            fields.configuration_screen_key_action(
                focus="hosts",
                list_focus="hosts",
                selected_exists=True,
                fields_exist=True,
                right=True,
            ),
            {"action": "focus-fields"},
        )
        self.assertEqual(
            fields.configuration_screen_key_action(
                focus="hosts",
                list_focus="hosts",
                selected_exists=False,
                fields_exist=False,
                right=True,
            ),
            {"action": "status", "status": "add-first"},
        )
        self.assertEqual(
            fields.configuration_screen_key_action(
                focus="fields",
                list_focus="hosts",
                selected_exists=True,
                fields_exist=True,
                up=True,
            ),
            {"action": "move-field", "delta": -1},
        )
        self.assertEqual(
            fields.configuration_screen_key_action(
                focus="hosts",
                list_focus="hosts",
                selected_exists=True,
                fields_exist=True,
                down=True,
            ),
            {"action": "move-list", "delta": 1},
        )
        self.assertEqual(
            fields.configuration_screen_key_action(
                focus="hosts",
                list_focus="hosts",
                selected_exists=True,
                fields_exist=True,
                enter=True,
            ),
            {"action": "focus-fields"},
        )
        self.assertEqual(
            fields.configuration_screen_key_action(
                focus="fields",
                list_focus="hosts",
                selected_exists=True,
                fields_exist=True,
                enter=True,
            ),
            {"action": "enter-field"},
        )
        self.assertEqual(
            fields.configuration_screen_key_action(
                focus="fields",
                list_focus="hosts",
                selected_exists=True,
                fields_exist=True,
                selected_field_key="direct_copy",
                space=True,
            ),
            {"action": "toggle-field-choice"},
        )
        self.assertEqual(
            fields.configuration_screen_key_action(
                focus="fields",
                list_focus="hosts",
                selected_exists=True,
                fields_exist=True,
                selected_field_key="type",
                space=True,
            ),
            {"action": "toggle-field-choice"},
        )
        self.assertEqual(
            fields.configuration_screen_key_action(
                focus="hosts",
                list_focus="hosts",
                selected_exists=False,
                fields_exist=False,
                delete=True,
            ),
            {"action": "status", "status": "none-selected"},
        )
        self.assertEqual(
            fields.configuration_screen_key_action(
                focus="fields",
                list_focus="remotes",
                selected_exists=True,
                fields_exist=True,
                escape=True,
            ),
            {"action": "focus-list", "focus": "remotes", "status": "list-focused"},
        )
        self.assertEqual(
            fields.configuration_screen_key_action(
                focus="remotes",
                list_focus="remotes",
                selected_exists=True,
                fields_exist=True,
                quit=True,
            ),
            {"action": "quit"},
        )

    def test_board_host_field_policy_matches_current_behavior(self) -> None:
        host = {"user": ""}

        self.assertTrue(fields.board_host_field_enabled("name", host))
        self.assertTrue(fields.board_host_field_enabled("type", host))
        self.assertTrue(fields.board_host_field_enabled("direct_copy", host))
        self.assertFalse(fields.board_host_field_enabled("host", host))
        self.assertEqual(fields.board_host_field_disabled_reason("host", host), "set SSH user first")
        self.assertEqual(fields.board_host_field_disabled_reason("name", host), "")

        host["user"] = "tester"
        self.assertTrue(fields.board_host_field_enabled("host", host))

    def test_board_host_field_hints_preserve_current_text(self) -> None:
        self.assertIn("board host profile", fields.board_host_field_hint("name"))
        self.assertIn("gen5_x5h", fields.board_host_field_hint("type"))
        self.assertIn("auto-detect", fields.board_host_field_hint("console_device"))
        self.assertIn("Enter/Space toggles yes", fields.board_host_field_hint("direct_copy"))
        self.assertEqual(fields.board_host_field_hint("unknown"), "")

    def test_board_host_value_helpers_match_current_behavior(self) -> None:
        self.assertEqual(fields.normalize_board_host_field_value("label", "  Lab board  "), "Lab board")
        self.assertEqual(fields.next_board_type_value(""), "gen5_x5h")
        self.assertEqual(fields.next_board_type_value("unknown"), "gen5_x5h")
        for value in ("1", "true", "yes", "on", " YES "):
            self.assertEqual(fields.normalize_board_host_field_value("direct_copy", value), "yes")
            self.assertEqual(fields.next_direct_copy_value(value), "no")
        for value in ("", "0", "false", "no", "maybe"):
            self.assertEqual(fields.normalize_board_host_field_value("direct_copy", value), "no")
            self.assertEqual(fields.next_direct_copy_value(value), "yes")

    def test_board_host_connection_reset_policy_matches_current_behavior(self) -> None:
        for key in ("user", "host", "work_dir"):
            self.assertTrue(fields.board_host_connection_reset_needed(key, "board", "board"))
        self.assertFalse(fields.board_host_connection_reset_needed("console_device", "board", "board"))
        self.assertFalse(fields.board_host_connection_reset_needed("host", "other", "board"))

    def test_board_host_inline_update_plan_mutates_config_and_reports_reset(self) -> None:
        config = {
            "board_hosts": [
                {"name": "board", "host": "old", "direct_copy": "no"},
                {"name": "other", "host": "other"},
            ],
            "active_board_host": "board",
        }
        board = config["board_hosts"][0]
        other = config["board_hosts"][1]

        plan = fields.apply_board_host_inline_field_update_for_config(config, board, "host", " 10.0.0.2 ")
        self.assertEqual(board["host"], "10.0.0.2")
        self.assertEqual(plan, {"value": "10.0.0.2", "status": "host updated", "connection_reset": True})

        plan = fields.apply_board_host_inline_field_update_for_config(config, board, "direct_copy", "YES")
        self.assertEqual(board["direct_copy"], "yes")
        self.assertEqual(plan, {"value": "yes", "status": "direct_copy updated", "connection_reset": False})

        plan = fields.apply_board_host_inline_field_update_for_config(config, other, "host", "10.0.0.3")
        self.assertEqual(other["host"], "10.0.0.3")
        self.assertFalse(plan["connection_reset"])

    def test_board_host_direct_copy_toggle_mutates_config_and_status(self) -> None:
        config = {
            "board_hosts": [
                {"name": "board", "direct_copy": "no"},
            ],
            "active_board_host": "board",
        }
        board = config["board_hosts"][0]

        plan = fields.apply_board_host_direct_copy_toggle_for_config(config, board)
        self.assertEqual(board["direct_copy"], "yes")
        self.assertEqual(config["board_host"]["direct_copy"], "yes")
        self.assertEqual(plan, {"value": "yes", "status": "Direct copy: yes"})

        plan = fields.apply_board_host_direct_copy_toggle_for_config(config, board)
        self.assertEqual(board["direct_copy"], "no")
        self.assertEqual(config["board_host"]["direct_copy"], "no")
        self.assertEqual(plan, {"value": "no", "status": "Direct copy: no"})

    def test_remote_field_enabled_matches_current_behavior(self) -> None:
        remote = {"name": "build", "user": ""}

        self.assertTrue(fields.remote_field_enabled("back", remote, active_remote="other", connected=False))
        self.assertTrue(fields.remote_field_enabled("projects_dir", remote, active_remote="other", connected=False))
        self.assertFalse(fields.remote_field_enabled("host", remote, active_remote="build", connected=True))
        self.assertFalse(fields.remote_field_enabled("moulin_manifest", remote, active_remote="other", connected=True))
        self.assertFalse(fields.remote_field_enabled("moulin_manifest", remote, active_remote="build", connected=False))

        remote["user"] = "builder"
        self.assertTrue(fields.remote_field_enabled("host", remote, active_remote="build", connected=True))
        self.assertTrue(fields.remote_field_enabled("dockerfile", remote, active_remote="build", connected=True))

    def test_remote_field_disabled_reason_order_matches_current_behavior(self) -> None:
        remote = {"name": "build", "user": "", "host": ""}

        self.assertEqual(
            fields.remote_field_disabled_reason(
                "moulin_manifest",
                remote,
                active_remote="other",
                remote_has_project_dir=False,
            ),
            "set this remote active first",
        )
        self.assertEqual(
            fields.remote_field_disabled_reason(
                "moulin_manifest",
                remote,
                active_remote="build",
                remote_has_project_dir=False,
            ),
            "set SSH user first",
        )
        remote["user"] = "builder"
        self.assertEqual(
            fields.remote_field_disabled_reason(
                "dockerfile",
                remote,
                active_remote="build",
                remote_has_project_dir=False,
            ),
            "set SSH host first",
        )
        remote["host"] = "host"
        self.assertEqual(
            fields.remote_field_disabled_reason(
                "dockerfile",
                remote,
                active_remote="build",
                remote_has_project_dir=False,
            ),
            "set projects dir and project dir first",
        )
        self.assertEqual(
            fields.remote_field_disabled_reason(
                "dockerfile",
                remote,
                active_remote="build",
                remote_has_project_dir=True,
            ),
            "connect to the build host first",
        )

    def test_remote_field_hints_preserve_current_text(self) -> None:
        self.assertIn("profile id", fields.remote_field_hint("name"))
        self.assertIn("browse after connect", fields.remote_field_hint("projects_dir"))
        self.assertEqual(fields.remote_field_hint("unknown"), "")

    def test_remote_value_helpers_match_current_behavior(self) -> None:
        self.assertEqual(fields.normalize_remote_field_value("host", "  10.13.64.194  "), "10.13.64.194")
        for key in ("user", "host", "projects_dir"):
            self.assertTrue(fields.remote_connection_reset_needed(key, "build", "build"))
        self.assertFalse(fields.remote_connection_reset_needed("label", "build", "build"))
        self.assertFalse(fields.remote_connection_reset_needed("host", "other", "build"))

    def test_remote_inline_update_plan_mutates_config_and_reports_reset(self) -> None:
        config = {
            "remotes": [
                {"name": "build", "host": "old"},
                {"name": "other", "host": "other"},
            ],
            "active_remote": "build",
        }
        build = config["remotes"][0]
        other = config["remotes"][1]

        plan = fields.apply_remote_inline_field_update_for_config(config, build, "projects_dir", " /mnt/projects ")
        self.assertEqual(build["projects_dir"], "/mnt/projects")
        self.assertEqual(plan, {"value": "/mnt/projects", "status": "projects_dir updated", "connection_reset": True})

        plan = fields.apply_remote_inline_field_update_for_config(config, build, "label", " Build host ")
        self.assertEqual(build["label"], "Build host")
        self.assertEqual(plan, {"value": "Build host", "status": "label updated", "connection_reset": False})

        plan = fields.apply_remote_inline_field_update_for_config(config, other, "host", "10.0.0.3")
        self.assertEqual(other["host"], "10.0.0.3")
        self.assertFalse(plan["connection_reset"])

    def test_remote_labeled_field_update_preserves_prompt_status_text(self) -> None:
        config = {
            "remotes": [
                {"name": "build", "host": "old"},
            ],
            "active_remote": "build",
        }
        remote = config["remotes"][0]

        plan = fields.apply_remote_labeled_field_update_for_config(config, remote, "host", " 10.0.0.2 ", "SSH host")

        self.assertEqual(remote["host"], "10.0.0.2")
        self.assertEqual(
            plan,
            {
                "value": "10.0.0.2",
                "status": "SSH host updated",
                "connection_reset": True,
            },
        )

    def test_remote_projects_dir_selection_plan_preserves_browse_status(self) -> None:
        config = {
            "remotes": [
                {"name": "build", "projects_dir": "/old"},
            ],
            "active_remote": "build",
        }
        remote = config["remotes"][0]

        plan = fields.apply_remote_projects_dir_selection_for_config(config, remote, "/new/projects")

        self.assertEqual(plan, {"status": "Projects dir: /new/projects"})
        self.assertEqual(remote["projects_dir"], "/new/projects")
        self.assertEqual(config["remote"], remote)

    def test_add_remote_action_policy_matches_current_behavior(self) -> None:
        remotes = [{"name": "build"}]

        self.assertEqual(
            fields.remote_draft_for_config({"remotes": remotes}),
            {"name": "remote-2", "label": "", "user": "", "host": "", "projects_dir": ""},
        )
        self.assertEqual(
            fields.remote_draft_actions(),
            [
                {"label": "Edit profile name", "kind": "name", "description": "Unique local profile id."},
                {"label": "Edit display label", "kind": "label", "description": "Human-readable label shown in the header."},
                {"label": "Edit SSH user", "kind": "user", "description": "Remote SSH user. Required before the profile can be used."},
                {"label": "Edit SSH host", "kind": "host", "description": "Remote SSH host. Required before the profile can be used."},
                {"label": "Create remote", "kind": "create", "description": "Save this profile and make it active."},
                {"label": "Cancel", "kind": "cancel", "description": "Return without saving this profile."},
            ],
        )
        self.assertTrue(fields.add_remote_action_enabled("cancel", {}, remotes))
        self.assertEqual(fields.add_remote_action_disabled_reason("cancel", {}, remotes), "")
        self.assertFalse(fields.add_remote_action_enabled("create", {"name": ""}, remotes))
        self.assertEqual(
            fields.add_remote_action_disabled_reason("create", {"name": ""}, remotes),
            "set profile name first",
        )
        self.assertEqual(
            fields.add_remote_action_disabled_reason("create", {"name": "build"}, remotes),
            "profile name already exists",
        )
        self.assertEqual(
            fields.add_remote_action_disabled_reason("create", {"name": "new", "user": ""}, remotes),
            "set SSH user first",
        )
        self.assertEqual(
            fields.add_remote_action_disabled_reason("create", {"name": "new", "user": "u", "host": ""}, remotes),
            "set SSH host first",
        )
        self.assertTrue(
            fields.add_remote_action_enabled("create", {"name": "new", "user": "u", "host": "h"}, remotes)
        )

    def test_remote_draft_action_model_and_enter_action_match_current_screen_policy(self) -> None:
        config = {"remotes": [{"name": "build"}]}
        draft = {"name": "new", "label": "", "user": "u", "host": "h", "projects_dir": ""}
        actions = fields.remote_draft_actions()

        self.assertEqual(
            fields.remote_draft_action_model(actions[0], draft, config["remotes"]),
            {
                "label": "Edit profile name",
                "kind": "name",
                "description": "Unique local profile id.",
                "enabled": True,
                "disabled_reason": "",
                "text": "Edit profile name: new",
            },
        )
        self.assertEqual(
            fields.remote_draft_action_model(actions[4], {"name": "", "user": "", "host": ""}, config["remotes"])["disabled_reason"],
            "set profile name first",
        )
        self.assertEqual(
            fields.remote_draft_enter_action_for_config(config, draft, actions[0]),
            {"action": "edit", "kind": "name", "label": "profile name"},
        )
        self.assertEqual(
            fields.remote_draft_enter_action_for_config(config, {"name": "", "user": "", "host": ""}, actions[4]),
            {"action": "status", "status": "set profile name first"},
        )
        self.assertEqual(fields.remote_draft_enter_action_for_config(config, draft, actions[4]), {"action": "create"})
        self.assertEqual(
            fields.remote_draft_enter_action_for_config(config, draft, actions[5]),
            {"action": "cancel", "status": "Build host add cancelled"},
        )

    def test_remote_draft_create_plan_matches_current_add_remote_screen_behavior(self) -> None:
        config = {
            "remotes": [{"name": "build", "label": "Build"}],
            "active_remote": "build",
        }

        plan = fields.apply_remote_draft_create_for_config(
            config,
            {
                "name": " new ",
                "label": "",
                "user": " user ",
                "host": " 10.0.0.2 ",
                "projects_dir": "/ignored/by/current/screen",
            },
        )

        self.assertEqual(
            plan,
            {
                "status": "Remote profile added: new",
                "connection_reset": True,
                "preflight_reset": True,
            },
        )
        self.assertEqual(
            config["remotes"][1],
            {
                "name": "new",
                "label": "new",
                "user": "user",
                "host": "10.0.0.2",
                "projects_dir": "",
            },
        )
        self.assertEqual(config["active_remote"], "new")
        self.assertEqual(config["remote"], config["remotes"][1])


if __name__ == "__main__":
    unittest.main()
