"""Job session workflow controller."""

from __future__ import annotations

from typing import Any, Callable

from components.jobs.api import command_control as job_command_control_api
from components.jobs.api import command_lifecycle as job_command_lifecycle_api
from components.jobs.api import command_runner as job_command_runner_api
from components.jobs.api import connection_workflow as job_connection_workflow_api
from components.jobs.api import workflow as job_workflow_api


class JobSessionController:
    """Provide command, control, and connection workflows for a TUI session."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        terminate_process_group: Callable[[int, int], Any],
        display_command: Callable[[list[str]], str],
        display_command_lines: Callable[[list[str]], list[str]],
        format_preflight: Callable[[str], tuple[str, dict[str, str]]],
        confirm_dialog: Callable[[Any], bool],
        draw: Callable[[], None],
    ) -> None:
        self.config = config
        self.docker_image = docker_image
        self.terminate_process_group = terminate_process_group
        self.display_command = display_command
        self.display_command_lines = display_command_lines
        self.format_preflight = format_preflight
        self.confirm_dialog = confirm_dialog
        self.draw = draw

    def stop_running_preview(self, port: Any, slot: str | None = None) -> str:
        return self.command_control_service().stop_running_preview(port, slot)

    def stop_running_command(self, port: Any, slot: str | None = None) -> None:
        self.command_control_service().stop_running_command(port, slot)

    def finish_active_job(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.command_workflow_service(port).finish_job(port, job)

    def start_next_active_job_command(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.command_workflow_service(port).start_next_command(port, job)

    def poll_active_jobs(self, port: Any) -> None:
        self.command_workflow_service(port).poll_jobs(port)

    def poll_active_job(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.command_workflow_service(port).poll_job(port, job)

    def command_control_service(self) -> job_command_control_api.CommandControlService:
        return job_command_control_api.command_control_service(
            terminate_process_group=self.terminate_process_group,
        )

    def command_workflow_service(self, port: Any) -> job_workflow_api.CommandWorkflowService:
        return job_workflow_api.command_workflow_service(
            runner=job_command_runner_api.command_runner_service(),
            lifecycle=job_command_lifecycle_api.command_lifecycle_service(
                terminate_process_group=self.terminate_process_group,
                display_command=self.display_command,
                display_command_lines=self.display_command_lines,
                format_preflight=self.format_preflight,
                start_pending_auto_board_connect=lambda target: self.connection_workflow_service(target).start_pending_auto_board_connect(target),
            ),
        )

    def connection_workflow_service(self, port: Any) -> job_connection_workflow_api.ConnectionWorkflowService:
        return job_connection_workflow_api.connection_workflow_service(
            self.config,
            docker_image=self.docker_image,
            confirm_dialog=self.confirm_dialog,
            draw=self.draw,
            start_next_command=lambda target, job: self.command_workflow_service(target).start_next_command(target, job),
        )


def job_session_controller(
    config: dict[str, Any],
    *,
    docker_image: str,
    terminate_process_group: Callable[[int, int], Any],
    display_command: Callable[[list[str]], str],
    display_command_lines: Callable[[list[str]], list[str]],
    format_preflight: Callable[[str], tuple[str, dict[str, str]]],
    confirm_dialog: Callable[[Any], bool],
    draw: Callable[[], None],
) -> JobSessionController:
    return JobSessionController(
        config,
        docker_image=docker_image,
        terminate_process_group=terminate_process_group,
        display_command=display_command,
        display_command_lines=display_command_lines,
        format_preflight=format_preflight,
        confirm_dialog=confirm_dialog,
        draw=draw,
    )
