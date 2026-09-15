"""Application terminal-port adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from components.main_menu.api import state as main_menu_state_api
from components.ui.api import terminal_port as ui_terminal_port_api
from components.ui.api.menu import MenuItem


class AppTerminalPortAdapter:
    """Own the ClientApp methods required by UI screens as a terminal port."""

    def __init__(
        self,
        *,
        app_dir: Path,
        terminal_port: ui_terminal_port_api.TerminalPortController,
        main_menu_state: main_menu_state_api.MainMenuStateController,
    ) -> None:
        self.app_dir = app_dir
        self.terminal_port = terminal_port
        self.main_menu_state = main_menu_state

    def setup_colors(self) -> None:
        self.terminal_port.setup_colors()

    def configure_escape_delay(self) -> None:
        self.terminal_port.configure_escape_delay()

    def set_cursor(self, visible: bool) -> None:
        self.terminal_port.set_cursor(visible)

    def read_key(self, port: Any) -> int:
        return self.terminal_port.read_key(port)

    def unread_key(self, ch: int) -> None:
        self.terminal_port.unread_key(ch)

    def read_queued_text(self, port: Any, first_ch: int) -> str:
        return self.terminal_port.read_queued_text(port, first_ch)

    def selected_attr(self) -> int:
        return self.terminal_port.selected_attr()

    def selected_disabled_attr(self) -> int:
        return self.terminal_port.selected_disabled_attr()

    def active_row_attr(self) -> int:
        return self.terminal_port.active_row_attr()

    def selected_active_attr(self) -> int:
        return self.terminal_port.selected_active_attr()

    def editing_attr(self) -> int:
        return self.terminal_port.editing_attr()

    def accent_attr(self) -> int:
        return self.terminal_port.accent_attr()

    def warn_attr(self) -> int:
        return self.terminal_port.warn_attr()

    def running_attr(self) -> int:
        return self.terminal_port.running_attr()

    def group_attr(self) -> int:
        return self.terminal_port.group_attr()

    def disabled_attr(self) -> int:
        return self.terminal_port.disabled_attr()

    def ok_attr(self) -> int:
        return self.terminal_port.ok_attr()

    def error_attr(self) -> int:
        return self.terminal_port.error_attr()

    def role_attr(self, role: str) -> int:
        return self.terminal_port.role_attr(role)

    def item_enabled(self, port: Any, item: MenuItem) -> bool:
        return self.main_menu_state.item_enabled(port, item)

    def disabled_reason(self, port: Any, item: MenuItem) -> str:
        return self.main_menu_state.disabled_reason(port, item)

    def add(self, port: Any, y: int, x: int, text: str, attr: int = 0) -> None:
        self.terminal_port.add(port, y, x, text, attr)

    def add_segments(self, port: Any, y: int, x: int, max_width: int, segments: list[tuple[str, int]]) -> None:
        self.terminal_port.add_segments(port, y, x, max_width, segments)

    def draw_box(self, port: Any, top: int, left: int, height: int, width: int, title: str = "", attr: int = 0) -> None:
        self.terminal_port.draw_box(port, top, left, height, width, title, attr)

    def connection_attr_for(self, state: str) -> int:
        return self.terminal_port.connection_attr_for(state)

    def mapping_status_snapshot(self, port: Any) -> dict[str, str]:
        return self.main_menu_state.mapping_status_snapshot(port)

    def draw_wrapped(self, port: Any, y: int, x: int, width: int, text: str, attr: int = 0, max_lines: int = 4) -> int:
        return self.terminal_port.draw_wrapped(port, y, x, width, text, attr, max_lines)

    def draw_scrollbar(self, port: Any, top: int, left: int, height: int, total: int, visible: int, scroll: int) -> None:
        self.terminal_port.draw_scrollbar(port, top, left, height, total, visible, scroll)

    def draw_label_value_wrapped(
        self,
        port: Any,
        row: int,
        x: int,
        width: int,
        label: str,
        value: str,
        *,
        max_lines: int = 3,
    ) -> int:
        return self.terminal_port.draw_label_value_wrapped(port, row, x, width, label, value, max_lines=max_lines)

    def suspend_tui(self) -> None:
        self.terminal_port.suspend_tui()

    def restore_tui(self, port: Any) -> None:
        self.terminal_port.restore_tui(port)


def app_terminal_port_adapter(
    *,
    app_dir: Path,
    terminal_port: ui_terminal_port_api.TerminalPortController,
    main_menu_state: main_menu_state_api.MainMenuStateController,
) -> AppTerminalPortAdapter:
    return AppTerminalPortAdapter(
        app_dir=app_dir,
        terminal_port=terminal_port,
        main_menu_state=main_menu_state,
    )
