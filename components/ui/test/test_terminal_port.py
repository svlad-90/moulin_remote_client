from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from components.ui.api import input as ui_input
from components.ui.api import terminal_port


class FakeCursesError(Exception):
    pass


class FakeCurses:
    error = FakeCursesError
    COLOR_BLACK = 0
    COLOR_CYAN = 6
    COLOR_YELLOW = 3
    COLOR_GREEN = 2
    COLOR_RED = 1
    COLOR_WHITE = 7
    COLOR_BLUE = 4
    A_BOLD = 100
    A_REVERSE = 200
    A_DIM = 400

    def __init__(self, *, has_colors: bool = True) -> None:
        self._has_colors = has_colors
        self.calls: list[tuple[str, Any]] = []
        self.unget: list[Any] = []

    def has_colors(self) -> bool:
        return self._has_colors

    def start_color(self) -> None:
        self.calls.append(("start_color", None))

    def use_default_colors(self) -> None:
        self.calls.append(("use_default_colors", None))

    def init_pair(self, pair: int, fg: int, bg: int) -> None:
        self.calls.append(("init_pair", (pair, fg, bg)))

    def color_pair(self, pair: int) -> int:
        return pair * 1000

    def set_escdelay(self, value: int) -> None:
        self.calls.append(("set_escdelay", value))

    def curs_set(self, value: int) -> None:
        self.calls.append(("curs_set", value))

    def unget_wch(self, value: str) -> None:
        self.unget.append(("wch", value))

    def ungetch(self, value: int) -> None:
        self.unget.append(("ch", value))

    def def_prog_mode(self) -> None:
        self.calls.append(("def_prog_mode", None))

    def endwin(self) -> None:
        self.calls.append(("endwin", None))

    def reset_prog_mode(self) -> None:
        self.calls.append(("reset_prog_mode", None))


class FakeScreen:
    def __init__(self, keys: list[Any] | None = None) -> None:
        self.keys = list(keys or [])
        self.adds: list[tuple[int, int, str, int]] = []
        self.timeouts: list[int] = []
        self.keypad_values: list[bool] = []

    def get_wch(self) -> Any:
        if not self.keys:
            raise FakeCursesError()
        return self.keys.pop(0)

    def getch(self) -> int:
        if not self.keys:
            return -1
        return int(self.keys.pop(0))

    def addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
        self.adds.append((y, x, text, attr))

    def timeout(self, value: int) -> None:
        self.timeouts.append(value)

    def keypad(self, value: bool) -> None:
        self.keypad_values.append(value)


class FakePort:
    def __init__(self, keys: list[Any] | None = None) -> None:
        self.screen = FakeScreen(keys)
        self.controller = terminal_port.terminal_port_controller()

    def read_key(self) -> int:
        return self.controller.read_key(self)

    def unread_key(self, ch: int) -> None:
        self.controller.unread_key(ch)


class TerminalPortControllerTests(unittest.TestCase):
    def test_setup_colors_initializes_current_pairs(self) -> None:
        fake_curses = FakeCurses()

        with patch("components.ui.src.terminal_port.curses", fake_curses):
            terminal_port.terminal_port_controller().setup_colors()

        self.assertEqual(fake_curses.calls[0], ("start_color", None))
        self.assertEqual(fake_curses.calls[1], ("use_default_colors", None))
        self.assertIn(("init_pair", (1, fake_curses.COLOR_BLACK, fake_curses.COLOR_CYAN)), fake_curses.calls)
        self.assertIn(("init_pair", (8, fake_curses.COLOR_BLACK, fake_curses.COLOR_GREEN)), fake_curses.calls)

    def test_read_key_encodes_text_and_handles_empty_queue(self) -> None:
        fake_curses = FakeCurses()
        port = FakePort(["ф", 260])

        with patch("components.ui.src.terminal_port.curses", fake_curses):
            controller = terminal_port.terminal_port_controller()
            self.assertEqual(controller.read_key(port), ui_input.TEXT_KEY_OFFSET + ord("ф"))
            self.assertEqual(controller.read_key(port), 260)
            self.assertEqual(controller.read_key(port), -1)

    def test_read_queued_text_collects_text_and_unreads_non_text(self) -> None:
        fake_curses = FakeCurses()
        port = FakePort(["b", 10])

        with patch("components.ui.src.terminal_port.curses", fake_curses):
            text = terminal_port.terminal_port_controller().read_queued_text(port, ord("a"))

        self.assertEqual(text, "ab")
        self.assertEqual(port.screen.timeouts, [0, -1])
        self.assertEqual(fake_curses.unget, [("ch", 10)])

    def test_draw_box_and_segments_write_expected_cells(self) -> None:
        fake_curses = FakeCurses()
        port = FakePort()

        with patch("components.ui.src.terminal_port.curses", fake_curses):
            controller = terminal_port.terminal_port_controller()
            controller.add_segments(port, 0, 0, 5, [("hello", 1), ("world", 2)])
            controller.draw_box(port, 1, 2, 3, 6, "T", 9)

        self.assertIn((0, 0, "hello", 1), port.screen.adds)
        self.assertIn((1, 2, "+----+", 9), port.screen.adds)
        self.assertIn((1, 4, " T", 9), port.screen.adds)

    def test_draw_label_value_wrapped_uses_layout_and_text_wrapping(self) -> None:
        fake_curses = FakeCurses()
        port = FakePort()

        with patch("components.ui.src.terminal_port.curses", fake_curses):
            controller = terminal_port.terminal_port_controller()
            end_row = controller.draw_label_value_wrapped(port, 2, 4, 20, "Name", "alpha beta gamma", max_lines=2)

        self.assertEqual(end_row, 4)
        self.assertEqual(port.screen.adds[0], (2, 4, "Name:   ", 2036))
        self.assertEqual(port.screen.adds[1][2], "alpha beta")
        self.assertEqual(port.screen.adds[2][2], "gamma")

    def test_suspend_and_restore_delegate_to_curses_and_screen(self) -> None:
        fake_curses = FakeCurses()
        port = FakePort()

        with patch("components.ui.src.terminal_port.curses", fake_curses):
            controller = terminal_port.terminal_port_controller()
            controller.suspend_tui()
            controller.restore_tui(port)

        self.assertEqual(fake_curses.calls, [("def_prog_mode", None), ("endwin", None), ("reset_prog_mode", None)])
        self.assertEqual(port.screen.keypad_values, [True])
        self.assertEqual(port.screen.timeouts, [250])


if __name__ == "__main__":
    unittest.main()
