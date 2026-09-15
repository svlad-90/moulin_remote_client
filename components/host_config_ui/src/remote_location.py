"""Remote project location selection service."""

from __future__ import annotations

import curses
from pathlib import Path
from typing import Any, Callable

from components.config.api import accessors as config_accessor_api
from components.project_config.api import project_fields as project_fields_api
from components.remote.api import discovery as remote_discovery_api
from components.ui.api import input as ui_input_api
from components.ui.api import menu as ui_menu_api


class RemoteLocationBrowser:
    """Browse project directories through the configured build host."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        fetch_child_dirs: Callable[[str], list[str]],
        fetch_home: Callable[[], str],
        parent_dir: Callable[[str, str], str],
    ) -> None:
        self.config = config
        self.fetch_child_dirs = fetch_child_dirs
        self.fetch_home = fetch_home
        self.parent_dir = parent_dir

    def browse_project_directory(self, port: Any, start_path: str) -> str | None:
        current_path = start_path if start_path and start_path != "." else "~"
        index = 0
        dirs: list[str] = []
        error = ""
        pending_path: str | None = current_path
        port.screen.timeout(-1)
        while True:
            height, width = port.screen.getmaxyx()
            if height < 18 or width < 80:
                port.screen.clear()
                port.add(0, 0, "Terminal is too small. Need at least 80x18.", port.warn_attr())
                port.screen.refresh()
                ch = port.read_key()
                if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                    return None
                continue
            if pending_path is not None:
                try:
                    next_dirs = self.fetch_child_dirs(pending_path)
                    current_path = pending_path
                    dirs = next_dirs
                    error = ""
                    index = 0
                except Exception as exc:
                    error = str(exc)
                pending_path = None
            entries = [".."] + dirs
            index = ui_menu_api.clamp_index(index, len(entries))
            self.draw_directory_browser(port, current_path, dirs, index, error, loading=False)
            ch = port.read_key()
            if ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
                index = ui_menu_api.move_index(index, len(entries), -1)
            elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"):
                index = ui_menu_api.move_index(index, len(entries), 1)
            elif ch in (ord("\t"), 10, 13):
                selected = entries[index]
                if selected == "..":
                    if current_path == "~":
                        try:
                            home = self.fetch_home()
                        except Exception:
                            home = "~"
                        pending_path = self.parent_dir(current_path, home)
                    else:
                        pending_path = self.parent_dir(current_path, "~")
                else:
                    pending_path = selected
            elif ch == ord(" "):
                selected = entries[index]
                return current_path if selected == ".." else selected
            elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
                return None

    def draw_directory_browser(
        self,
        port: Any,
        current_path: str,
        dirs: list[str],
        index: int,
        error: str,
        *,
        loading: bool,
    ) -> None:
        port.screen.erase()
        height, width = port.screen.getmaxyx()
        panel_top = 3
        panel_height = height - 6
        port.add(0, 0, "Browse remote project directory"[:width].ljust(width), curses.A_BOLD)
        port.add(1, 0, f"{config_accessor_api.remote_spec_for_config(self.config)}:{current_path}"[:width].ljust(width))
        port.draw_box(panel_top, 0, panel_height, width, "Directories")
        inner_width = max(0, width - 4)
        for row in range(panel_top + 1, panel_top + panel_height - 1):
            port.add(row, 2, " " * inner_width)
        if loading:
            port.add(panel_top + 1, 2, "Loading..."[:inner_width], port.accent_attr())
        elif error:
            port.add(panel_top + 1, 2, error[:inner_width], port.error_attr())
        entries = [".."] + dirs
        visible = max(1, panel_height - 2)
        index = ui_menu_api.clamp_index(index, len(entries))
        scroll = ui_menu_api.list_scroll(index, len(entries), visible)
        if not loading:
            for offset, path in enumerate(entries[scroll : scroll + visible]):
                item_index = scroll + offset
                attr = port.selected_attr() if item_index == index else 0
                label = "../" if path == ".." else Path(path).name + "/"
                port.add(panel_top + 1 + offset, 2, label[:inner_width].ljust(inner_width), attr)
        footer = "Up/Down: select | Enter: open | Space: choose selected | q/Esc: back"
        port.add(height - 2, 0, footer[:width].ljust(width), port.accent_attr())
        port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
        port.screen.noutrefresh()
        curses.doupdate()


class ProjectRemoteDirEditor:
    """Edit a project profile's remote directory using a remote browser."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        browser: RemoteLocationBrowser,
        project_field_service: project_fields_api.ProjectFieldService | None = None,
    ) -> None:
        self.config = config
        self.browser = browser
        self.project_field_service = project_field_service or project_fields_api.project_field_service()

    def edit_project_remote_dir(
        self,
        port: Any,
        project: dict[str, Any],
        *,
        connected: bool,
        apply_project_value: Callable[[dict[str, Any], str, str], Any],
    ) -> None:
        field = {"label": "Project dir", "key": "project_dir", "kind": "remote_dir"}
        if not self.project_field_service.field_enabled_for_config(
            field,
            project,
            self.config,
            connected=connected,
        ):
            port.status = self.project_field_service.field_disabled_reason_for_config(field, project, self.config)
            return
        selected = self.browser.browse_project_directory(port, str(project.get("project_dir", "")) or "~")
        if selected:
            apply_project_value(project, "project_dir", selected)
            port.status = f"Project dir: {project.get('project_dir', '')}"


def remote_location_browser_for_config(
    config: dict[str, Any],
    runner: Callable[[list[str]], str],
) -> RemoteLocationBrowser:
    remote_discovery = remote_discovery_api.remote_project_discovery_service()
    return RemoteLocationBrowser(
        config,
        fetch_child_dirs=lambda path: remote_discovery.fetch_remote_child_dirs_for_config(
            config,
            path,
            runner,
        ),
        fetch_home=lambda: remote_discovery.fetch_remote_home_for_config(
            config,
            runner,
        ),
        parent_dir=remote_discovery.remote_parent_dir,
    )


def project_remote_dir_editor_for_config(
    config: dict[str, Any],
    runner: Callable[[list[str]], str],
) -> ProjectRemoteDirEditor:
    return ProjectRemoteDirEditor(
        config,
        browser=remote_location_browser_for_config(config, runner),
    )
