from __future__ import annotations

import unittest
from typing import Any

from components.ui.api import action_execution
from components.ui.api.menu import MenuItem


class FakeActionPort:
    def __init__(self, item: MenuItem) -> None:
        self.items = [item]
        self.selected = 0
        self.status = ""
        self.action_running = False
        self.active_job: dict[str, Any] | None = None
        self.board_job: dict[str, Any] | None = None
        self.enabled = True
        self.disabled_status = "disabled"
        self.menu_dirty = False
        self.main_full_redraw = False
        self.logs_dirty = False
        self.handler_calls = 0

    def item_enabled(self, _item: MenuItem) -> bool:
        return self.enabled

    def disabled_reason(self, _item: MenuItem) -> str:
        return self.disabled_status


class Harness:
    def __init__(self, *, confirm: bool = True) -> None:
        self.confirm = confirm
        self.confirm_requests: list[Any] = []
        self.messages: list[tuple[str, list[str]]] = []
        self.refresh_count = 0
        self.controller = action_execution.ActionExecutionController(
            confirm_dialog=self.confirm_dialog,
            show_message=self.show_message,
            refresh_after_action=self.refresh,
        )

    def confirm_dialog(self, content: Any) -> bool:
        self.confirm_requests.append(content)
        return self.confirm

    def show_message(self, title: str, lines: list[str]) -> None:
        self.messages.append((title, lines))

    def refresh(self) -> None:
        self.refresh_count += 1


def item(label: str = "Run", *, confirm: bool = False, handler: Any | None = None) -> MenuItem:
    if handler is None:
        def handler(port: FakeActionPort) -> None:
            port.handler_calls += 1

    return MenuItem(label, "commands", "description", lambda _app: "", handler, confirm=confirm)


class ActionExecutionControllerTests(unittest.TestCase):
    def test_run_selected_executes_enabled_action_and_marks_ui_dirty(self) -> None:
        port = FakeActionPort(item())
        harness = Harness()

        harness.controller.run_selected(port)

        self.assertEqual(port.handler_calls, 1)
        self.assertEqual(harness.refresh_count, 1)
        self.assertTrue(port.menu_dirty)
        self.assertTrue(port.main_full_redraw)
        self.assertTrue(port.logs_dirty)

    def test_run_selected_reports_disabled_action_without_refreshing(self) -> None:
        port = FakeActionPort(item())
        port.enabled = False
        port.disabled_status = "connect first"
        harness = Harness()

        harness.controller.run_selected(port)

        self.assertEqual(port.status, "connect first")
        self.assertEqual(port.handler_calls, 0)
        self.assertEqual(harness.refresh_count, 0)

    def test_run_selected_reports_running_item_without_refreshing(self) -> None:
        port = FakeActionPort(item("Build"))
        port.active_job = {"item_label": "Build"}
        harness = Harness()

        harness.controller.run_selected(port)

        self.assertEqual(port.status, "Command is already running; live log is shown in Logs")
        self.assertEqual(port.handler_calls, 0)
        self.assertEqual(harness.refresh_count, 0)

    def test_run_selected_cancelled_confirmation_does_not_refresh(self) -> None:
        port = FakeActionPort(item("Danger", confirm=True))
        harness = Harness(confirm=False)

        harness.controller.run_selected(port)

        self.assertEqual(len(harness.confirm_requests), 1)
        self.assertEqual(port.status, "Cancelled: Danger")
        self.assertEqual(port.handler_calls, 0)
        self.assertEqual(harness.refresh_count, 0)

    def test_run_selected_reports_system_exit_and_refreshes(self) -> None:
        def fail(_port: FakeActionPort) -> None:
            raise SystemExit("boom")

        port = FakeActionPort(item("Fail", handler=fail))
        harness = Harness()

        harness.controller.run_selected(port)

        self.assertEqual(port.status, "Fail: failed")
        self.assertEqual(harness.messages, [("Action failed", ["boom"])])
        self.assertEqual(harness.refresh_count, 1)
        self.assertTrue(port.logs_dirty)

    def test_run_selected_reports_exception_and_refreshes(self) -> None:
        def fail(_port: FakeActionPort) -> None:
            raise RuntimeError("bad")

        port = FakeActionPort(item("Explode", handler=fail))
        harness = Harness()

        harness.controller.run_selected(port)

        self.assertEqual(port.status, "Explode: failed")
        self.assertEqual(harness.messages, [("Action failed", ["bad"])])
        self.assertEqual(harness.refresh_count, 1)


if __name__ == "__main__":
    unittest.main()
