from __future__ import annotations

import signal
import unittest
from typing import Any

from components.jobs.api import command_lifecycle
from components.jobs.api import jobs


class FakeProcess:
    def __init__(self, rc: int | None, *, pid: int = 1234) -> None:
        self.rc = rc
        self.pid = pid

    def poll(self) -> int | None:
        return self.rc


class FakePort:
    def __init__(self) -> None:
        self.status = ""
        self.logs_dirty = False
        self.menu_dirty = False
        self.main_full_redraw = False
        self.last_exit: int | None = None
        self.active_job: dict[str, Any] | None = None
        self.board_job: dict[str, Any] | None = None
        self.last_job: dict[str, Any] | None = None
        self.last_board_job: dict[str, Any] | None = None
        self.last_jobs_by_label: dict[str, dict[str, Any]] = {}
        self.last_board_jobs_by_label: dict[str, dict[str, Any]] = {}
        self.preflight = "not run"
        self.preflight_values: dict[str, str] = {}
        self.connection_state = "disconnected"
        self.board_auto_connect_count = 0
        self.render_cache: dict[str, Any] = {"header": "cached"}

    def start_pending_auto_board_connect(self) -> bool:
        self.board_auto_connect_count += 1
        return True


def _service(
    *,
    now: float = 10.0,
    terminations: list[tuple[int, int]] | None = None,
    sleeps: list[float] | None = None,
    started: list[tuple[dict[str, Any], list[str]]] | None = None,
) -> command_lifecycle.CommandLifecycleService:
    if terminations is None:
        terminations = []
    if sleeps is None:
        sleeps = []
    if started is None:
        started = []

    def start_command(job: dict[str, Any], command: list[str], mark_dirty: Any) -> None:
        started.append((job, command))
        job["process"] = FakeProcess(None)
        mark_dirty()

    return command_lifecycle.CommandLifecycleService(
        now=lambda: now,
        sleep=sleeps.append,
        terminate_process_group=lambda pid, sig: terminations.append((pid, sig)),
        display_command=lambda command: " ".join(command),
        display_command_lines=lambda command: ["command: " + " ".join(command)],
        format_preflight=lambda output: ("ok", {"raw": output}),
        start_pending_auto_board_connect=lambda port: port.start_pending_auto_board_connect(),
        start_command_process=start_command,
    )


class CommandLifecycleServiceTests(unittest.TestCase):
    def test_start_next_command_starts_first_command_and_logs_step(self) -> None:
        port = FakePort()
        job = jobs.create_command_job(
            title="Build",
            item_label="Run product build",
            slot="build",
            commands=[["ninja", "full_ufs.img.gz"]],
        )
        started: list[tuple[dict[str, Any], list[str]]] = []

        _service(started=started).start_next_command(port, job)

        self.assertEqual(started, [(job, ["ninja", "full_ufs.img.gz"])])
        self.assertTrue(port.logs_dirty)
        self.assertEqual(
            jobs.job_output_lines(job),
            [
                "====================================",
                "Starting step 1/1: Run product build",
                "====================================",
                "",
                "command: ninja full_ufs.img.gz",
            ],
        )

    def test_start_next_command_finishes_completed_sequence_and_resets_preflight_when_needed(self) -> None:
        port = FakePort()
        job = jobs.create_command_job(
            title="Prepare remote project",
            item_label="Prepare remote project",
            slot="build",
            commands=[],
        )
        port.active_job = job

        _service().start_next_command(port, job)

        self.assertIsNone(port.active_job)
        self.assertIs(port.last_job, job)
        self.assertIs(port.last_jobs_by_label["Prepare remote project"], job)
        self.assertEqual(port.status, "Prepare remote project: done; reconnect to refresh preflight")
        self.assertEqual(port.preflight, "not run")
        self.assertNotIn("header", port.render_cache)

    def test_poll_job_advances_successful_command_step(self) -> None:
        port = FakePort()
        job = jobs.create_command_job(
            title="Build",
            item_label="Run product build",
            slot="build",
            commands=[["one"], ["two"]],
        )
        job["process"] = FakeProcess(0)
        started: list[tuple[dict[str, Any], list[str]]] = []

        _service(started=started).poll_job(port, job)

        self.assertEqual(job["index"], 1)
        self.assertEqual(started, [(job, ["two"])])
        self.assertIn("exit: 0", jobs.job_output_lines(job))
        self.assertTrue(port.logs_dirty)

    def test_poll_job_finishes_failed_command(self) -> None:
        port = FakePort()
        job = jobs.create_command_job(
            title="Build",
            item_label="Run product build",
            slot="build",
            commands=[["ninja"]],
        )
        job["process"] = FakeProcess(2)
        port.active_job = job

        _service().poll_job(port, job)

        self.assertIsNone(port.active_job)
        self.assertIs(port.last_job, job)
        self.assertIs(port.last_jobs_by_label["Run product build"], job)
        self.assertEqual(port.last_exit, 2)
        self.assertEqual(port.status, "Build: exit 2")

    def test_poll_job_handles_connect_completion_and_preflight(self) -> None:
        port = FakePort()
        job = jobs.create_build_connect_job(
            item_label="Connect build host",
            command=["ssh", "build"],
            started_at=0.0,
        )
        job["process"] = FakeProcess(0)
        jobs.append_job_output(job, "preflight line")
        port.active_job = job

        _service().poll_job(port, job)

        self.assertIsNone(port.active_job)
        self.assertEqual(port.preflight, "ok")
        self.assertEqual(port.preflight_values, {"raw": "Starting remote preflight...\npreflight line\nexit: 0"})
        self.assertEqual(port.connection_state, "connected")
        self.assertEqual(port.board_auto_connect_count, 1)

    def test_poll_job_terminates_connect_timeout_and_autoconnects_board(self) -> None:
        port = FakePort()
        job = jobs.create_build_connect_job(
            item_label="Connect build host",
            command=["ssh", "build"],
            started_at=0.0,
        )
        job["timeout"] = 1.0
        job["process"] = FakeProcess(None, pid=77)
        port.active_job = job
        terminations: list[tuple[int, int]] = []
        sleeps: list[float] = []

        _service(now=5.0, terminations=terminations, sleeps=sleeps).poll_job(port, job)

        self.assertEqual(terminations, [(77, signal.SIGTERM), (77, signal.SIGKILL)])
        self.assertEqual(sleeps, [0.2])
        self.assertIsNone(port.active_job)
        self.assertEqual(port.connection_state, "disconnected")
        self.assertEqual(port.status, "Disconnected: connect timeout")
        self.assertEqual(port.board_auto_connect_count, 1)

    def test_poll_job_sends_sigkill_on_stop_timeout(self) -> None:
        port = FakePort()
        job = jobs.create_command_job(title="Build", item_label="Build", slot="build", commands=[])
        job["process"] = FakeProcess(None, pid=88)
        job["stopping"] = True
        job["stop_requested_at"] = 1.0
        terminations: list[tuple[int, int]] = []

        _service(now=4.0, terminations=terminations).poll_job(port, job)

        self.assertEqual(terminations, [(88, signal.SIGKILL)])
        self.assertIn("stop timeout: SIGKILL", jobs.job_output_lines(job))


if __name__ == "__main__":
    unittest.main()
