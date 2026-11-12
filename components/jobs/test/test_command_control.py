from __future__ import annotations

import io
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
        self.stdin: io.BytesIO | None = None

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

    def test_stop_running_build_sends_ctrl_c_and_waits_for_exit(self) -> None:
        port = FakeControlPort()
        port.active_job = jobs.create_command_job(
            title="Build",
            item_label="Build",
            slot="build",
            commands=[],
        )
        process = FakeProcess(None, pid=4321)
        process.stdin = io.BytesIO()
        port.active_job["process"] = process
        port.active_job["current_stop_mode"] = "pty-interrupt"
        terminations: list[tuple[int, int]] = []
        service = command_control.CommandControlService(
            now=lambda: 12.0,
            terminate_process_group=lambda pid, sig: terminations.append((pid, sig)),
        )

        service.stop_running_command(port, "build")

        self.assertEqual(process.stdin.getvalue(), b"\x03")
        self.assertEqual(terminations, [])
        self.assertEqual(port.status, "Waiting for command to stop")
        self.assertIn("graceful stop requested: Ctrl-C", jobs.job_output_lines(port.active_job))

        service.stop_running_command(port, "build")

        self.assertEqual(terminations, [(4321, signal.SIGTERM)])
        self.assertEqual(port.status, "Forced SSH stop requested")
        self.assertIn("forced SSH stop requested: SIGTERM", jobs.job_output_lines(port.active_job))

    def test_stop_running_build_falls_back_when_ctrl_c_pipe_is_closed(self) -> None:
        port = FakeControlPort()
        port.active_job = jobs.create_command_job(
            title="Build",
            item_label="Build",
            slot="build",
            commands=[],
        )
        process = FakeProcess(None, pid=4321)
        process.stdin = io.BytesIO()
        process.stdin.close()
        port.active_job["process"] = process
        port.active_job["current_stop_mode"] = "pty-interrupt"
        terminations: list[tuple[int, int]] = []
        service = command_control.CommandControlService(
            now=lambda: 12.0,
            terminate_process_group=lambda pid, sig: terminations.append((pid, sig)),
        )

        service.stop_running_command(port, "build")

        self.assertEqual(terminations, [(4321, signal.SIGTERM)])
        self.assertEqual(port.active_job["stop_phase"], "terminate")
        self.assertEqual(port.status, "Stop requested")
        self.assertIn(
            "Ctrl-C unavailable: stopping SSH with SIGTERM",
            jobs.job_output_lines(port.active_job),
        )

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

    def test_cancel_connection_job_terminates_and_releases_build_slot(self) -> None:
        port = FakeControlPort()
        port.active_job = jobs.create_build_connect_job(
            item_label="Connect build host",
            command=["ssh", "old-host"],
            started_at=1.0,
        )
        old_job = port.active_job
        old_job["process"] = FakeProcess(None, pid=4321)
        terminations: list[tuple[int, int]] = []
        service = command_control.CommandControlService(
            terminate_process_group=lambda pid, sig: terminations.append((pid, sig)),
        )

        cancelled = service.cancel_connection_job(port, "build")

        self.assertTrue(cancelled)
        self.assertEqual(terminations, [(4321, signal.SIGTERM)])
        self.assertIsNone(port.active_job)
        self.assertIs(port.last_job, old_job)
        self.assertIn("cancelled: host selection changed", jobs.job_output_lines(old_job))

    def test_cancel_connection_job_preserves_non_connection_build(self) -> None:
        port = FakeControlPort()
        port.active_job = jobs.create_command_job(
            title="Build",
            item_label="Build",
            slot="build",
            commands=[],
        )
        service = command_control.CommandControlService(
            terminate_process_group=lambda _pid, _sig: None,
        )

        self.assertFalse(service.cancel_connection_job(port, "build"))
        self.assertIsNotNone(port.active_job)


if __name__ == "__main__":
    unittest.main()
