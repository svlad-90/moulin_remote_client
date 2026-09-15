"""Command job control services."""

from __future__ import annotations

import signal
import time
from typing import Any, Callable

from components.jobs.api import jobs as job_api
from components.ui.api import session as ui_session_api


def selected_item_label(port: Any) -> str | None:
    items = list(getattr(port, "items", []))
    selected = getattr(port, "selected", 0)
    if not items or not isinstance(selected, int) or selected < 0 or selected >= len(items):
        return None
    return str(items[selected].label)


class CommandControlService:
    """Preview and stop running command jobs in a TUI session."""

    def __init__(
        self,
        *,
        now: Callable[[], float] = time.monotonic,
        terminate_process_group: Callable[[int, int], Any],
    ) -> None:
        self.now = now
        self.terminate_process_group = terminate_process_group

    def stop_running_preview(self, port: Any, slot: str | None = None) -> str:
        return job_api.stop_running_preview_for_label(
            slot=slot,
            active_job=port.active_job,
            board_job=port.board_job,
            selected_item_label=selected_item_label(port),
        )

    def stop_running_command(self, port: Any, slot: str | None = None) -> None:
        job = job_api.selected_or_first_running_job_for_label(
            slot=slot,
            active_job=port.active_job,
            board_job=port.board_job,
            selected_item_label=selected_item_label(port),
        )
        self.stop_job(port, job, slot)

    def stop_job(self, port: Any, job: dict[str, Any] | None, slot: str | None = None) -> None:
        process = job.get("process") if job is not None else None
        process_running = job_api.process_running(process)
        plan = job_api.request_stop_plan(job, slot, process_running=process_running, now=self.now())
        if plan["action"] == "status":
            port.status = str(plan["status"])
            return
        if job is not None and "log" in plan:
            job_api.append_job_output(job, str(plan["log"]))
            port.logs_dirty = True
        process_pid = job_api.process_pid(process)
        if plan["action"] == "terminate" and process_pid is not None:
            self.terminate_process_group(process_pid, signal.SIGTERM)
            port.status = str(plan["status"])
            port.logs_dirty = True
            return
        if plan["action"] == "finish":
            ui_session_api.apply_state(port, plan["state"])
            ui_session_api.apply_state(
                port,
                job_api.finish_job_state(
                    job,
                    active_job=port.active_job,
                    board_job=port.board_job,
                ),
            )


def command_control_service(
    *,
    now: Callable[[], float] = time.monotonic,
    terminate_process_group: Callable[[int, int], Any],
) -> CommandControlService:
    return CommandControlService(now=now, terminate_process_group=terminate_process_group)
