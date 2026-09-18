"""Board host configuration screen renderer."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from typing import Any, Callable

from components.host_config_ui.api import board_screen_state as config_board_screen_state_api
from components.host_config.api import fields as config_field_api
from components.config.api import profiles as config_profile_api
from components.ui.api import text as ui_text_api


@dataclass(frozen=True)
class BoardScreenRenderResult:
    hosts: list[dict[str, Any]]
    fields: list[tuple[str, str]]
    selected_host: dict[str, Any] | None
    editing_cursor_yx: tuple[int, int] | None


@dataclass(frozen=True)
class BoardFieldDisplayRow:
    label: str
    key: str
    field_index: int | None
    group: bool = False


class BoardScreenRenderer:
    """Render the board host configuration screen from controller state."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        board_host_fields_factory: Callable[[], list[tuple[str, str]]],
        board_field_service: config_field_api.BoardHostFieldService | None = None,
    ) -> None:
        self.config = config
        self.board_host_fields_factory = board_host_fields_factory
        self.board_field_service = board_field_service or config_field_api.board_host_field_service()

    def render(
        self,
        port: Any,
        *,
        height: int,
        width: int,
        screen_state: config_board_screen_state_api.BoardScreenStateController,
    ) -> BoardScreenRenderResult:
        state = screen_state.state
        hosts = screen_state.hosts()
        fields = self.board_host_fields_factory()
        screen_state.sync_selection(hosts, fields)
        selected_host = screen_state.selected_host(hosts)

        panel_top = 3
        panel_height = height - 6
        self._render_header(port, width, state.focus)
        port.draw_box(panel_top, 0, panel_height, width, "Board hosts")

        detail_x = 2
        detail_w = width - 4
        table_w = width - 4
        min_detail_rows = 2 + len(fields) + 3
        visible_hosts = max(1, min(max(1, len(hosts)), panel_height - min_detail_rows))
        table_y = panel_top + 1
        self._render_host_list(port, hosts, table_y, table_w, visible_hosts, state)

        row = self._render_host_count_if_needed(port, hosts, visible_hosts, table_y, detail_x, detail_w, state)
        editing_cursor_yx = self._render_host_details(
            port,
            fields,
            selected_host,
            row,
            height,
            panel_top,
            panel_height,
            detail_x,
            detail_w,
            state,
        )
        self._render_footer(port, height, width)
        return BoardScreenRenderResult(
            hosts=hosts,
            fields=fields,
            selected_host=selected_host,
            editing_cursor_yx=editing_cursor_yx,
        )

    def _render_header(self, port: Any, width: int, focus: str) -> None:
        active_name = str(config_profile_api.active_board_host(self.config).get("name", "")) or "<none>"
        port.add(0, 0, "Board host configuration"[:width], curses.A_BOLD)
        port.add(1, 0, f"Active: {active_name} | Board connection: {port.board_connection_state}"[:width])
        port.add(2, 0, f"Focus: {'board host list' if focus == 'hosts' else 'fields'}"[:width], port.accent_attr())

    def _render_host_list(
        self,
        port: Any,
        hosts: list[dict[str, Any]],
        table_y: int,
        table_w: int,
        visible_hosts: int,
        state: config_board_screen_state_api.BoardScreenState,
    ) -> None:
        host_scroll = config_field_api.host_profile_page_scroll(state.host_index, len(hosts), visible_hosts)
        port.add(table_y, 2, ui_text_api.fit_text("A Name               User@Host", table_w), port.accent_attr())
        if not hosts:
            port.add(table_y + 1, 2, "No board hosts configured. Press 'a' to add one."[:table_w], port.disabled_attr())
            return
        for offset, profile in enumerate(hosts[host_scroll : host_scroll + visible_hosts]):
            item_index = host_scroll + offset
            row_model = config_field_api.host_profile_row_model(
                profile,
                active_name=str(self.config.get("active_board_host", "")),
                selected=state.focus == "hosts" and item_index == state.host_index,
            )
            attr = self._profile_row_attr(port, str(row_model["state"]))
            port.add(table_y + 1 + offset, 2, ui_text_api.fit_text(str(row_model["text"]), table_w).ljust(table_w), attr)

    def _render_host_count_if_needed(
        self,
        port: Any,
        hosts: list[dict[str, Any]],
        visible_hosts: int,
        table_y: int,
        detail_x: int,
        detail_w: int,
        state: config_board_screen_state_api.BoardScreenState,
    ) -> int:
        row = table_y + visible_hosts + 2
        if len(hosts) > visible_hosts:
            port.add(
                row,
                detail_x,
                config_field_api.host_profile_count_label(state.host_index, len(hosts), "board hosts")[:detail_w],
                port.disabled_attr(),
            )
            row += 1
        return row

    def _render_host_details(
        self,
        port: Any,
        fields: list[tuple[str, str]],
        selected_host: dict[str, Any] | None,
        row: int,
        height: int,
        panel_top: int,
        panel_height: int,
        detail_x: int,
        detail_w: int,
        state: config_board_screen_state_api.BoardScreenState,
    ) -> tuple[int, int] | None:
        if selected_host is None:
            port.add(row, detail_x, "Selected board host: <none>"[:detail_w], port.disabled_attr())
            return None
        display_rows = self._field_display_rows(fields)
        hint_row = panel_top + panel_height - 2
        visible_fields = max(0, hint_row - row)
        editing_cursor_yx = self._render_field_rows(
            port,
            display_rows,
            selected_host,
            row,
            visible_fields,
            detail_x,
            detail_w,
            state,
        )
        self._render_field_hint(port, fields, hint_row, detail_x, detail_w, state)
        return editing_cursor_yx

    def _field_display_rows(self, fields: list[tuple[str, str]]) -> list[BoardFieldDisplayRow]:
        rows: list[BoardFieldDisplayRow] = []
        last_group = ""
        for field_index, (label, key) in enumerate(fields):
            group = self._field_group_for_key(key)
            if group != last_group:
                if rows and not rows[-1].group:
                    rows.append(BoardFieldDisplayRow("", "", None, group=True))
                rows.append(BoardFieldDisplayRow(group, "", None, group=True))
                last_group = group
            rows.append(BoardFieldDisplayRow(label, key, field_index))
        return rows

    def _field_group_for_key(self, key: str) -> str:
        if key in {"name", "label", "type"}:
            return "PROFILE"
        if key in {"user", "host", "work_dir"}:
            return "SSH"
        if key in {"console_device", "ufs_loadaddr", "ufs_buffersize", "direct_copy"}:
            return "FLASHING"
        if key in {"tftp_root", "nfs_root", "deploy_subdir", "server_ip", "board_ip"}:
            return "NETWORK BOOT"
        return "OTHER"

    def _render_field_rows(
        self,
        port: Any,
        display_rows: list[BoardFieldDisplayRow],
        selected_host: dict[str, Any],
        row: int,
        visible_fields: int,
        detail_x: int,
        detail_w: int,
        state: config_board_screen_state_api.BoardScreenState,
    ) -> tuple[int, int] | None:
        editing_cursor_yx: tuple[int, int] | None = None
        for display_row in display_rows[:visible_fields]:
            if display_row.group:
                attr = port.accent_attr() if display_row.label else 0
                port.add(row, detail_x, ui_text_api.fit_text(display_row.label, detail_w).ljust(detail_w), attr)
                row += 1
                continue
            label = display_row.label
            key = display_row.key
            is_editing = state.focus == "fields" and key == state.editing_key
            raw_value = state.editing_value if is_editing else str(selected_host.get(key, ""))
            enabled = self.board_field_service.field_enabled(key, selected_host)
            row_model = config_field_api.host_field_row_model(
                label=label,
                key=key,
                profile=selected_host,
                value=raw_value,
                enabled=enabled,
                selected=state.focus == "fields" and display_row.field_index == state.field_index,
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
        row: int,
        detail_x: int,
        detail_w: int,
        state: config_board_screen_state_api.BoardScreenState,
    ) -> None:
        if not fields or state.focus != "fields":
            return
        _label, selected_key = fields[state.field_index]
        if state.editing_key:
            port.add(row, detail_x, "Enter: save | Esc: cancel | Left/Right/Home/End: move cursor"[:detail_w], port.accent_attr())
            return
        port.add(row, detail_x, self.board_field_service.field_hint(selected_key)[:detail_w], port.accent_attr())

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


def board_screen_renderer(
    config: dict[str, Any],
    *,
    board_host_fields_factory: Callable[[], list[tuple[str, str]]],
) -> BoardScreenRenderer:
    return BoardScreenRenderer(config, board_host_fields_factory=board_host_fields_factory)
