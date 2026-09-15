"""Project picker screen controller."""

from __future__ import annotations

import curses
from pathlib import Path
from typing import Any, Callable

from components.build_runtime.api import env as config_env_api
from components.config.api import profiles as config_profile_api
from components.build_runtime.api import runtime as config_runtime_api
from components.ui.api import input as ui_input_api
from components.ui.api import menu as ui_menu_api


class ProjectPickerController:
    """Select the active project profile from a focused picker screen."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        app_dir: Path,
        default_build_targets: str,
        default_moulin_manifest: str,
        default_dockerfile: str,
        save_config: Callable[[dict[str, Any]], Any],
    ) -> None:
        self.config = config
        self.app_dir = app_dir
        self.default_build_targets = default_build_targets
        self.default_moulin_manifest = default_moulin_manifest
        self.default_dockerfile = default_dockerfile
        self.save_config = save_config

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
                plan = config_profile_api.apply_project_picker_selection_for_config(self.config, projects[index])
                if plan["runtime_reload"]:
                    reload_runtime()
                if plan["save"]:
                    self.save_config(self.config)
                port.status = str(plan["status"])
                return
            elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
                return

    def _projects(self) -> list[dict[str, Any]]:
        projects = config_profile_api.project_profiles_for_config(self.config)
        if projects:
            return projects
        config_runtime_api.normalize_runtime_project_profiles(
            self.config,
            app_dir=self.app_dir,
            default_build_targets=self.default_build_targets,
            default_moulin_manifest=self.default_moulin_manifest,
            default_dockerfile=self.default_dockerfile,
        )
        return config_profile_api.project_profiles_for_config(self.config)


def project_picker_controller(
    config: dict[str, Any],
    *,
    app_dir: Path,
    default_build_targets: str,
    default_moulin_manifest: str,
    default_dockerfile: str,
    save_config: Callable[[dict[str, Any]], Any],
) -> ProjectPickerController:
    return ProjectPickerController(
        config,
        app_dir=app_dir,
        default_build_targets=default_build_targets,
        default_moulin_manifest=default_moulin_manifest,
        default_dockerfile=default_dockerfile,
        save_config=save_config,
    )
