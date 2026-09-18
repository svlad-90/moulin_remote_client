from __future__ import annotations

import curses
import unittest
from typing import Any
from unittest.mock import patch

from components.ui.api import main_keys
from components.ui.api.menu import MenuItem


class FakePanels:
    def __init__(self) -> None:
        self.scrolls: list[int] = []

    def scroll_logs(self, _port: Any, delta: int) -> None:
        self.scrolls.append(delta)


class FakeDialogWorkflow:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.calls = 0

    def run_confirm_dialog(self, _port: Any, _content: Any) -> bool:
        self.calls += 1
        return self.result


class FakeConfigWorkflow:
    def __init__(self) -> None:
        self.project_calls = 0

    def run_project_configurations_screen(self, _port: Any) -> None:
        self.project_calls += 1


class FakePort:
    def __init__(self) -> None:
        self.items = [
            MenuItem("One", "group", "First", lambda _app: "", lambda _app: None),
            MenuItem("Two", "group", "Second", lambda _app: "", lambda _app: None),
        ]
        self.selected = 0
        self.active_menu_tab = ""
        self.menu_focus = "items"
        self.focus_panel = "actions"
        self.focus_before_logs_expanded = "actions"
        self.logs_expanded = False
        self.main_full_redraw = False
        self.render_cache = {"x": "y"}
        self.log_follow = False
        self.status = ""
        self.active_job: dict[str, Any] | None = None
        self.board_job: dict[str, Any] | None = None
        self.run_selected_calls = 0
        self.quit_calls = 0
        self.dialog_workflow = FakeDialogWorkflow(True)
        self.config_workflow = FakeConfigWorkflow()

    def item_enabled(self, _item: MenuItem) -> bool:
        return True

    def run_selected(self) -> None:
        self.run_selected_calls += 1

    def quit(self) -> None:
        self.quit_calls += 1

    def dialog_workflow_controller(self) -> FakeDialogWorkflow:
        return self.dialog_workflow

    def config_workflow_controller(self) -> FakeConfigWorkflow:
        return self.config_workflow


class MainKeyControllerTests(unittest.TestCase):
    def test_down_moves_action_selection_and_enables_log_follow(self) -> None:
        port = FakePort()

        main_keys.main_key_controller().handle_key(port, curses.KEY_DOWN)

        self.assertEqual(port.selected, 1)
        self.assertTrue(port.log_follow)

    def test_up_from_first_item_wraps_to_last_item(self) -> None:
        port = FakePort()
        port.items = [
            MenuItem("Configure", "configuration", "Setup", lambda _app: "", lambda _app: None),
            MenuItem("Edit", "configuration", "Edit setup", lambda _app: "", lambda _app: None),
            MenuItem("Build", "build", "Build", lambda _app: "", lambda _app: None),
            MenuItem("Rebuild", "build", "Rebuild", lambda _app: "", lambda _app: None),
            MenuItem("Flash", "flashing", "Flash", lambda _app: "", lambda _app: None),
        ]

        main_keys.main_key_controller().handle_key(port, curses.KEY_UP)

        self.assertEqual(port.menu_focus, "items")
        self.assertEqual(port.active_menu_tab, "configuration")
        self.assertEqual(port.selected, 1)

    def test_down_from_last_item_wraps_to_first_item(self) -> None:
        port = FakePort()
        port.selected = len(port.items) - 1

        main_keys.main_key_controller().handle_key(port, curses.KEY_DOWN)

        self.assertEqual(port.selected, 0)
        self.assertEqual(port.menu_focus, "items")

    def test_stale_log_focus_moves_action_selection_instead_of_scrolling_logs(self) -> None:
        port = FakePort()
        port.focus_panel = "logs"
        panels = FakePanels()

        with patch("components.ui.src.main_keys.ui_panels_api.main_panels_controller", return_value=panels):
            main_keys.main_key_controller().handle_key(port, curses.KEY_DOWN)

        self.assertEqual(port.focus_panel, "actions")
        self.assertEqual(port.selected, 1)
        self.assertEqual(panels.scrolls, [])

    def test_left_right_switch_tabs_and_restore_last_tab_selection(self) -> None:
        port = FakePort()
        port.items = [
            MenuItem("Configure", "configuration", "Setup", lambda _app: "", lambda _app: None),
            MenuItem("Edit", "configuration", "Edit setup", lambda _app: "", lambda _app: None),
            MenuItem("Build", "build", "Build", lambda _app: "", lambda _app: None),
            MenuItem("Rebuild", "build", "Rebuild", lambda _app: "", lambda _app: None),
        ]
        port.active_menu_tab = "configuration"
        port.selected = 1

        controller = main_keys.main_key_controller()
        controller.handle_key(port, curses.KEY_RIGHT)
        self.assertEqual(port.active_menu_tab, "build")
        self.assertEqual(port.selected, 2)

        controller.handle_key(port, curses.KEY_DOWN)
        self.assertEqual(port.selected, 3)

        controller.handle_key(port, curses.KEY_LEFT)
        self.assertEqual(port.focus_panel, "actions")
        self.assertEqual(port.active_menu_tab, "configuration")
        self.assertEqual(port.selected, 1)

    def test_mouse_wheel_moves_action_selection_one_item(self) -> None:
        port = FakePort()
        button_down = getattr(curses, "BUTTON5_PRESSED", 0x200000)

        with patch("components.ui.src.main_keys.curses.getmouse", return_value=(0, 0, 0, 0, button_down)):
            main_keys.main_key_controller().handle_key(port, curses.KEY_MOUSE)

        self.assertEqual(port.selected, 1)
        self.assertTrue(port.log_follow)

    def test_mouse_wheel_does_not_scroll_collapsed_logs_when_logs_were_focused(self) -> None:
        port = FakePort()
        port.focus_panel = "logs"
        panels = FakePanels()
        button_down = getattr(curses, "BUTTON5_PRESSED", 0x200000)

        with (
            patch("components.ui.src.main_keys.curses.getmouse", return_value=(0, 0, 0, 0, button_down)),
            patch("components.ui.src.main_keys.ui_panels_api.main_panels_controller", return_value=panels),
        ):
            main_keys.main_key_controller().handle_key(port, curses.KEY_MOUSE)

        self.assertEqual(port.focus_panel, "actions")
        self.assertEqual(port.selected, 1)
        self.assertEqual(panels.scrolls, [])

    def test_expanded_logs_escape_restores_previous_focus_and_clears_cache(self) -> None:
        port = FakePort()
        port.logs_expanded = True
        port.focus_before_logs_expanded = "logs"

        main_keys.main_key_controller().handle_key(port, 27)

        self.assertFalse(port.logs_expanded)
        self.assertEqual(port.focus_panel, "logs")
        self.assertTrue(port.main_full_redraw)
        self.assertEqual(port.render_cache, {})

    def test_settings_hotkey_runs_project_configuration_screen(self) -> None:
        port = FakePort()

        main_keys.main_key_controller().handle_key(port, ord("s"))

        self.assertEqual(port.config_workflow.project_calls, 1)
        self.assertTrue(port.main_full_redraw)
        self.assertTrue(port.menu_dirty)

    def test_escape_with_active_job_does_not_open_exit_confirm(self) -> None:
        port = FakePort()
        port.active_job = {"process": object()}

        main_keys.main_key_controller().handle_key(port, 27)

        self.assertEqual(port.dialog_workflow.calls, 0)
        self.assertEqual(port.quit_calls, 0)
        self.assertIn("Command is running", port.status)

    def test_escape_without_active_job_uses_exit_confirm(self) -> None:
        port = FakePort()

        main_keys.main_key_controller().handle_key(port, 27)

        self.assertEqual(port.dialog_workflow.calls, 1)
        self.assertEqual(port.quit_calls, 1)


if __name__ == "__main__":
    unittest.main()
