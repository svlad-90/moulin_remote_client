from __future__ import annotations

import unittest
from typing import Any

from components.ui.api import main_run_loop


class FakeScreen:
    def __init__(self, keys: list[int]) -> None:
        self.keys = keys
        self.keypad_values: list[bool] = []
        self.timeouts: list[int] = []

    def keypad(self, value: bool) -> None:
        self.keypad_values.append(value)

    def timeout(self, value: int) -> None:
        self.timeouts.append(value)


class FakeConnectionWorkflow:
    def __init__(self, events: list[str]) -> None:
        self.auto_connect_calls = 0
        self.events = events

    def auto_connect(self, _port: Any) -> None:
        self.auto_connect_calls += 1
        self.events.append("auto-connect")


class FakePort:
    def __init__(self, keys: list[int]) -> None:
        self.screen = FakeScreen(keys)
        self.done = False
        self.active_job: dict[str, Any] | None = None
        self.board_job: dict[str, Any] | None = None
        self.selected = 0
        self.events: list[str] = []
        self.connection_workflow = FakeConnectionWorkflow(self.events)
        self.configure_calls = 0
        self.cursor_values: list[bool] = []
        self.draw_calls = 0
        self.poll_calls = 0
        self.key_calls: list[int] = []
        self.profile_events: list[str] = []
        self.flush_calls = 0

    def configure_escape_delay(self) -> None:
        self.configure_calls += 1

    def set_cursor(self, value: bool) -> None:
        self.cursor_values.append(value)

    def connection_workflow_service(self) -> FakeConnectionWorkflow:
        return self.connection_workflow

    def draw(self) -> None:
        self.draw_calls += 1
        self.events.append("draw")

    def poll_active_jobs(self) -> None:
        self.poll_calls += 1

    def read_key(self) -> int:
        if not self.screen.keys:
            raise AssertionError("fake key queue is empty")
        return self.screen.keys.pop(0)

    def handle_main_key(self, ch: int) -> None:
        self.key_calls.append(ch)
        self.done = True

    def ui_profile_slow(self, event: str, _started: float, **_fields: Any) -> float:
        self.profile_events.append(event)
        return 0.0

    def flush_ui_profile(self) -> None:
        self.flush_calls += 1


class MainRunLoopControllerTests(unittest.TestCase):
    def test_run_initializes_screen_autoconnects_and_handles_key(self) -> None:
        port = FakePort([ord("q")])
        controller = main_run_loop.main_run_loop_controller(
            auto_connect_enabled=True,
            sleep=lambda _seconds: None,
            monotonic=lambda: 1.0,
        )

        controller.run(port)

        self.assertEqual(port.configure_calls, 1)
        self.assertEqual(port.cursor_values, [False])
        self.assertEqual(port.screen.keypad_values, [True])
        self.assertEqual(port.connection_workflow.auto_connect_calls, 1)
        self.assertEqual(port.events[:2], ["draw", "auto-connect"])
        self.assertEqual(port.key_calls, [ord("q")])
        self.assertEqual(port.draw_calls, 2)
        self.assertEqual(port.poll_calls, 1)
        self.assertEqual(port.flush_calls, 1)
        self.assertIn("draw-initial", port.profile_events)
        self.assertIn("draw-after-input-slow", port.profile_events)

    def test_idle_timeout_redraws_and_sleeps_before_next_key(self) -> None:
        sleeps: list[float] = []
        port = FakePort([-1, ord("q")])
        controller = main_run_loop.main_run_loop_controller(
            auto_connect_enabled=False,
            sleep=sleeps.append,
            monotonic=lambda: 1.0,
        )

        controller.run(port)

        self.assertEqual(sleeps, [0.05])
        self.assertEqual(port.draw_calls, 3)
        self.assertEqual(port.poll_calls, 2)
        self.assertEqual(port.screen.timeouts, [250, 250, 250])
        self.assertIn("draw-idle-slow", port.profile_events)

    def test_active_job_uses_short_input_timeout(self) -> None:
        port = FakePort([ord("q")])
        port.active_job = {"title": "running"}
        controller = main_run_loop.main_run_loop_controller(
            auto_connect_enabled=False,
            sleep=lambda _seconds: None,
            monotonic=lambda: 1.0,
        )

        controller.run(port)

        self.assertEqual(port.screen.timeouts, [250, 50])


if __name__ == "__main__":
    unittest.main()
