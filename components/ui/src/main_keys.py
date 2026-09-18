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
        self._sync_menu_state(port)
        if port.logs_expanded:
            self._handle_expanded_logs_key(port, ch)
            return
        if ch == curses.KEY_LEFT or ui_input_api.key_code_matches(ch, "h"):
            port.focus_panel = "actions"
            self._move_tab(port, -1)
        elif ch == curses.KEY_RIGHT or ui_input_api.key_code_matches(ch, "l"):
            port.focus_panel = "actions"
            self._move_tab(port, 1)
        elif ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
            self._move_vertical(port, -1)
        elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"):
            self._move_vertical(port, 1)
        elif ch == curses.KEY_MOUSE:
            self._handle_mouse(port)
        elif ch in (curses.KEY_ENTER, 10, 13) and port.focus_panel == "actions" and getattr(port, "menu_focus", "items") == "tabs":
            port.menu_focus = "items"
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

    def _sync_menu_state(self, port: Any) -> None:
        if not hasattr(port, "menu_focus"):
            port.menu_focus = "items"
        if not hasattr(port, "active_menu_tab"):
            port.active_menu_tab = ""
        if not hasattr(port, "menu_tab_selection"):
            port.menu_tab_selection = {}
        if not port.items:
            return
        enabled = [port.item_enabled(item) for item in port.items]
        port.active_menu_tab = ui_menu_api.normalize_active_tab(port.active_menu_tab, port.items, port.selected)
        visible = ui_menu_api.visible_item_indices(port.items, port.active_menu_tab)
        if visible:
            port.selected = ui_menu_api.nearest_visible_selection(port.selected, visible, enabled)

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
        if port.logs_expanded:
            ui_panels_api.main_panels_controller().scroll_logs(port, delta)
            return
        port.focus_panel = "actions"
        if getattr(port, "menu_focus", "items") == "tabs":
            port.menu_focus = "items"
            return
        self._move_items_or_focus_tabs(port, delta)
        port.log_follow = True

    def _move_vertical(self, port: Any, delta: int) -> None:
        port.focus_panel = "actions"
        if getattr(port, "menu_focus", "items") == "tabs":
            port.menu_focus = "items"
        else:
            self._move_items_or_focus_tabs(port, delta)
        port.log_follow = True

    def _move_items_or_focus_tabs(self, port: Any, delta: int) -> None:
        visible = ui_menu_api.visible_item_indices(port.items, getattr(port, "active_menu_tab", ""))
        enabled = [port.item_enabled(item) for item in port.items]
        candidates = [index for index in visible if 0 <= index < len(enabled) and enabled[index]]
        if not candidates:
            port.menu_focus = "tabs"
            return
        if port.selected not in candidates:
            port.selected = candidates[0]
            return
        position = candidates.index(port.selected)
        if delta < 0 and position == 0:
            port.selected = candidates[-1]
            return
        if delta > 0 and position == len(candidates) - 1:
            port.selected = candidates[0]
            return
        port.selected = candidates[position + delta]

    def _move_tab(self, port: Any, delta: int) -> None:
        tabs = ui_menu_api.menu_tabs(port.items)
        if not tabs:
            return
        active = ui_menu_api.normalize_active_tab(getattr(port, "active_menu_tab", ""), port.items, port.selected)
        self._remember_tab_selection(port, active)
        next_tab = tabs[(tabs.index(active) + delta) % len(tabs)]
        port.active_menu_tab = next_tab
        self._select_tab_item(port, next_tab)
        port.menu_scroll = 0

    def _remember_tab_selection(self, port: Any, tab: str) -> None:
        if not hasattr(port, "menu_tab_selection"):
            port.menu_tab_selection = {}
        visible = ui_menu_api.visible_item_indices(port.items, tab)
        if port.selected in visible:
            port.menu_tab_selection[tab] = port.selected

    def _select_tab_item(self, port: Any, tab: str) -> None:
        visible = ui_menu_api.visible_item_indices(port.items, tab)
        enabled = [port.item_enabled(item) for item in port.items]
        remembered = getattr(port, "menu_tab_selection", {}).get(tab)
        if remembered in visible and 0 <= remembered < len(enabled) and enabled[remembered]:
            port.selected = remembered
            return
        enabled_visible = [index for index in visible if 0 <= index < len(enabled) and enabled[index]]
        if enabled_visible:
            port.selected = enabled_visible[0]
        elif visible:
            port.selected = visible[0]

    def _handle_escape(self, port: Any) -> None:
        if job_api.has_active_job(port.active_job, port.board_job):
            port.status = "Command is running; use q after it finishes or open the command screen to stop it"
            return
        if port.dialog_workflow_controller().run_confirm_dialog(port, ui_dialog_api.exit_confirm_content()):
            port.quit()


def main_key_controller() -> MainKeyController:
    return MainKeyController()
