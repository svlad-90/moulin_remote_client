from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from components.app.api import terminal


class AppTerminalPortAdapterTests(unittest.TestCase):
    def test_terminal_adapter_owns_terminal_and_menu_state_port_methods(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            terminal_port = Mock()
            terminal_port.selected_attr.return_value = 7
            terminal_port.read_key.return_value = 113
            terminal_port.draw_wrapped.return_value = 4
            main_menu_state = Mock()
            main_menu_state.item_enabled.return_value = True
            main_menu_state.disabled_reason.return_value = ""
            main_menu_state.mapping_status_snapshot.return_value = {"sync": "ok"}
            port: Any = object()
            item: Any = object()
            adapter = terminal.app_terminal_port_adapter(
                app_dir=Path(tmpdir),
                terminal_port=terminal_port,
                main_menu_state=main_menu_state,
            )

            adapter.setup_colors()
            adapter.configure_escape_delay()
            adapter.configure_mouse()
            adapter.set_cursor(False)
            self.assertEqual(adapter.read_key(port), 113)
            adapter.unread_key(10)
            self.assertEqual(adapter.selected_attr(), 7)
            self.assertTrue(adapter.item_enabled(port, item))
            self.assertEqual(adapter.disabled_reason(port, item), "")
            adapter.add(port, 1, 2, "text", 3)
            adapter.add_segments(port, 1, 2, 10, [("a", 0)])
            adapter.draw_box(port, 1, 2, 3, 4, "T", 5)
            self.assertEqual(adapter.mapping_status_snapshot(port), {"sync": "ok"})
            self.assertEqual(adapter.draw_wrapped(port, 1, 2, 20, "text"), 4)
            adapter.suspend_tui()
            adapter.restore_tui(port)

            terminal_port.setup_colors.assert_called_once_with()
            terminal_port.configure_escape_delay.assert_called_once_with()
            terminal_port.configure_mouse.assert_called_once_with()
            terminal_port.set_cursor.assert_called_once_with(False)
            terminal_port.read_key.assert_called_once_with(port)
            terminal_port.unread_key.assert_called_once_with(10)
            main_menu_state.item_enabled.assert_called_once_with(port, item)
            main_menu_state.disabled_reason.assert_called_once_with(port, item)
            terminal_port.add.assert_called_once_with(port, 1, 2, "text", 3)
            terminal_port.add_segments.assert_called_once_with(port, 1, 2, 10, [("a", 0)])
            terminal_port.draw_box.assert_called_once_with(port, 1, 2, 3, 4, "T", 5)
            main_menu_state.mapping_status_snapshot.assert_called_once_with(port)
            terminal_port.draw_wrapped.assert_called_once_with(port, 1, 2, 20, "text", 0, 4)
            terminal_port.suspend_tui.assert_called_once_with()
            terminal_port.restore_tui.assert_called_once_with(port)


if __name__ == "__main__":
    unittest.main()
