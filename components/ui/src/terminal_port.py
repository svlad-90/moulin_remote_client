"""Curses terminal port controller."""

from __future__ import annotations

import curses
import os
from typing import Any

from components.ui.api import input as ui_input
from components.ui.api import layout as ui_layout
from components.ui.api import text as ui_text


class TerminalPortController:
    """Provide the curses-backed UI port used by higher-level controllers."""

    def setup_colors(self) -> None:
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_GREEN, -1)
        curses.init_pair(5, curses.COLOR_RED, -1)
        curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(7, curses.COLOR_GREEN, -1)
        curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_GREEN)

    def configure_escape_delay(self) -> None:
        try:
            curses.set_escdelay(100)
        except (AttributeError, curses.error):
            pass

    def configure_mouse(self) -> None:
        try:
            if os.environ.get("MOULIN_TUI_MOUSE", "").lower() in {"1", "true", "yes", "on"}:
                curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
            else:
                curses.mousemask(0)
        except (AttributeError, curses.error):
            pass

    def set_cursor(self, visible: bool) -> None:
        try:
            curses.curs_set(1 if visible else 0)
        except curses.error:
            pass

    def read_key(self, port: Any) -> int:
        try:
            ch = port.screen.get_wch()
        except curses.error:
            return -1
        except AttributeError:
            return port.screen.getch()
        if isinstance(ch, str):
            if not ch:
                return -1
            return ui_input.encode_text_key(ch)
        return int(ch)

    def unread_key(self, ch: int) -> None:
        if ch < 0:
            return
        try:
            text = ui_input.decode_text_key(ch)
            if text:
                curses.unget_wch(text)
            else:
                curses.ungetch(ch)
        except (curses.error, ValueError, OverflowError):
            pass

    def read_queued_text(self, port: Any, first_ch: int) -> str:
        text = ui_input.key_code_to_text(first_ch)
        if not text:
            return ""
        previous_timeout = -1
        port.screen.timeout(0)
        try:
            while True:
                ch = port.read_key()
                if ch == -1:
                    break
                char = ui_input.key_code_to_text(ch)
                if not char:
                    port.unread_key(ch)
                    break
                text += char
        finally:
            port.screen.timeout(previous_timeout)
        return text

    def selected_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(1) | curses.A_BOLD
        return curses.A_REVERSE | curses.A_BOLD

    def selected_disabled_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(1) | curses.A_DIM
        return curses.A_REVERSE | curses.A_DIM

    def active_row_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(7) | curses.A_BOLD
        return curses.A_REVERSE | curses.A_BOLD

    def selected_active_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(8) | curses.A_BOLD
        return curses.A_REVERSE | curses.A_BOLD

    def editing_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(6) | curses.A_BOLD
        return curses.A_REVERSE | curses.A_BOLD

    def accent_attr(self) -> int:
        return curses.color_pair(2) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD

    def warn_attr(self) -> int:
        return curses.color_pair(3) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD

    def running_attr(self) -> int:
        return self.warn_attr()

    def group_attr(self) -> int:
        return curses.color_pair(4) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD

    def disabled_attr(self) -> int:
        return curses.A_DIM

    def ok_attr(self) -> int:
        return self.group_attr()

    def error_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(5) | curses.A_BOLD
        return curses.A_BOLD

    def role_attr(self, role: str) -> int:
        attrs = {
            "accent": self.accent_attr,
            "disabled": self.disabled_attr,
            "error": self.error_attr,
            "ok": self.ok_attr,
            "warn": self.warn_attr,
        }
        attr_func = attrs.get(role)
        return attr_func() if attr_func is not None else 0

    def add(self, port: Any, y: int, x: int, text: str, attr: int = 0) -> None:
        try:
            port.screen.addstr(y, x, text, attr)
        except curses.error:
            pass

    def add_segments(self, port: Any, y: int, x: int, max_width: int, segments: list[tuple[str, int]]) -> None:
        remaining = max_width
        pos = x
        for text, attr in segments:
            if remaining <= 0:
                return
            chunk = text[:remaining]
            self.add(port, y, pos, chunk, attr)
            pos += len(chunk)
            remaining -= len(chunk)

    def draw_box(self, port: Any, top: int, left: int, height: int, width: int, title: str = "", attr: int = 0) -> None:
        if height < 2 or width < 2:
            return
        horizontal = "-" * max(0, width - 2)
        self.add(port, top, left, "+" + horizontal + "+", attr)
        for row in range(top + 1, top + height - 1):
            self.add(port, row, left, "|", attr)
            self.add(port, row, left + 1, " " * max(0, width - 2))
            self.add(port, row, left + width - 1, "|", attr)
        self.add(port, top + height - 1, left, "+" + horizontal + "+", attr)
        if title:
            self.add(port, top, left + 2, f" {title} "[: max(0, width - 4)], attr or self.accent_attr())

    def connection_attr_for(self, state: str) -> int:
        if state == "connected":
            return self.group_attr()
        if state in {"connecting", "disconnecting"}:
            return self.warn_attr()
        return self.disabled_attr()

    def draw_wrapped(self, port: Any, y: int, x: int, width: int, text: str, attr: int = 0, max_lines: int = 4) -> int:
        row = y
        for line in ui_text.wrap_text_lines(text, width, max_lines):
            self.add(port, row, x, line, attr)
            row += 1
        return row

    def draw_scrollbar(self, port: Any, top: int, left: int, height: int, total: int, visible: int, scroll: int) -> None:
        thumb = ui_layout.scrollbar_thumb(top, height, total, visible, scroll)
        if thumb is None:
            return
        thumb_top, thumb_height = thumb
        for row in range(top, top + height):
            selected = thumb_top <= row < thumb_top + thumb_height
            attr = self.accent_attr() if selected else self.disabled_attr()
            self.add(port, row, left, "#" if selected else "|", attr)

    def draw_label_value_wrapped(self, port: Any, row: int, x: int, width: int, label: str, value: str, *, max_lines: int = 3) -> int:
        layout = ui_layout.label_value_layout(x, width, label)
        self.add(port, row, x, layout.label_text.ljust(layout.label_width)[:width], self.accent_attr())
        return self.draw_wrapped(port, row, layout.value_x, layout.value_width, value or "<not set>", max_lines=max_lines)

    def suspend_tui(self) -> None:
        curses.def_prog_mode()
        curses.endwin()

    def restore_tui(self, port: Any) -> None:
        curses.reset_prog_mode()
        port.screen.keypad(True)
        self.configure_mouse()
        port.screen.timeout(250)


def terminal_port_controller() -> TerminalPortController:
    return TerminalPortController()
