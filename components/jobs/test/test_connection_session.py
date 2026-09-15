from __future__ import annotations

import unittest
from typing import Any

from components.jobs.api import connection_session


class FakeSessionPort:
    def __init__(self) -> None:
        self.status = ""
        self.action_running = False
        self.active_job: dict[str, Any] | None = None
        self.board_job: dict[str, Any] | None = None
        self.connection_state = "disconnected"
        self.board_connection_state = "disconnected"
        self.auto_connect_done = False
        self.pending_auto_board_connect = False


def config(*, build: bool = True, board: bool = True) -> dict[str, Any]:
    return {
        "remote": {"name": "build", "user": "builder" if build else "", "host": "10.0.0.1" if build else ""},
        "board_host": {"name": "board", "user": "tester" if board else "", "host": "10.0.0.2" if board else ""},
    }


class Harness:
    def __init__(self, *, confirm: bool = True, cfg: dict[str, Any] | None = None) -> None:
        self.confirm = confirm
        self.confirm_requests: list[Any] = []
        self.draw_count = 0
        self.build_starts = 0
        self.board_starts = 0
        self.controller = connection_session.ConnectionSessionController(
            cfg if cfg is not None else config(),
            confirm_dialog=self.confirm_dialog,
            draw=self.draw,
            start_build_host_connect=self.start_build,
            start_board_host_connect=self.start_board,
        )

    def confirm_dialog(self, content: Any) -> bool:
        self.confirm_requests.append(content)
        return self.confirm

    def draw(self) -> None:
        self.draw_count += 1

    def start_build(self) -> None:
        self.build_starts += 1

    def start_board(self) -> None:
        self.board_starts += 1


class ConnectionSessionControllerTests(unittest.TestCase):
    def test_toggle_build_host_starts_connect_when_disconnected(self) -> None:
        port = FakeSessionPort()
        harness = Harness()

        harness.controller.toggle_build_host(port)

        self.assertEqual(harness.build_starts, 1)
        self.assertEqual(harness.board_starts, 0)
        self.assertEqual(harness.confirm_requests, [])

    def test_toggle_build_host_disconnects_after_confirmation(self) -> None:
        port = FakeSessionPort()
        port.connection_state = "connected"
        harness = Harness(confirm=True)

        harness.controller.toggle_build_host(port)

        self.assertEqual(len(harness.confirm_requests), 1)
        self.assertEqual(harness.draw_count, 1)
        self.assertFalse(port.action_running)
        self.assertEqual(port.connection_state, "disconnected")
        self.assertEqual(port.status, "Disconnected")

    def test_toggle_board_host_cancel_keeps_connection(self) -> None:
        port = FakeSessionPort()
        port.board_connection_state = "connected"
        harness = Harness(confirm=False)

        harness.controller.toggle_board_host(port)

        self.assertEqual(len(harness.confirm_requests), 1)
        self.assertEqual(harness.draw_count, 0)
        self.assertEqual(port.board_connection_state, "connected")
        self.assertEqual(port.status, "Cancelled: Disconnect board host")

    def test_toggle_build_host_reports_missing_ssh_config(self) -> None:
        port = FakeSessionPort()
        harness = Harness(cfg=config(build=False))

        harness.controller.toggle_build_host(port)

        self.assertEqual(port.status, "set SSH user first")
        self.assertEqual(harness.build_starts, 0)

    def test_auto_connect_prefers_build_host_and_marks_board_pending(self) -> None:
        port = FakeSessionPort()
        harness = Harness()

        harness.controller.auto_connect(port)

        self.assertTrue(port.auto_connect_done)
        self.assertTrue(port.pending_auto_board_connect)
        self.assertEqual(harness.build_starts, 1)
        self.assertEqual(harness.board_starts, 0)

    def test_auto_connect_starts_board_only_when_build_host_is_not_configured(self) -> None:
        port = FakeSessionPort()
        harness = Harness(cfg=config(build=False, board=True))

        harness.controller.auto_connect(port)

        self.assertTrue(port.auto_connect_done)
        self.assertFalse(port.pending_auto_board_connect)
        self.assertEqual(harness.build_starts, 0)
        self.assertEqual(harness.board_starts, 1)

    def test_start_pending_auto_board_connect_clears_pending_and_starts_board(self) -> None:
        port = FakeSessionPort()
        port.pending_auto_board_connect = True
        harness = Harness()

        started = harness.controller.start_pending_auto_board_connect(port)

        self.assertTrue(started)
        self.assertFalse(port.pending_auto_board_connect)
        self.assertEqual(harness.board_starts, 1)

    def test_start_pending_auto_board_connect_clears_pending_when_board_busy(self) -> None:
        port = FakeSessionPort()
        port.pending_auto_board_connect = True
        port.board_job = {"title": "Flash"}
        harness = Harness()

        started = harness.controller.start_pending_auto_board_connect(port)

        self.assertFalse(started)
        self.assertFalse(port.pending_auto_board_connect)
        self.assertEqual(harness.board_starts, 0)


if __name__ == "__main__":
    unittest.main()
