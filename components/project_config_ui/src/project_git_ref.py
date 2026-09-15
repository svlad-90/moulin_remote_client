"""Project git-ref selection service."""

from __future__ import annotations

import curses
from typing import Any, Callable

from components.config.api import accessors as config_accessor_api
from components.project_config.api import fields as project_field_api
from components.remote.api import discovery as remote_discovery_api
from components.ui.api import input as ui_input_api
from components.ui.api import menu as ui_menu_api
from components.ui.api import text as ui_text_api


class ProjectGitRefSelector:
    """Select or manually enter the git ref for a project profile."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        fetch_branches: Callable[[str], list[str]],
    ) -> None:
        self.config = config
        self.fetch_branches = fetch_branches

    def edit_project_git_ref(
        self,
        port: Any,
        project: dict[str, Any],
        *,
        connected: bool,
        apply_project_value: Callable[[dict[str, Any], str, str], Any],
    ) -> None:
        git_url = config_accessor_api.project_git_url_for_config(self.config)
        if (
            project_field_api.project_is_active_for_config(project, self.config)
            and connected
            and config_accessor_api.remote_has_ssh_for_config(self.config)
            and git_url
        ):
            try:
                self.draw_loading_message(port, "Select Git branch/ref", "Reading remote Git branches...")
                branches = self.fetch_branches(git_url)
            except Exception as exc:
                port.status = f"Branch list failed: {exc}"
            else:
                selected = self.select_git_branch(port, branches, str(project.get("git_ref", "")))
                if selected is not None:
                    apply_project_value(project, "git_ref", selected)
                    return
        value = port.prompt("Git branch/ref", str(project.get("git_ref", ""))).strip()
        if ui_input_api.prompt_was_cancelled(port):
            port.status = "Edit cancelled"
            return
        apply_project_value(project, "git_ref", value)

    def select_git_branch(self, port: Any, branches: list[str], current: str) -> str | None:
        choices = ["<manual input>"] + branches
        index = choices.index(current) if current in choices else 0
        port.screen.timeout(-1)
        while True:
            port.screen.erase()
            height, width = port.screen.getmaxyx()
            if height < 16 or width < 70:
                port.add(0, 0, "Terminal is too small. Need at least 70x16.", port.warn_attr())
                port.screen.refresh()
                ch = port.read_key()
                if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                    return None
                continue
            port.add(0, 0, "Select Git branch/ref"[:width], curses.A_BOLD)
            port.add(1, 0, ui_text_api.fit_text(f"Git URL: {config_accessor_api.project_git_url_for_config(self.config)}", width))
            port.draw_box(3, 0, height - 6, width, "Branches")
            visible = max(1, height - 8)
            if len(choices) == 1:
                port.add(4, 2, "No branches found. Use manual input."[: width - 4], port.warn_attr())
            index = ui_menu_api.clamp_index(index, len(choices))
            scroll = ui_menu_api.list_scroll(index, len(choices), visible)
            for offset, choice in enumerate(choices[scroll : scroll + visible]):
                item_index = scroll + offset
                marker = "*" if choice == current and choice != "<manual input>" else " "
                label = f"{marker} {choice}"
                attr = port.selected_attr() if item_index == index else 0
                port.add(4 + offset, 2, ui_text_api.fit_text(label, width - 4).ljust(width - 4), attr)
            footer = "Up/Down: select | Enter: choose | q/Esc: cancel"
            port.add(height - 2, 0, footer[:width], port.accent_attr())
            port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
            port.screen.refresh()
            ch = port.read_key()
            if (ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k")) and choices:
                index = ui_menu_api.move_index(index, len(choices), -1)
            elif (ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j") or ch == ord("\t")) and choices:
                index = ui_menu_api.move_index(index, len(choices), 1)
            elif ch in (10, 13) and choices:
                if choices[index] == "<manual input>":
                    value = port.prompt("Git branch/ref", current).strip()
                    if ui_input_api.prompt_was_cancelled(port):
                        port.status = "Edit cancelled"
                        return None
                    return value
                return choices[index]
            elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
                return None

    def draw_loading_message(self, port: Any, title: str, message: str) -> None:
        port.screen.erase()
        height, width = port.screen.getmaxyx()
        port.add(0, 0, title[:width], curses.A_BOLD)
        port.add(2, 0, message[:width], port.accent_attr())
        port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
        port.screen.refresh()


def project_git_ref_selector_for_config(
    config: dict[str, Any],
    runner: Callable[[list[str]], str],
) -> ProjectGitRefSelector:
    remote_discovery = remote_discovery_api.remote_project_discovery_service()
    return ProjectGitRefSelector(
        config,
        fetch_branches=lambda git_url: remote_discovery.fetch_git_branches_for_config(
            config,
            git_url,
            runner,
        ),
    )
