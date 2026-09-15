from __future__ import annotations

import unittest
from components.ui.api import dialog_workflow
from components.ui.api import dialogs


class FakeScreen:
    def __init__(self, keys: list[int] | None = None, *, text: bytes = b"") -> None:
        self.keys = keys or []
        self.text = text
        self.timeouts: list[int] = []
        self.refresh_count = 0
        self.erase_count = 0
        self.height = 30
        self.width = 100
        self.getstr_calls: list[tuple[int, int]] = []
        self.move_calls: list[tuple[int, int]] = []

    def timeout(self, value: int) -> None:
        self.timeouts.append(value)

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def refresh(self) -> None:
        self.refresh_count += 1

    def erase(self) -> None:
        self.erase_count += 1

    def getstr(self, row: int, col: int) -> bytes:
        self.getstr_calls.append((row, col))
        return self.text

    def move(self, row: int, col: int) -> None:
        self.move_calls.append((row, col))


class FakePort:
    def __init__(self, keys: list[int] | None = None, *, text: bytes = b"") -> None:
        self.screen = FakeScreen(keys, text=text)
        self.render_cache = {"stale": "value"}
        self.main_full_redraw = False
        self.menu_dirty = False
        self.logs_dirty = False
        self.rows: list[tuple[int, int, str, int]] = []
        self.boxes: list[tuple[int, int, int, int, str]] = []
        self.draw_count = 0
        self.wrapped: list[str] = []
        self.cursor_states: list[bool] = []
        self.prompt_cancelled = False

    def read_key(self) -> int:
        if not self.screen.keys:
            raise AssertionError("fake key queue is empty")
        return self.screen.keys.pop(0)

    def read_queued_text(self, first_ch: int) -> str:
        if 32 <= first_ch < 127:
            return chr(first_ch)
        return ""

    def draw(self) -> None:
        self.draw_count += 1

    def draw_box(self, top: int, left: int, height: int, width: int, title: str = "", attr: int = 0) -> None:
        self.boxes.append((top, left, height, width, title))

    def add(self, y: int, x: int, text: str, attr: int = 0) -> None:
        self.rows.append((y, x, text, attr))

    def draw_wrapped(self, _y: int, _x: int, _width: int, text: str, _attr: int = 0, *, max_lines: int = 4) -> int:
        self.wrapped.append(text)
        return _y + 1

    def warn_attr(self) -> int:
        return 1

    def accent_attr(self) -> int:
        return 2

    def set_cursor(self, visible: bool) -> None:
        self.cursor_states.append(visible)


class DialogWorkflowControllerTests(unittest.TestCase):
    def test_run_confirm_dialog_accepts_and_closes_overlay(self) -> None:
        port = FakePort([ord("y")])
        controller = dialog_workflow.dialog_workflow_controller()

        result = controller.run_confirm_dialog(
            port,
            dialogs.ConfirmContent("Title", "Warning", "Subject", "Details", "Footer"),
        )

        self.assertTrue(result)
        self.assertEqual(port.draw_count, 1)
        self.assertEqual(port.screen.timeouts, [-1, 250])
        self.assertTrue(port.main_full_redraw)
        self.assertTrue(port.menu_dirty)
        self.assertTrue(port.logs_dirty)
        self.assertEqual(port.render_cache, {})

    def test_confirm_sync_action_does_not_redraw_background(self) -> None:
        port = FakePort([27])
        controller = dialog_workflow.dialog_workflow_controller()

        result = controller.confirm_sync_action(port, "Pull", "Pull mappings")

        self.assertFalse(result)
        self.assertEqual(port.draw_count, 0)
        self.assertIn("This action can change local or remote mapped files.", [row[2] for row in port.rows])

    def test_show_message_draws_screen_and_waits_for_return_key(self) -> None:
        port = FakePort([10])
        controller = dialog_workflow.dialog_workflow_controller()

        controller.show_message(port, "Action failed", ["boom", "details"])

        self.assertEqual(port.screen.erase_count, 1)
        self.assertIn("Action failed", [row[2] for row in port.rows])
        self.assertIn("boom", [row[2] for row in port.rows])
        self.assertEqual(port.screen.timeouts, [-1, 250])

    def test_prompt_returns_typed_value_and_restores_cursor_state(self) -> None:
        port = FakePort([ord("/"), ord("t"), ord("m"), ord("p"), 10])
        controller = dialog_workflow.dialog_workflow_controller()

        result = controller.prompt(port, "Path", "")

        self.assertEqual(result, "/tmp")
        self.assertFalse(port.prompt_cancelled)
        self.assertEqual(port.screen.getstr_calls, [])
        self.assertEqual(port.cursor_states, [True, False])

    def test_prompt_supports_backspace_delete_and_cancel(self) -> None:
        port = FakePort([ord("a"), ord("b"), 127, ord("c"), 10])
        controller = dialog_workflow.dialog_workflow_controller()

        result = controller.prompt(port, "Name", "")

        self.assertEqual(result, "ac")
        self.assertFalse(port.prompt_cancelled)

        cancel_port = FakePort([ord("x"), 27])
        cancelled = controller.prompt(cancel_port, "Name", "old")

        self.assertEqual(cancelled, "")
        self.assertTrue(cancel_port.prompt_cancelled)


if __name__ == "__main__":
    unittest.main()
