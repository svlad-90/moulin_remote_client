from __future__ import annotations

import unittest

import moulin_remote_client as client
from components.ui.api import menu
from components.ui.api.menu import MenuItem


def _item_enabled(item: MenuItem, **overrides: object) -> bool:
    values = {
        "active_job": None,
        "board_job": None,
        "board_host_has_ssh": True,
        "board_connected": True,
        "build_connected": True,
        "remote_has_ssh": True,
        "remote_has_project_dir": True,
        "prepare_remote_project_needed": False,
        "checkout_git_ref_needed": False,
    }
    values.update(overrides)
    return menu.item_enabled(item, **values)


def _disabled_reason(item: MenuItem, **overrides: object) -> str:
    values = {
        "active_job": None,
        "board_job": None,
        "board_host_user": "board",
        "board_host_host": "host",
        "board_connected": True,
        "build_connected": True,
        "remote_has_user": True,
        "remote_has_host": True,
        "remote_has_project_dir": True,
        "prepare_remote_project_needed": False,
        "checkout_git_ref_needed": False,
    }
    values.update(overrides)
    return menu.disabled_reason(item, **values)


class MenuModelBehaviorTests(unittest.TestCase):
    def test_menu_item_defaults_match_client_contract(self) -> None:
        item = MenuItem(
            "Open",
            "setup",
            "Open setup.",
            lambda app: "preview",
            lambda app: None,
        )

        self.assertIsInstance(item, client.MenuItem)
        self.assertFalse(item.confirm)
        self.assertFalse(item.requires_remote)
        self.assertFalse(item.requires_ssh)
        self.assertFalse(item.requires_project)
        self.assertFalse(item.allow_during_job)
        self.assertEqual(item.preview(None), "preview")

    def test_menu_item_flags_are_preserved(self) -> None:
        item = MenuItem(
            "Run",
            "commands",
            "Run command.",
            lambda app: "preview",
            lambda app: None,
            confirm=True,
            requires_remote=True,
            requires_ssh=True,
            requires_project=True,
            allow_during_job=True,
        )

        self.assertTrue(item.confirm)
        self.assertTrue(item.requires_remote)
        self.assertTrue(item.requires_ssh)
        self.assertTrue(item.requires_project)
        self.assertTrue(item.allow_during_job)

    def test_item_job_slot_matches_current_menu_group_policy(self) -> None:
        self.assertEqual(menu.item_job_slot(MenuItem("Run product build", "build commands", "", lambda app: "", lambda app: None)), "build")
        self.assertEqual(menu.item_job_slot(MenuItem("Analyze Yocto", "build commands / yocto incremental build", "", lambda app: "", lambda app: None)), "build")
        self.assertEqual(menu.item_job_slot(MenuItem("Sync mapped files", "sync", "", lambda app: "", lambda app: None)), "build")
        self.assertEqual(menu.item_job_slot(MenuItem("Connect build host", "build host session", "", lambda app: "", lambda app: None)), "build")
        self.assertEqual(menu.item_job_slot(MenuItem("Flash UFS image", "board commands", "", lambda app: "", lambda app: None)), "board")
        self.assertEqual(menu.item_job_slot(MenuItem("Connect board host", "board host session", "", lambda app: "", lambda app: None)), "board")
        self.assertIsNone(menu.item_job_slot(MenuItem("Open local NFS workspace", "tftp/nfs / open local workspaces", "", lambda app: "", lambda app: None)))
        self.assertIsNone(menu.item_job_slot(MenuItem("Open board serial console", "flashing / board host", "", lambda app: "", lambda app: None)))
        self.assertIsNone(menu.item_job_slot(MenuItem("Open U-Boot console", "flashing / board host", "", lambda app: "", lambda app: None)))
        self.assertIsNone(menu.item_job_slot(MenuItem("Open remote TFTP root", "tftp/nfs / open remote roots", "", lambda app: "", lambda app: None)))
        self.assertIsNone(menu.item_job_slot(MenuItem("Project configuration", "setup", "", lambda app: "", lambda app: None)))

    def test_job_lookup_helpers_match_current_shape(self) -> None:
        active = {"item_label": "Run product build"}
        board = {"item_label": "Flash UFS image"}
        item = MenuItem("Flash UFS image", "board commands", "", lambda app: "", lambda app: None)

        self.assertIs(menu.job_for_item(item, [active, board]), board)
        self.assertIs(menu.active_job_for_slot("build", active_job=active, board_job=board), active)
        self.assertIs(menu.active_job_for_slot("board", active_job=active, board_job=board), board)
        self.assertIsNone(menu.active_job_for_slot(None, active_job=active, board_job=board))
        self.assertIs(
            menu.display_job_for_item(item, active_job=active, board_job=board, last_board_job=None, last_job=None),
            board,
        )
        self.assertEqual(
            menu.display_job_for_item(
                MenuItem("Regenerate Moulin/Ninja", "build commands", "", lambda app: "", lambda app: None),
                active_job=active,
                board_job=board,
                last_board_job=None,
                last_job=active,
                last_jobs_by_label={"Regenerate Moulin/Ninja": {"item_label": "Regenerate Moulin/Ninja"}},
            )["item_label"],
            "Regenerate Moulin/Ninja",
        )
        self.assertIs(
            menu.display_job_for_item(item, active_job=None, board_job=None, last_board_job=board, last_job=active),
            board,
        )
        self.assertIsNone(
            menu.display_job_for_item(
                MenuItem("Other", "board commands", "", lambda app: "", lambda app: None),
                active_job=None,
                board_job=None,
                last_board_job=board,
                last_job=active,
            )
        )

    def test_menu_rows_and_scroll_match_current_draw_policy(self) -> None:
        items = [
            MenuItem("Remote configurations", "setup", "", lambda app: "", lambda app: None),
            MenuItem("Connect build host", "build host session", "", lambda app: "", lambda app: None),
            MenuItem("Run product build", "build commands", "", lambda app: "", lambda app: None),
        ]

        rows = menu.menu_rows(items, ["Remote configurations", "Disconnect build host", "Run product build"])

        self.assertEqual(
            rows,
            [
                ("SETUP", None),
                ("1. Remote configurations", 0),
                ("", None),
                ("BUILD HOST SESSION", None),
                ("2. Disconnect build host", 1),
                ("", None),
                ("BUILD COMMANDS", None),
                ("3. Run product build", 2),
            ],
        )
        self.assertEqual(menu.selected_menu_row(rows, 2), 7)
        self.assertEqual(menu.clamp_menu_scroll(rows, selected=2, scroll=0, visible_rows=4), 4)

    def test_menu_rows_render_slash_groups_as_subgroups(self) -> None:
        items = [
            MenuItem("Run product build", "build commands", "", lambda app: "", lambda app: None),
            MenuItem("Clean impacted Yocto recipes + run product build", "build commands / yocto incremental build", "", lambda app: "", lambda app: None),
        ]

        rows = menu.menu_rows(items, ["Run product build", "Clean impacted Yocto recipes + run product build"])

        self.assertEqual(
            rows,
            [
                ("BUILD COMMANDS", None),
                ("1. Run product build", 0),
                ("", None),
                ("YOCTO INCREMENTAL BUILD", None),
                ("2. Clean impacted Yocto recipes + run product build", 1),
            ],
        )

    def test_wrapped_menu_rows_indent_continuation_under_item_text(self) -> None:
        rows = [
            ("YOCTO INCREMENTAL BUILD", None),
            ("10. Clean impacted Yocto recipes + run product build", 9),
        ]

        wrapped = menu.wrapped_menu_rows(rows, 30)

        self.assertEqual(
            wrapped,
            [
                ("YOCTO INCREMENTAL BUILD", None),
                ("10. Clean impacted Yocto", 9),
                ("    recipes + run product", 9),
                ("    build", 9),
            ],
        )
        self.assertEqual(menu.selected_menu_row(wrapped, 9), 1)

    def test_menu_rows_separate_subgroup_when_returning_to_parent_group(self) -> None:
        items = [
            MenuItem("Run product build", "build commands", "", lambda app: "", lambda app: None),
            MenuItem("Clean impacted Yocto recipes + run product build", "build commands / yocto incremental build", "", lambda app: "", lambda app: None),
            MenuItem("Stop running command", "build commands", "", lambda app: "", lambda app: None),
        ]

        rows = menu.menu_rows(items, ["Run product build", "Clean impacted Yocto recipes + run product build", "Stop running command"])

        self.assertEqual(
            rows,
            [
                ("BUILD COMMANDS", None),
                ("1. Run product build", 0),
                ("", None),
                ("YOCTO INCREMENTAL BUILD", None),
                ("2. Clean impacted Yocto recipes + run product build", 1),
                ("", None),
                ("3. Stop running command", 2),
            ],
        )
        self.assertEqual(menu.clamp_menu_scroll(rows, selected=0, scroll=3, visible_rows=4), 1)
        self.assertEqual(menu.clamp_menu_scroll(rows, selected=1, scroll=3, visible_rows=4), 3)

    def test_menu_tabs_filter_visible_items_with_local_display_numbers(self) -> None:
        items = [
            MenuItem("Build host configuration", "configuration", "", lambda app: "", lambda app: None),
            MenuItem("Run product build", "build", "", lambda app: "", lambda app: None),
            MenuItem("Open board host shell", "sessions / board host", "", lambda app: "", lambda app: None),
            MenuItem("Flash UFS image", "flashing", "", lambda app: "", lambda app: None),
            MenuItem("Deploy full TFTP/NFS set", "tftp/nfs", "", lambda app: "", lambda app: None),
        ]

        self.assertEqual(menu.menu_tabs(items), ["configuration", "sessions", "build", "flashing", "tftp/nfs"])
        self.assertEqual(menu.visible_item_indices(items, "tftp/nfs"), [4])
        self.assertEqual(menu.normalize_active_tab("", items, selected=3), "flashing")
        rows = menu.menu_rows_for_indices(items, [item.label for item in items], [4])

        self.assertEqual(rows, [("TFTP/NFS", None), ("1. Deploy full TFTP/NFS set", 4)])

    def test_build_tab_rows_render_command_and_mapping_subgroups(self) -> None:
        items = [
            MenuItem("Copy mapped files to build host", "build / files mapping", "", lambda app: "", lambda app: None),
            MenuItem("Build Docker image", "build / commands", "", lambda app: "", lambda app: None),
            MenuItem("Sync mapped files", "build / files mapping", "", lambda app: "", lambda app: None),
        ]

        rows = menu.menu_rows_for_indices(items, [item.label for item in items], [1, 0, 2])

        self.assertEqual(
            rows,
            [
                ("COMMANDS", None),
                ("1. Build Docker image", 1),
                ("", None),
                ("FILES MAPPING", None),
                ("2. Copy mapped files to build host", 0),
                ("3. Sync mapped files", 2),
            ],
        )

    def test_command_preview_matches_current_menu_preview_shape(self) -> None:
        self.assertEqual(menu.command_preview([]), "no commands")
        self.assertEqual(
            menu.command_preview(
                [
                    ["ssh", "host", "echo hello"],
                    ["bash", "-lc", "two words"],
                    ["python3", "tool.py"],
                    ["ignored"],
                ]
            ),
            "ssh host 'echo hello'\nbash -lc 'two words'\npython3 tool.py",
        )

    def test_selected_action_guard_matches_current_run_selected_prechecks(self) -> None:
        item = MenuItem("Run product build", "build commands", "", lambda app: "", lambda app: None)

        self.assertEqual(
            menu.selected_action_guard(
                item,
                action_running=True,
                item_running=False,
                enabled=True,
                disabled_status="disabled",
            ),
            {"allowed": False, "status": "Another interactive action is already running"},
        )
        self.assertEqual(
            menu.selected_action_guard(
                MenuItem(
                    "Open board host shell",
                    "sessions / board host",
                    "",
                    lambda app: "",
                    lambda app: None,
                    allow_during_job=True,
                ),
                action_running=True,
                item_running=False,
                enabled=True,
                disabled_status="disabled",
            ),
            {"allowed": True, "status": ""},
        )
        self.assertEqual(
            menu.selected_action_guard(
                item,
                action_running=False,
                item_running=True,
                enabled=True,
                disabled_status="disabled",
            ),
            {"allowed": False, "status": "Command is already running; live log is shown in Logs"},
        )
        self.assertEqual(
            menu.selected_action_guard(
                item,
                action_running=False,
                item_running=False,
                enabled=False,
                disabled_status="connect to the build host first",
            ),
            {"allowed": False, "status": "connect to the build host first"},
        )
        self.assertEqual(
            menu.selected_action_guard(
                item,
                action_running=False,
                item_running=False,
                enabled=True,
                disabled_status="disabled",
            ),
            {"allowed": True, "status": ""},
        )

    def test_selection_helpers_match_current_navigation_policy(self) -> None:
        self.assertEqual(menu.clamp_index(3, 0), 0)
        self.assertEqual(menu.clamp_index(-2, 5), 0)
        self.assertEqual(menu.clamp_index(9, 5), 4)
        self.assertEqual(menu.clamp_index(2, 5), 2)

        self.assertEqual(menu.move_index(0, 0, 1), 0)
        self.assertEqual(menu.move_index(0, 3, -1), 2)
        self.assertEqual(menu.move_index(2, 3, 1), 0)
        self.assertEqual(menu.move_index(1, 3, 1), 2)

        self.assertEqual(menu.list_scroll(index=0, count=10, visible=4), 0)
        self.assertEqual(menu.list_scroll(index=3, count=10, visible=4), 0)
        self.assertEqual(menu.list_scroll(index=4, count=10, visible=4), 1)
        self.assertEqual(menu.list_scroll(index=9, count=10, visible=4), 6)
        self.assertEqual(menu.list_scroll(index=9, count=3, visible=10), 0)

        self.assertEqual(menu.move_selection(0, [], 1), 0)
        self.assertEqual(menu.move_selection(0, [False, True, False], 1), 1)
        self.assertEqual(menu.move_selection(2, [True, False, True], 1), 0)
        self.assertEqual(menu.move_selection(1, [False, False, False], 1), 2)
        self.assertEqual(menu.move_selection(0, [False, False, False], -1), 2)

        self.assertEqual(menu.nearest_enabled_selection(2, []), 0)
        self.assertEqual(menu.nearest_enabled_selection(2, [False, True, False, True]), 3)
        self.assertEqual(menu.nearest_enabled_selection(2, [False, True, False, False]), 1)
        self.assertEqual(menu.nearest_enabled_selection(1, [False, False]), 1)

        self.assertEqual(menu.normalize_selection(8, [False, True, True]), 2)
        self.assertEqual(menu.normalize_selection(-3, [False, True, True]), 1)
        self.assertEqual(menu.normalize_selection(1, [False, False, False]), 1)

    def test_sync_menu_selection_preserves_label_and_normalizes_enabled_item(self) -> None:
        old_items = [
            MenuItem("Remote configurations", "setup", "", lambda app: "", lambda app: None),
            MenuItem("Run product build", "build commands", "", lambda app: "", lambda app: None),
        ]
        new_items = [
            MenuItem("Connect build host", "build host session", "", lambda app: "", lambda app: None),
            MenuItem("Run product build", "build commands", "", lambda app: "", lambda app: None),
            MenuItem("Stop running command", "build commands", "", lambda app: "", lambda app: None),
        ]

        self.assertEqual(menu.sync_menu_selection(old_items, 1, new_items, [True, True, True]), 1)
        self.assertEqual(menu.sync_menu_selection(old_items, 99, new_items, [True, True, True]), 1)
        self.assertEqual(menu.sync_menu_selection(old_items, 0, [], []), 0)
        self.assertEqual(menu.sync_menu_selection(old_items, 1, new_items, [True, False, True]), 2)

    def test_item_enabled_preserves_command_gating_order(self) -> None:
        copy_item = MenuItem("Copy build artifacts", "board commands", "", lambda app: "", lambda app: None, requires_remote=True, requires_project=True)
        build_item = MenuItem("Run product build", "build commands", "", lambda app: "", lambda app: None, requires_remote=True, requires_project=True)
        stop_item = MenuItem("Stop running command", "build commands", "", lambda app: "", lambda app: None)
        active_job = {"item_label": "Regenerate Moulin/Ninja"}
        connect_job = {"item_label": "Connect build host", "kind": "connect"}

        self.assertFalse(_item_enabled(stop_item, active_job=None))
        self.assertFalse(_item_enabled(stop_item, active_job=connect_job))
        self.assertTrue(_item_enabled(stop_item, active_job=active_job))
        self.assertFalse(_item_enabled(build_item, active_job=active_job))
        self.assertFalse(_item_enabled(copy_item, board_connected=False))
        self.assertFalse(_item_enabled(copy_item, build_connected=False))
        self.assertTrue(_item_enabled(copy_item))
        local_workspace_item = MenuItem("Open local NFS workspace", "tftp/nfs / open local workspaces", "", lambda app: "", lambda app: None, requires_project=True)
        board_serial_item = MenuItem("Open board serial console", "flashing / board host", "", lambda app: "", lambda app: None, allow_during_job=True)
        build_directory_item = MenuItem("Open build directory", "build / workspace", "", lambda app: "", lambda app: None, requires_remote=True, requires_project=True, allow_during_job=True)
        self.assertTrue(_item_enabled(local_workspace_item, board_connected=False))
        self.assertTrue(_item_enabled(board_serial_item, board_job={"item_label": "Flash UFS image"}))
        self.assertTrue(_item_enabled(build_directory_item, active_job={"item_label": "Run product build"}))

    def test_item_enabled_stops_only_stoppable_board_commands(self) -> None:
        stop_item = MenuItem("Stop current board command", "board commands", "", lambda app: "", lambda app: None)
        board_connect_job = {"item_label": "Connect board host", "kind": "board-connect"}
        board_command_job = {"item_label": "Flash UFS image"}

        self.assertFalse(_item_enabled(stop_item, board_job=None))
        self.assertFalse(_item_enabled(stop_item, board_job=board_connect_job))
        self.assertTrue(_item_enabled(stop_item, board_job=board_command_job))

    def test_disabled_reason_preserves_current_messages(self) -> None:
        copy_item = MenuItem("Copy build artifacts", "board commands", "", lambda app: "", lambda app: None, requires_remote=True, requires_project=True)
        build_item = MenuItem("Run product build", "build commands", "", lambda app: "", lambda app: None, requires_remote=True, requires_project=True)
        board_shell = MenuItem("Open board host shell", "board host session", "", lambda app: "", lambda app: None)

        self.assertEqual(
            menu.disabled_reason(copy_item, active_job=None, board_job=None, board_host_user="", board_host_host="", board_connected=False, build_connected=False, remote_has_user=False, remote_has_host=False, remote_has_project_dir=False, prepare_remote_project_needed=False, checkout_git_ref_needed=False),
            "set board SSH user first",
        )
        self.assertEqual(
            _disabled_reason(copy_item, board_host_host="", board_connected=False, build_connected=False, remote_has_user=False, remote_has_host=False, remote_has_project_dir=False),
            "set board SSH host first",
        )
        self.assertEqual(
            _disabled_reason(copy_item, board_connected=False, build_connected=False, remote_has_user=False, remote_has_host=False, remote_has_project_dir=False),
            "connect to the board host first",
        )
        self.assertEqual(
            _disabled_reason(copy_item, build_connected=False),
            "connect to the build host first",
        )
        self.assertEqual(
            _disabled_reason(board_shell, board_connected=False),
            "connect to the board host first",
        )
        self.assertEqual(
            _disabled_reason(build_item, prepare_remote_project_needed=True),
            "remote project needs preparation",
        )

    def test_disabled_reason_treats_connect_jobs_as_no_stoppable_command(self) -> None:
        build_stop = MenuItem("Stop running command", "build commands", "", lambda app: "", lambda app: None)
        board_stop = MenuItem("Stop current board command", "board commands", "", lambda app: "", lambda app: None)

        self.assertEqual(
            _disabled_reason(build_stop, active_job={"item_label": "Connect build host", "kind": "connect"}),
            "no build or sync command is running",
        )
        self.assertEqual(
            _disabled_reason(board_stop, board_job={"item_label": "Connect board host", "kind": "board-connect"}),
            "no board command is running",
        )

    def test_selected_action_plan_reports_disabled_item(self) -> None:
        item = MenuItem("Run product build", "build commands", "", lambda app: "", lambda app: None)

        plan = menu.selected_action_plan(
            item,
            [],
            action_running=False,
            enabled_for_item=lambda _item: False,
            disabled_reason_for_item=lambda _item: "connect to the build host first",
        )

        self.assertFalse(plan["item_running"])
        self.assertFalse(plan["enabled"])
        self.assertEqual(plan["disabled_status"], "connect to the build host first")
        self.assertEqual(plan["guard"], {"allowed": False, "status": "connect to the build host first"})

    def test_selected_action_plan_reports_running_item_without_enabled_check(self) -> None:
        item = MenuItem("Run product build", "build commands", "", lambda app: "", lambda app: None)

        plan = menu.selected_action_plan(
            item,
            [{"item_label": "Run product build"}],
            action_running=False,
            enabled_for_item=lambda _item: (_ for _ in ()).throw(AssertionError("enabled check should not run")),
            disabled_reason_for_item=lambda _item: "disabled",
        )

        self.assertTrue(plan["item_running"])
        self.assertTrue(plan["enabled"])
        self.assertEqual(plan["guard"], {"allowed": False, "status": "Command is already running; live log is shown in Logs"})


if __name__ == "__main__":
    unittest.main()
