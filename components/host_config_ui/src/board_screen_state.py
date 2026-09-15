"""Board host configuration screen state controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from components.config.api import profiles as config_profile_api
from components.ui.api import input as ui_input_api


@dataclass
class BoardScreenState:
    host_index: int = 0
    host_index_initialized: bool = False
    field_index: int = 0
    focus: str = "hosts"
    editing_key: str = ""
    editing_value: str = ""
    editing_cursor: int = 0


class BoardScreenStateController:
    """Own navigation and inline editing state for the board host screen."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.state = BoardScreenState()

    def hosts(self) -> list[dict[str, Any]]:
        return [item for item in self.config.get("board_hosts", []) if isinstance(item, dict)]

    def sync_selection(self, hosts: list[dict[str, Any]], fields: list[tuple[str, str]]) -> None:
        if not self.state.host_index_initialized:
            self.state.host_index = config_profile_api.active_profile_index(
                hosts,
                str(self.config.get("active_board_host", "")),
            )
            self.state.host_index_initialized = True
        self.state.host_index = min(self.state.host_index, max(0, len(hosts) - 1))
        if fields:
            self.state.field_index = min(self.state.field_index, max(0, len(fields) - 1))
        elif not hosts:
            self.state.field_index = 0

    def selected_host(self, hosts: list[dict[str, Any]]) -> dict[str, Any] | None:
        return hosts[self.state.host_index] if hosts else None

    def selected_field_key(self, fields: list[tuple[str, str]]) -> str:
        if fields and 0 <= self.state.field_index < len(fields):
            return fields[self.state.field_index][1]
        return ""

    def apply_navigation_action(self, port: Any, action: dict[str, Any], *, field_count: int, host_count: int) -> None:
        kind = action["action"]
        if kind == "focus-list":
            self.state.focus = str(action["focus"])
            if action.get("status") == "list-focused":
                port.status = "Board host list focused"
        elif kind == "focus-fields":
            self.state.focus = "fields"
        elif kind == "move-field" and field_count:
            self.state.field_index = (self.state.field_index + int(action["delta"])) % field_count
        elif kind == "move-list" and host_count:
            self.state.host_index = (self.state.host_index + int(action["delta"])) % host_count
        elif kind == "status":
            if action["status"] == "add-first":
                port.status = "Add a board host first"
            elif action["status"] == "none-selected":
                port.status = "No board host selected"

    def begin_inline_edit(self, key: str, value: str) -> None:
        self.state.editing_key = key
        self.state.editing_value = value
        self.state.editing_cursor = len(value)

    def handle_inline_edit_key(
        self,
        port: Any,
        ch: int,
        selected_host: dict[str, Any],
        apply_host_value: Callable[[Any, dict[str, Any], str, str], None],
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
            apply_host_value(port, selected_host, self.state.editing_key, self.state.editing_value)
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
        hosts = self.hosts()
        self.state.host_index = max(0, len(hosts) - 1)
        self.state.focus = "fields" if hosts else "hosts"

    def apply_delete_state(self) -> None:
        hosts = self.hosts()
        self.state.host_index = min(self.state.host_index, max(0, len(hosts) - 1))
        self.state.focus = "hosts"
