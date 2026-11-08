"""Curses terminal port controller."""

from __future__ import annotations

import base64
import curses
import os
import select
import shutil
import subprocess
import sys
from typing import Any

from components.jobs.api import jobs as job_api
from components.ui.api import input as ui_input
from components.ui.api import layout as ui_layout
from components.ui.api import text as ui_text


class TerminalPortController:
    """Provide the curses-backed UI port used by higher-level controllers."""

    def __init__(self) -> None:
        self._event_read_fd, self._event_write_fd = os.pipe()
        os.set_blocking(self._event_read_fd, False)
        os.set_blocking(self._event_write_fd, False)
        try:
            self._input_fd: int | None = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            self._input_fd = None

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
        curses.init_pair(9, curses.COLOR_BLACK, curses.COLOR_YELLOW)
        curses.init_pair(10, curses.COLOR_MAGENTA, -1)

    def configure_escape_delay(self) -> None:
        try:
            curses.set_escdelay(500)
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

    def notify_job_state_changed(self) -> None:
        """Wake a UI wait after a background job changes state."""
        try:
            os.write(self._event_write_fd, b"\0")
        except (BlockingIOError, OSError):
            pass

    def wait_for_key_or_job_event(self, port: Any, timeout: float | None) -> int:
        """Wait for terminal input or a background-job notification."""
        port.screen.timeout(0)
        ch = self.read_key(port)
        if ch != -1:
            return ch

        readers = [self._event_read_fd]
        if self._input_fd is not None:
            readers.append(self._input_fd)
        try:
            ready, _, _ = select.select(readers, [], [], timeout)
        except InterruptedError:
            return -1

        if self._event_read_fd in ready:
            self._drain_job_events()
            return job_api.JOB_STATE_WAKE_KEY
        if self._input_fd is not None and self._input_fd in ready:
            port.screen.timeout(-1)
            return self.read_key(port)
        return -1

    def close_job_event_channel(self) -> None:
        """Close the wakeup pipe owned by this terminal controller."""
        for name in ("_event_read_fd", "_event_write_fd"):
            fd = getattr(self, name, -1)
            if fd < 0:
                continue
            try:
                os.close(fd)
            except OSError:
                pass
            setattr(self, name, -1)

    def _drain_job_events(self) -> None:
        while True:
            try:
                if not os.read(self._event_read_fd, 4096):
                    return
            except BlockingIOError:
                return
            except OSError:
                return

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

    def selected_warn_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(9) | curses.A_BOLD
        return curses.A_REVERSE | curses.A_BOLD

    def running_attr(self) -> int:
        return self.warn_attr()

    def group_attr(self) -> int:
        return curses.color_pair(4) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD

    def section_attr(self) -> int:
        return curses.color_pair(10) | curses.A_DIM if curses.has_colors() else curses.A_DIM

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
            "section": self.section_attr,
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

    def draw_box(
        self,
        port: Any,
        top: int,
        left: int,
        height: int,
        width: int,
        title: str = "",
        attr: int = 0,
        *,
        title_attr: int | None = None,
    ) -> None:
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
            resolved_title_attr = title_attr if title_attr is not None else attr or self.accent_attr()
            self.add(port, top, left + 2, f" {title} "[: max(0, width - 4)], resolved_title_attr)

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

    def copy_to_clipboard(self, text: str) -> bool:
        """Copy text with a desktop helper, falling back to terminal OSC 52."""
        if not text:
            return False
        commands: list[list[str]] = []
        if os.environ.get("DISPLAY") and shutil.which("xclip"):
            commands.append(["xclip", "-selection", "clipboard"])
        if os.environ.get("DISPLAY") and shutil.which("xsel"):
            commands.append(["xsel", "--clipboard", "--input"])
        if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
            commands.append(["wl-copy"])
        for command in commands:
            try:
                environment = os.environ.copy()
                for variable in (
                    "BAMF_DESKTOP_FILE_HINT",
                    "DESKTOP_STARTUP_ID",
                    "GIO_LAUNCHED_DESKTOP_FILE",
                    "GIO_LAUNCHED_DESKTOP_FILE_PID",
                    "STARTUP_ID",
                    "XDG_ACTIVATION_TOKEN",
                ):
                    environment.pop(variable, None)
                subprocess.run(
                    command,
                    input=text,
                    text=True,
                    check=True,
                    timeout=2,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=environment,
                )
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
            return True
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        sequence = f"\x1b]52;c;{payload}\x07"
        if os.environ.get("TMUX"):
            escaped = sequence.replace("\x1b", "\x1b\x1b")
            sequence = f"\x1bPtmux;{escaped}\x1b\\"
        try:
            sys.stdout.write(sequence)
            sys.stdout.flush()
        except (OSError, UnicodeError):
            return False
        return True


def terminal_port_controller() -> TerminalPortController:
    return TerminalPortController()
