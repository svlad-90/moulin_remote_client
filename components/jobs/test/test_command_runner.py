from __future__ import annotations

import unittest
from typing import Any

from components.jobs.api import command_runner
from components.ui.api.menu import MenuItem


def _preview(_app: Any) -> str:
    return ""


def _handler(_app: Any) -> None:
    return None


class FakeRunnerPort:
    def __init__(self, item: MenuItem) -> None:
        self.items = [item]
        self.selected = 0
        self.status = ""
        self.focus_panel = ""
        self.action_running = False
        self.logs_dirty = False
        self.menu_dirty = False
        self.main_full_redraw = False
        self.active_job: dict[str, Any] | None = None
        self.board_job: dict[str, Any] | None = None


class CommandRunnerServiceTests(unittest.TestCase):
    def test_start_commands_creates_build_job_and_applies_started_state(self) -> None:
        port = FakeRunnerPort(MenuItem("Run product build", "build commands", "", _preview, _handler))
        started: list[dict[str, Any]] = []

        rc = command_runner.command_runner_service().start_commands(
            port,
            "Run product build",
            [["ninja", "full_ufs.img.gz"]],
            start_next_command=started.append,
        )

        self.assertEqual(rc, 0)
        self.assertIs(port.active_job, started[0])
        self.assertIsNone(port.board_job)
        self.assertEqual(port.active_job["slot"], "build")
        self.assertEqual(port.active_job["item_label"], "Run product build")
        self.assertEqual(port.status, "Running: Run product build")
        self.assertEqual(port.focus_panel, "actions")
        self.assertTrue(port.logs_dirty)
        self.assertTrue(port.menu_dirty)
        self.assertTrue(port.main_full_redraw)

    def test_start_commands_creates_board_job_for_board_menu_item(self) -> None:
        port = FakeRunnerPort(MenuItem("Flash UFS image", "board commands", "", _preview, _handler))
        started: list[dict[str, Any]] = []

        rc = command_runner.command_runner_service().start_commands(
            port,
            "Flash UFS image",
            [["ssh", "board", "flash"]],
            start_next_command=started.append,
        )

        self.assertEqual(rc, 0)
        self.assertIs(port.board_job, started[0])
        self.assertIsNone(port.active_job)
        self.assertEqual(port.board_job["slot"], "board")
        self.assertEqual(port.status, "Running: Flash UFS image")

    def test_start_commands_reports_busy_slot_without_starting_next_command(self) -> None:
        port = FakeRunnerPort(MenuItem("Run product build", "build commands", "", _preview, _handler))
        port.active_job = {"title": "Existing"}
        started: list[dict[str, Any]] = []

        rc = command_runner.command_runner_service().start_commands(
            port,
            "Run product build",
            [["ninja"]],
            start_next_command=started.append,
        )

        self.assertEqual(rc, 1)
        self.assertEqual(port.status, "Another build action is already running")
        self.assertEqual(started, [])

    def test_start_commands_allows_parallel_different_job_slots(self) -> None:
        port = FakeRunnerPort(MenuItem("Flash UFS image", "board commands", "", _preview, _handler))
        port.active_job = {"title": "Run product build"}
        started: list[dict[str, Any]] = []

        rc = command_runner.command_runner_service().start_commands(
            port,
            "Flash UFS image",
            [["ssh", "board", "flash"]],
            start_next_command=started.append,
        )

        self.assertEqual(rc, 0)
        self.assertIs(port.board_job, started[0])
        self.assertEqual(port.active_job, {"title": "Run product build"})
        self.assertEqual(port.status, "Running: Flash UFS image")


if __name__ == "__main__":
    unittest.main()
