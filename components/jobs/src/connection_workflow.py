"""Connection workflow service."""

from __future__ import annotations

from typing import Any, Callable

from components.jobs.api import connection as job_connection_api
from components.jobs.api import connection_session as job_connection_session_api


class ConnectionWorkflowService:
    """Own build-host and board-host connection workflows."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        confirm_dialog: Callable[[Any], bool],
        draw: Callable[[], None],
        start_next_command: Callable[[Any, dict[str, Any]], Any],
    ) -> None:
        self.config = config
        self.docker_image = docker_image
        self.confirm_dialog = confirm_dialog
        self.draw = draw
        self.start_next_command = start_next_command

    def toggle_build_host(self, port: Any) -> None:
        self._session_controller(port).toggle_build_host(port)

    def toggle_board_host(self, port: Any) -> None:
        self._session_controller(port).toggle_board_host(port)

    def auto_connect(self, port: Any) -> None:
        self._session_controller(port).auto_connect(port)

    def start_pending_auto_board_connect(self, port: Any) -> bool:
        return self._session_controller(port).start_pending_auto_board_connect(port)

    def start_build_host_connect(self, port: Any) -> None:
        self._job_controller().start_build_host_connect(
            port,
            start_next_command=lambda job: self.start_next_command(port, job),
        )

    def start_board_host_connect(self, port: Any) -> None:
        self._job_controller().start_board_host_connect(
            port,
            start_next_command=lambda job: self.start_next_command(port, job),
        )

    def _session_controller(self, port: Any) -> job_connection_session_api.ConnectionSessionController:
        return job_connection_session_api.connection_session_controller(
            self.config,
            confirm_dialog=self.confirm_dialog,
            draw=self.draw,
            start_build_host_connect=lambda: self.start_build_host_connect(port),
            start_board_host_connect=lambda: self.start_board_host_connect(port),
        )

    def _job_controller(self) -> job_connection_api.ConnectionJobController:
        return job_connection_api.connection_job_controller_for_config(
            self.config,
            docker_image=self.docker_image,
        )


def connection_workflow_service(
    config: dict[str, Any],
    *,
    docker_image: str,
    confirm_dialog: Callable[[Any], bool],
    draw: Callable[[], None],
    start_next_command: Callable[[Any, dict[str, Any]], Any],
) -> ConnectionWorkflowService:
    return ConnectionWorkflowService(
        config,
        docker_image=docker_image,
        confirm_dialog=confirm_dialog,
        draw=draw,
        start_next_command=start_next_command,
    )
