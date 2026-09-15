from __future__ import annotations

import signal
import unittest
from dataclasses import dataclass
from typing import Any

from components.jobs.api import command_control
from components.jobs.api import jobs


@dataclass
class FakeMenuItem:
    label: str


class FakeProcess:
    def __init__(self, rc: int | None, *, pid: int = 1234) -> None:
        self.rc = rc
        self.pid = pid

    def poll(self) -> int | None:
        return self.rc


class FakeControlPort:
    def __init__(self) -> None:
        self.items = [FakeMenuItem("Build"), FakeMenuItem("Flash UFS image")]
        self.selected = 0
        self.status = ""
        self.logs_dirty = False
        self.menu_dirty = False
        self.main_full_redraw = False
        self.active_job: dict[str, Any] | None = None
        self.board_job: dict[str, Any] | None = None
        self.last_job: dict[str, Any] | None = None
        self.last_board_job: dict[str, Any] | None = None
        self.last_exit: int | None = None


class CommandControlServiceTests(unittest.TestCase):
    def test_stop_running_preview_uses_selected_running_job(self) -> None:
        port = FakeControlPort()
        port.active_job = jobs.create_command_job(
            title="Build",
            item_label="Build",
            slot="build",
            commands=[],
        )
        service = command_control.CommandControlService(
            now=lambda: 12.0,
            terminate_process_group=lambda _pid, _sig: None,
        )

        self.assertEqual(service.stop_running_preview(port), "Stop active command: Build")

    def test_stop_running_command_requests_sigterm_for_live_process(self) -> None:
        port = FakeControlPort()
        port.active_job = jobs.create_command_job(
            title="Build",
            item_label="Build",
            slot="build",
            commands=[],
        )
        port.active_job["process"] = FakeProcess(None, pid=4321)
        terminations: list[tuple[int, int]] = []
        service = command_control.CommandControlService(
            now=lambda: 12.0,
            terminate_process_group=lambda pid, sig: terminations.append((pid, sig)),
        )

        service.stop_running_command(port, "build")

        self.assertEqual(terminations, [(4321, signal.SIGTERM)])
        self.assertEqual(port.status, "Stop requested")
        self.assertTrue(port.logs_dirty)
        self.assertIn("stop requested: SIGTERM", jobs.job_output_lines(port.active_job))

    def test_stop_running_command_finishes_job_without_live_process(self) -> None:
        port = FakeControlPort()
        port.active_job = jobs.create_command_job(
            title="Build",
            item_label="Build",
            slot="build",
            commands=[],
        )
        service = command_control.CommandControlService(
            now=lambda: 12.0,
            terminate_process_group=lambda _pid, _sig: None,
        )

        service.stop_running_command(port, "build")

        self.assertIsNone(port.active_job)
        self.assertEqual(port.last_job["title"], "Build")
        self.assertEqual(port.last_exit, 130)
        self.assertEqual(port.status, "Build: stopped")
        self.assertTrue(port.logs_dirty)

    def test_stop_running_command_reports_missing_job(self) -> None:
        port = FakeControlPort()
        service = command_control.CommandControlService(
            now=lambda: 12.0,
            terminate_process_group=lambda _pid, _sig: None,
        )

        service.stop_running_command(port, "board")

        self.assertEqual(port.status, "No board command is running")


if __name__ == "__main__":
    unittest.main()
