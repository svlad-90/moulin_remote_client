"""Build host configuration screen renderer."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from typing import Any, Callable

from components.host_config.api import fields as config_field_api
from components.config.api import profiles as config_profile_api
from components.host_config_ui.api import remote_screen_state as config_remote_screen_state_api
from components.ui.api import text as ui_text_api


@dataclass(frozen=True)
class RemoteScreenRenderResult:
    remotes: list[dict[str, Any]]
    fields: list[tuple[str, str]]
    selected_remote: dict[str, Any] | None
    editing_cursor_yx: tuple[int, int] | None


class RemoteScreenRenderer:
    """Render the build host configuration screen from controller state."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        remote_fields_factory: Callable[[], list[tuple[str, str]]],
        build_field_service: config_field_api.BuildHostFieldService | None = None,
    ) -> None:
        self.config = config
        self.remote_fields_factory = remote_fields_factory
        self.build_field_service = build_field_service or config_field_api.build_host_field_service()

    def render(
        self,
        port: Any,
        *,
        height: int,
        width: int,
        screen_state: config_remote_screen_state_api.RemoteScreenStateController,
    ) -> RemoteScreenRenderResult:
        state = screen_state.state
        remote = config_profile_api.active_remote(self.config)
        remotes = screen_state.remotes()
        screen_state.sync_selection(remotes, [])
        selected_remote = screen_state.selected_remote(remotes)

        panel_top = 3
        panel_height = height - 6
        self._render_header(port, width, state.focus, remote)
        port.draw_box(panel_top, 0, panel_height, width, "Build hosts")

        detail_x = 2
        detail_w = width - 4
        table_w = width - 4
        fields: list[tuple[str, str]] = []
        if selected_remote is not None:
            fields = self.remote_fields_factory()
            screen_state.sync_selection(remotes, fields)
        else:
            screen_state.sync_selection(remotes, [])

        min_detail_rows = 2 + len(fields) + 3
        visible_remotes = max(1, min(max(1, len(remotes)), panel_height - min_detail_rows))
        table_y = panel_top + 1
        self._render_remote_list(port, remotes, table_y, table_w, visible_remotes, state)

        row = self._render_remote_count_if_needed(port, remotes, visible_remotes, table_y, detail_x, detail_w, state)
        editing_cursor_yx = self._render_remote_details(
            port,
            fields,
            selected_remote,
            row,
            height,
            panel_top,
            panel_height,
            detail_x,
            detail_w,
            state,
        )
        self._render_footer(port, height, width)
        return RemoteScreenRenderResult(
            remotes=remotes,
            fields=fields,
            selected_remote=selected_remote,
            editing_cursor_yx=editing_cursor_yx,
        )

    def _render_header(self, port: Any, width: int, focus: str, remote: dict[str, Any]) -> None:
        port.add(0, 0, "Build host configuration"[:width], curses.A_BOLD)
        active_name = str(remote.get("name", "")) or "<none>"
        port.add(1, 0, f"Active: {active_name} | Build connection: {port.connection_state}"[:width])
        port.add(2, 0, f"Focus: {'build host list' if focus == 'remotes' else 'fields'}"[:width], port.accent_attr())

    def _render_remote_list(
        self,
        port: Any,
        remotes: list[dict[str, Any]],
        table_y: int,
        table_w: int,
        visible_remotes: int,
        state: config_remote_screen_state_api.RemoteScreenState,
    ) -> None:
        remote_scroll = config_field_api.host_profile_page_scroll(state.remote_index, len(remotes), visible_remotes)
        port.add(table_y, 2, ui_text_api.fit_text("A Name               User@Host", table_w), port.accent_attr())
        if not remotes:
            port.add(table_y + 1, 2, "No build hosts configured. Press 'a' to add one."[:table_w], port.disabled_attr())
            return
        for offset, profile in enumerate(remotes[remote_scroll : remote_scroll + visible_remotes]):
            item_index = remote_scroll + offset
            row_model = config_field_api.host_profile_row_model(
                profile,
                active_name=str(self.config.get("active_remote", "")),
                selected=state.focus == "remotes" and item_index == state.remote_index,
            )
            attr = self._profile_row_attr(port, str(row_model["state"]))
            port.add(table_y + 1 + offset, 2, ui_text_api.fit_text(str(row_model["text"]), table_w).ljust(table_w), attr)

    def _render_remote_count_if_needed(
        self,
        port: Any,
        remotes: list[dict[str, Any]],
        visible_remotes: int,
        table_y: int,
        detail_x: int,
        detail_w: int,
        state: config_remote_screen_state_api.RemoteScreenState,
    ) -> int:
        row = table_y + visible_remotes + 2
        if len(remotes) > visible_remotes:
            port.add(
                row,
                detail_x,
                config_field_api.host_profile_count_label(state.remote_index, len(remotes), "build hosts")[:detail_w],
                port.disabled_attr(),
            )
            row += 1
        return row

    def _render_remote_details(
        self,
        port: Any,
        fields: list[tuple[str, str]],
        selected_remote: dict[str, Any] | None,
        row: int,
        height: int,
        panel_top: int,
        panel_height: int,
        detail_x: int,
        detail_w: int,
        state: config_remote_screen_state_api.RemoteScreenState,
    ) -> tuple[int, int] | None:
        if selected_remote is None:
            port.add(row, detail_x, "Selected build host: <none>"[:detail_w], port.disabled_attr())
            return None
        port.add(row, detail_x, "Fields:", port.accent_attr())
        row += 1
        visible_fields = max(0, panel_top + panel_height - row - 5)
        editing_cursor_yx = self._render_field_rows(
            port,
            fields,
            selected_remote,
            row,
            visible_fields,
            detail_x,
            detail_w,
            state,
        )
        row += len(fields[:visible_fields])
        self._render_field_hint(port, fields, selected_remote, row, height, detail_x, detail_w, state)
        return editing_cursor_yx

    def _render_field_rows(
        self,
        port: Any,
        fields: list[tuple[str, str]],
        selected_remote: dict[str, Any],
        row: int,
        visible_fields: int,
        detail_x: int,
        detail_w: int,
        state: config_remote_screen_state_api.RemoteScreenState,
    ) -> tuple[int, int] | None:
        editing_cursor_yx: tuple[int, int] | None = None
        for offset, (label, key) in enumerate(fields[:visible_fields]):
            is_editing = state.focus == "fields" and key == state.editing_key
            raw_value = state.editing_value if is_editing else str(selected_remote.get(key, ""))
            enabled = self.build_field_service.field_enabled_for_config(
                key,
                selected_remote,
                self.config,
                connected=port.connection_state == "connected",
            )
            row_model = config_field_api.host_field_row_model(
                label=label,
                key=key,
                profile=selected_remote,
                value=raw_value,
                enabled=enabled,
                selected=state.focus == "fields" and offset == state.field_index,
                editing=is_editing,
            )
            attr = self._field_row_attr(port, str(row_model["state"]))
            port.add(row, detail_x, ui_text_api.fit_text(str(row_model["text"]), detail_w).ljust(detail_w), attr)
            if is_editing:
                cursor_x = min(detail_x + 20 + state.editing_cursor, detail_x + detail_w - 1)
                editing_cursor_yx = (row, cursor_x)
            row += 1
        return editing_cursor_yx

    def _render_field_hint(
        self,
        port: Any,
        fields: list[tuple[str, str]],
        selected_remote: dict[str, Any],
        row: int,
        height: int,
        detail_x: int,
        detail_w: int,
        state: config_remote_screen_state_api.RemoteScreenState,
    ) -> None:
        if row >= height - 3 or not fields or state.focus != "fields":
            return
        _label, selected_key = fields[state.field_index]
        if state.editing_key:
            port.add(row, detail_x, "Enter: save | Esc: cancel | Left/Right/Home/End: move cursor"[:detail_w], port.accent_attr())
            return
        enabled = self.build_field_service.field_enabled_for_config(
            selected_key,
            selected_remote,
            self.config,
            connected=port.connection_state == "connected",
        )
        message = (
            self.build_field_service.field_hint(selected_key)
            if enabled
            else self.build_field_service.field_disabled_reason_for_config(selected_key, selected_remote, self.config)
        )
        port.add(row, detail_x, message[:detail_w], port.accent_attr() if enabled else port.disabled_attr())

    def _render_footer(self, port: Any, height: int, width: int) -> None:
        footer = "Left/Right: hosts/fields | Enter: edit/save | a: add | d: delete | s: set active | Esc: hosts/back | q: back"
        port.add(height - 2, 0, footer[:width], port.accent_attr())
        port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)

    def _profile_row_attr(self, port: Any, state: str) -> int:
        if state == "selected-active":
            return port.selected_active_attr()
        if state == "selected":
            return port.selected_attr()
        if state == "active":
            return port.active_row_attr()
        return 0

    def _field_row_attr(self, port: Any, state: str) -> int:
        if state == "editing":
            return port.editing_attr()
        if state == "selected":
            return port.selected_attr()
        if state == "selected-disabled":
            return port.selected_disabled_attr()
        if state == "disabled":
            return port.disabled_attr()
        return 0


def remote_screen_renderer(
    config: dict[str, Any],
    *,
    remote_fields_factory: Callable[[], list[tuple[str, str]]],
) -> RemoteScreenRenderer:
    return RemoteScreenRenderer(config, remote_fields_factory=remote_fields_factory)
