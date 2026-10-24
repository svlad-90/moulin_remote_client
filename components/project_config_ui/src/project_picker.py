"""Project picker screen controller."""

from __future__ import annotations

import curses
from typing import Any, Callable

from components.config.api import profiles as config_profile_api
from components.ui.api import input as ui_input_api
from components.ui.api import menu as ui_menu_api


class ProjectPickerController:
    """Select the active project profile from a focused picker screen."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        profile_action_controller: Any,
    ) -> None:
        self.config = config
        self.profile_action_controller = profile_action_controller

    def select_project(self, port: Any, *, reload_runtime: Callable[[], None]) -> None:
        projects = self._projects()
        index = config_profile_api.active_profile_index(projects, str(self.config.get("active_project", "")))
        port.screen.timeout(-1)
        while True:
            port.screen.erase()
            height, width = port.screen.getmaxyx()
            if height < 12 or width < 70:
                port.add(0, 0, "Terminal is too small. Need at least 70x12.", port.warn_attr())
                port.screen.refresh()
                ch = port.read_key()
                if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                    return
                continue
            port.draw_box(0, 0, height - 2, width, "Projects")
            visible = max(1, height - 5)
            index = ui_menu_api.clamp_index(index, len(projects))
            scroll = ui_menu_api.list_scroll(index, len(projects), visible)
            for offset, project in enumerate(projects[scroll : scroll + visible]):
                item_index = scroll + offset
                row_model = config_profile_api.project_picker_row_model(
                    project,
                    active_project=str(self.config.get("active_project", "")),
                )
                attr = port.selected_attr() if item_index == index else 0
                port.add(1 + offset, 2, str(row_model["text"])[: width - 4].ljust(width - 4), attr)
            footer = "Up/Down: select | Enter: set active | q/Esc: back"
            port.add(height - 2, 0, footer[:width], port.accent_attr())
            port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
            port.screen.refresh()
            ch = port.read_key()
            if (ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k")) and projects:
                index = ui_menu_api.move_index(index, len(projects), -1)
            elif (ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j")) and projects:
                index = ui_menu_api.move_index(index, len(projects), 1)
            elif ch in (10, 13) and projects:
                self.profile_action_controller.set_active_project(port, projects[index])
                return
            elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
                return

    def _projects(self) -> list[dict[str, Any]]:
        return config_profile_api.project_profiles_for_config(self.config)


def project_picker_controller(
    config: dict[str, Any],
    *,
    profile_action_controller: Any,
) -> ProjectPickerController:
    return ProjectPickerController(
        config,
        profile_action_controller=profile_action_controller,
    )
