"""Main screen key handling workflow."""

from __future__ import annotations

import curses
from typing import Any

from components.jobs.api import jobs as job_api
from components.ui.api import dialogs as ui_dialog_api
from components.ui.api import input as ui_input_api
from components.ui.api import menu as ui_menu_api
from components.ui.api import panels as ui_panels_api


class MainKeyController:
    """Handle keyboard actions for the main screen."""

    def handle_key(self, port: Any, ch: int) -> None:
        if port.items:
            port.selected = ui_menu_api.normalize_selection(
                port.selected,
                [port.item_enabled(item) for item in port.items],
            )
        if port.logs_expanded:
            self._handle_expanded_logs_key(port, ch)
            return
        if ch == curses.KEY_LEFT or ui_input_api.key_code_matches(ch, "h"):
            port.focus_panel = "actions"
        elif ch == curses.KEY_RIGHT or ui_input_api.key_code_matches(ch, "l"):
            port.focus_panel = "logs"
        elif ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
            self._move_up(port)
        elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"):
            self._move_down(port)
        elif ch == curses.KEY_MOUSE:
            self._handle_mouse(port)
        elif ch in (curses.KEY_ENTER, 10, 13) or ui_input_api.key_code_matches(ch, "r"):
            port.run_selected()
        elif ui_input_api.key_code_matches(ch, "f"):
            port.focus_before_logs_expanded = port.focus_panel
            port.logs_expanded = True
            port.main_full_redraw = True
            port.render_cache.clear()
        elif ui_input_api.key_code_matches(ch, "s"):
            port.config_workflow_controller().run_project_configurations_screen(port)
            port.main_full_redraw = True
            port.menu_dirty = True
        elif ui_input_api.key_code_matches(ch, "q"):
            port.quit()
        elif ch == 27:
            self._handle_escape(port)
        else:
            port.status = f"Unknown key: {chr(ch)!r}" if 0 <= ch < 256 else f"Unknown key: {ch}"

    def _handle_expanded_logs_key(self, port: Any, ch: int) -> None:
        if ui_input_api.key_code_matches(ch, "f") or ch == 27:
            port.logs_expanded = False
            port.focus_panel = port.focus_before_logs_expanded
            port.main_full_redraw = True
            port.render_cache.clear()
        elif ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
            ui_panels_api.main_panels_controller().scroll_logs(port, -1)
        elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"):
            ui_panels_api.main_panels_controller().scroll_logs(port, 1)
        elif ch in (curses.KEY_PPAGE,):
            ui_panels_api.main_panels_controller().scroll_logs(port, -10)
        elif ch in (curses.KEY_NPAGE,):
            ui_panels_api.main_panels_controller().scroll_logs(port, 10)
        elif ch == curses.KEY_MOUSE:
            self._handle_mouse(port)
        else:
            port.status = "Logs expanded; use f/Esc to return"

    def _handle_mouse(self, port: Any) -> None:
        try:
            _mouse_id, _x, _y, _z, bstate = curses.getmouse()
        except curses.error:
            return
        if bstate & getattr(curses, "BUTTON4_PRESSED", 0):
            self._move_or_scroll(port, -1)
        elif bstate & getattr(curses, "BUTTON5_PRESSED", 0):
            self._move_or_scroll(port, 1)

    def _move_or_scroll(self, port: Any, delta: int) -> None:
        if port.logs_expanded or port.focus_panel == "logs":
            ui_panels_api.main_panels_controller().scroll_logs(port, delta)
            return
        port.selected = ui_menu_api.move_selection(
            port.selected,
            [port.item_enabled(item) for item in port.items],
            delta,
        )
        port.log_follow = True

    def _move_up(self, port: Any) -> None:
        if port.focus_panel == "logs":
            ui_panels_api.main_panels_controller().scroll_logs(port, -1)
            return
        port.selected = ui_menu_api.move_selection(
            port.selected,
            [port.item_enabled(item) for item in port.items],
            -1,
        )
        port.log_follow = True

    def _move_down(self, port: Any) -> None:
        if port.focus_panel == "logs":
            ui_panels_api.main_panels_controller().scroll_logs(port, 1)
            return
        port.selected = ui_menu_api.move_selection(
            port.selected,
            [port.item_enabled(item) for item in port.items],
            1,
        )
        port.log_follow = True

    def _handle_escape(self, port: Any) -> None:
        if job_api.has_active_job(port.active_job, port.board_job):
            port.status = "Command is running; use q after it finishes or open the command screen to stop it"
            return
        if port.dialog_workflow_controller().run_confirm_dialog(port, ui_dialog_api.exit_confirm_content()):
            port.quit()


def main_key_controller() -> MainKeyController:
    return MainKeyController()
