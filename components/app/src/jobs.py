"""Application job use-case controller."""

from __future__ import annotations

from typing import Any, Callable

from components.jobs.api import connection_workflow as job_connection_workflow
from components.jobs.api import session as job_session
from components.jobs.api import workflow as job_workflow


class AppJobController:
    """Own job lifecycle and command workflow use cases for the TUI app."""

    def __init__(
        self,
        *,
        terminate_process_group: Callable[..., Any],
        display_command: Callable[..., str],
        display_command_lines: Callable[..., list[str]],
        format_preflight: Callable[..., list[str]],
        confirm_dialog: Callable[[Any, Any], bool],
    ) -> None:
        self.terminate_process_group = terminate_process_group
        self.display_command = display_command
        self.display_command_lines = display_command_lines
        self.format_preflight = format_preflight
        self.confirm_dialog = confirm_dialog

    def job_session_controller(self, port: Any) -> job_session.JobSessionController:
        return job_session.job_session_controller(
            port.config,
            docker_image=port.docker_image,
            terminate_process_group=self.terminate_process_group,
            display_command=self.display_command,
            display_command_lines=self.display_command_lines,
            format_preflight=self.format_preflight,
            confirm_dialog=lambda content: self.confirm_dialog(port, content),
            draw=port.draw,
        )

    def stop_running_preview(self, port: Any, slot: str | None = None) -> str:
        return self.job_session_controller(port).stop_running_preview(port, slot)

    def stop_running_command(self, port: Any, slot: str | None = None) -> None:
        self.job_session_controller(port).stop_running_command(port, slot)

    def finish_active_job(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.job_session_controller(port).finish_active_job(port, job)

    def start_next_active_job_command(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.job_session_controller(port).start_next_active_job_command(port, job)

    def poll_active_jobs(self, port: Any) -> None:
        self.job_session_controller(port).poll_active_jobs(port)

    def poll_active_job(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.job_session_controller(port).poll_active_job(port, job)

    def command_workflow_service(self, port: Any) -> job_workflow.CommandWorkflowService:
        return self.job_session_controller(port).command_workflow_service(port)

    def connection_workflow_service(self, port: Any) -> job_connection_workflow.ConnectionWorkflowService:
        return self.job_session_controller(port).connection_workflow_service(port)


def app_job_controller(
    *,
    terminate_process_group: Callable[..., Any],
    display_command: Callable[..., str],
    display_command_lines: Callable[..., list[str]],
    format_preflight: Callable[..., list[str]],
    confirm_dialog: Callable[[Any, Any], bool],
) -> AppJobController:
    return AppJobController(
        terminate_process_group=terminate_process_group,
        display_command=display_command,
        display_command_lines=display_command_lines,
        format_preflight=format_preflight,
        confirm_dialog=confirm_dialog,
    )
