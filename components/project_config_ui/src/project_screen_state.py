"""Project configuration screen state controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from components.config.api import profiles as config_profile_api
from components.ui.api import input as ui_input_api


@dataclass
class ProjectScreenState:
    project_index: int = 0
    project_index_initialized: bool = False
    field_index: int = 0
    focus: str = "projects"
    editing_key: str = ""
    editing_value: str = ""
    editing_cursor: int = 0


class ProjectScreenStateController:
    """Own navigation and inline editing state for the project screen."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.state = ProjectScreenState()

    def projects(self) -> list[dict[str, Any]]:
        return [item for item in self.config.get("projects", []) if isinstance(item, dict)]

    def sync_selection(self, projects: list[dict[str, Any]], fields: list[dict[str, Any]]) -> None:
        if not self.state.project_index_initialized:
            self.state.project_index = config_profile_api.active_profile_index(
                projects,
                str(self.config.get("active_project", "")),
            )
            self.state.focus = "projects"
            self.state.project_index_initialized = True
        self.state.project_index = min(self.state.project_index, max(0, len(projects) - 1))
        if fields:
            self.state.field_index = min(self.state.field_index, max(0, len(fields) - 1))
        elif not projects:
            self.state.field_index = 0

    def selected_project(self, projects: list[dict[str, Any]]) -> dict[str, Any] | None:
        return projects[self.state.project_index] if projects else None

    def selected_field_key(self, fields: list[dict[str, Any]]) -> str:
        if fields and 0 <= self.state.field_index < len(fields):
            return str(fields[self.state.field_index]["key"])
        return ""

    def apply_navigation_action(self, port: Any, action: dict[str, Any], *, field_count: int, project_count: int) -> None:
        kind = action["action"]
        if kind == "focus-list":
            self.state.focus = str(action["focus"])
            if action.get("status") == "list-focused":
                port.status = "Project list focused"
        elif kind == "focus-fields":
            self.state.focus = "fields"
        elif kind == "move-field" and field_count:
            self.state.field_index = (self.state.field_index + int(action["delta"])) % field_count
        elif kind == "move-list" and project_count:
            self.state.project_index = (self.state.project_index + int(action["delta"])) % project_count
        elif kind == "status":
            if action["status"] == "add-first":
                port.status = "Add a project first"
            elif action["status"] == "none-selected":
                port.status = "No project selected"

    def begin_inline_edit(self, key: str, value: str) -> None:
        self.state.editing_key = key
        self.state.editing_value = value
        self.state.editing_cursor = len(value)

    def handle_inline_edit_key(
        self,
        port: Any,
        ch: int,
        selected_project: dict[str, Any],
        apply_project_value: Callable[[Any, dict[str, Any], str, str], None],
    ) -> bool:
        edit = ui_input_api.inline_edit_key_action(self.state.editing_value, self.state.editing_cursor, ch)
        if edit.action == "noop":
            edit = ui_input_api.inline_edit_key_action(
                self.state.editing_value,
                self.state.editing_cursor,
                ch,
                port.read_queued_text(ch),
            )
        if edit.action == "save":
            apply_project_value(port, selected_project, self.state.editing_key, self.state.editing_value)
            self.clear_inline_edit()
            port.set_cursor(False)
            return True
        if edit.action == "cancel":
            self.clear_inline_edit()
            port.status = "Edit cancelled"
            port.set_cursor(False)
            return True
        if edit.action == "edit":
            self.state.editing_value = edit.value
            self.state.editing_cursor = edit.cursor
            return True
        return True

    def clear_inline_edit(self) -> None:
        self.state.editing_key = ""
        self.state.editing_value = ""
        self.state.editing_cursor = 0

    def apply_profile_state(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        projects = state["projects"]
        self.state.project_index = int(state["project_index"])
        self.state.focus = str(state["focus"])
        return projects
