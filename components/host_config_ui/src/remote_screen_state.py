"""Build host configuration screen state controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from components.config.api import profiles as config_profile_api
from components.ui.api import input as ui_input_api


@dataclass
class RemoteScreenState:
    remote_index: int = 0
    remote_index_initialized: bool = False
    field_index: int = 0
    focus: str = "remotes"
    editing_key: str = ""
    editing_value: str = ""
    editing_cursor: int = 0


class RemoteScreenStateController:
    """Own navigation and inline editing state for the build host screen."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.state = RemoteScreenState()

    def remotes(self) -> list[dict[str, Any]]:
        return [item for item in self.config.get("remotes", []) if isinstance(item, dict)]

    def sync_selection(self, remotes: list[dict[str, Any]], fields: list[tuple[str, str]]) -> None:
        if not self.state.remote_index_initialized:
            self.state.remote_index = config_profile_api.active_profile_index(
                remotes,
                str(self.config.get("active_remote", "")),
            )
            self.state.focus = "remotes"
            self.state.remote_index_initialized = True
        self.state.remote_index = min(self.state.remote_index, max(0, len(remotes) - 1))
        if fields:
            self.state.field_index = min(self.state.field_index, max(0, len(fields) - 1))
        elif not remotes:
            self.state.field_index = 0

    def selected_remote(self, remotes: list[dict[str, Any]]) -> dict[str, Any] | None:
        return remotes[self.state.remote_index] if remotes else None

    def selected_field_key(self, fields: list[tuple[str, str]]) -> str:
        if fields and 0 <= self.state.field_index < len(fields):
            return fields[self.state.field_index][1]
        return ""

    def apply_navigation_action(self, port: Any, action: dict[str, Any], *, field_count: int, remote_count: int) -> None:
        kind = action["action"]
        if kind == "focus-list":
            self.state.focus = str(action["focus"])
            if action.get("status") == "list-focused":
                port.status = "Build host list focused"
        elif kind == "focus-fields":
            self.state.focus = "fields"
        elif kind == "move-field" and field_count:
            self.state.field_index = (self.state.field_index + int(action["delta"])) % field_count
        elif kind == "move-list" and remote_count:
            self.state.remote_index = (self.state.remote_index + int(action["delta"])) % remote_count
        elif kind == "status":
            if action["status"] == "add-first":
                port.status = "Add a build host first"
            elif action["status"] == "none-selected":
                port.status = "No build host selected"

    def begin_inline_edit(self, key: str, value: str) -> None:
        self.state.editing_key = key
        self.state.editing_value = value
        self.state.editing_cursor = len(value)

    def handle_inline_edit_key(
        self,
        port: Any,
        ch: int,
        selected_remote: dict[str, Any],
        apply_remote_value: Callable[[Any, dict[str, Any], str, str], None],
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
            apply_remote_value(port, selected_remote, self.state.editing_key, self.state.editing_value)
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

    def apply_add_state(self) -> None:
        self.state.remote_index = max(0, len(self.config.get("remotes", [])) - 1)
        self.state.focus = "fields" if self.config.get("remotes") else "remotes"

    def apply_delete_state(self) -> None:
        self.state.remote_index = min(self.state.remote_index, max(0, len(self.config.get("remotes", [])) - 1))
        self.state.focus = "remotes"
