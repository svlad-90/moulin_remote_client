"""Command job lifecycle service."""

from __future__ import annotations

import signal
import time
from typing import Any, Callable

from components.jobs.api import jobs as job_api
from components.ui.api import session as ui_session_api


class CommandLifecycleService:
    """Advance, poll, and finish running command jobs."""

    def __init__(
        self,
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = time.sleep,
        terminate_process_group: Callable[[int, int], Any],
        display_command: Callable[[list[str]], str],
        display_command_lines: Callable[[list[str]], list[str]],
        format_preflight: Callable[[str], tuple[str, dict[str, str]]],
        start_pending_auto_board_connect: Callable[[Any], Any],
        start_command_process: Callable[[dict[str, Any], list[str], Callable[[], None]], Any] = job_api.start_command_process,
    ) -> None:
        self.now = now
        self.sleep = sleep
        self.terminate_process_group = terminate_process_group
        self.display_command = display_command
        self.display_command_lines = display_command_lines
        self.format_preflight = format_preflight
        self.start_pending_auto_board_connect = start_pending_auto_board_connect
        self.start_command_process = start_command_process

    def finish_job(self, port: Any, job: dict[str, Any] | None = None) -> None:
        if job is None:
            job = port.active_job
        ui_session_api.apply_state(
            port,
            job_api.finish_job_state(
                job,
                active_job=port.active_job,
                board_job=port.board_job,
            ),
        )

    def start_next_command(self, port: Any, job: dict[str, Any] | None = None) -> None:
        if job is None:
            job = port.active_job
        if job is None:
            return
        plan = job_api.next_command_step_plan(job)
        if plan["action"] == "complete":
            state = dict(plan["state"])
            if state.pop("needs_preflight_reset", False):
                ui_session_api.reset_preflight(port)
            ui_session_api.apply_state(port, state)
            self.finish_job(port, job)
            return
        start = job_api.prepare_command_step_start(
            job,
            plan,
            display_command=self.display_command,
            display_command_lines=self.display_command_lines,
        )
        for line in start["log_lines"]:
            job_api.append_job_output(job, line)
        port.logs_dirty = True
        self.start_command_process(job, start["command"], lambda: setattr(port, "logs_dirty", True))

    def poll_jobs(self, port: Any) -> None:
        for job in list(job_api.running_job_list(port.active_job, port.board_job)):
            self.poll_job(port, job)

    def poll_job(self, port: Any, job: dict[str, Any] | None = None) -> None:
        if job is None:
            job = port.active_job
        if job is None:
            return
        process = job.get("process")
        process_running = job_api.process_running(process)
        rc = job_api.process_returncode(process)
        plan = job_api.poll_process_plan(job, process_running=process_running, rc=rc, now=self.now())
        if plan["action"] == "start_next":
            self.start_next_command(port, job)
            return
        process_pid = job_api.process_pid(process)
        if plan["action"] == "stop_timeout" and process_pid is not None:
            job_api.append_job_output(job, str(plan["log"]))
            port.logs_dirty = True
            self.terminate_process_group(process_pid, signal.SIGKILL)
            return
        if plan["action"] == "connect_timeout" and process_pid is not None:
            self._handle_connect_timeout(port, job, process, process_pid, plan)
            return
        if plan["action"] == "wait":
            return
        self._handle_process_complete(port, job, plan)

    def _handle_connect_timeout(
        self,
        port: Any,
        job: dict[str, Any],
        process: Any,
        process_pid: int,
        plan: dict[str, Any],
    ) -> None:
        self.terminate_process_group(process_pid, signal.SIGTERM)
        self.sleep(0.2)
        if job_api.process_running(process):
            self.terminate_process_group(process_pid, signal.SIGKILL)
        job_api.append_job_output(job, str(plan["log"]))
        port.logs_dirty = True
        ui_session_api.apply_state(port, plan["state"])
        self.finish_job(port, job)
        if plan["start_pending_auto_board_connect"]:
            self.start_pending_auto_board_connect(port)

    def _handle_process_complete(self, port: Any, job: dict[str, Any], plan: dict[str, Any]) -> None:
        job_api.join_output_reader(job, timeout=0.2)
        job_api.append_job_output(job, str(plan["log"]))
        port.logs_dirty = True
        action = plan["completed"]
        if action["action"] == "connect":
            output = "\n".join(str(line) for line in job_api.job_output_lines(job))
            port.preflight, port.preflight_values = self.format_preflight(output)
            ui_session_api.apply_state(port, action["state"])
            self.finish_job(port, job)
            self.start_pending_auto_board_connect(port)
            return
        if action["action"] in {"finish", "board-connect"}:
            ui_session_api.apply_state(port, action["state"])
            self.finish_job(port, job)
            return
        job_api.advance_completed_command_step(job)
        self.start_next_command(port, job)


def command_lifecycle_service(
    *,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Any] = time.sleep,
    terminate_process_group: Callable[[int, int], Any],
    display_command: Callable[[list[str]], str],
    display_command_lines: Callable[[list[str]], list[str]],
    format_preflight: Callable[[str], tuple[str, dict[str, str]]],
    start_pending_auto_board_connect: Callable[[Any], Any],
    start_command_process: Callable[[dict[str, Any], list[str], Callable[[], None]], Any] = job_api.start_command_process,
) -> CommandLifecycleService:
    return CommandLifecycleService(
        now=now,
        sleep=sleep,
        terminate_process_group=terminate_process_group,
        display_command=display_command,
        display_command_lines=display_command_lines,
        format_preflight=format_preflight,
        start_pending_auto_board_connect=start_pending_auto_board_connect,
        start_command_process=start_command_process,
    )
