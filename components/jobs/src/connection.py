"""Build and board host connection job controllers."""

from __future__ import annotations

import time
from typing import Any, Callable

from components.board.api import session as board_session_api
from components.jobs.api import jobs as job_api
from components.remote.api import project as remote_project_api
from components.ui.api import session as ui_session_api


def menu_item_label(port: Any, wanted: str) -> str:
    items = list(getattr(port, "items", []))
    fallback = items[0].label if items else wanted
    item = next((menu_item for menu_item in items if menu_item.label == wanted), None)
    return item.label if item is not None else fallback


class ConnectionJobController:
    """Start build-host and board-host connection jobs for the TUI session."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        now: Callable[[], float] = time.monotonic,
        remote_project_service: remote_project_api.RemoteProjectMaintenanceService | None = None,
        board_session_service: board_session_api.BoardSessionCommandService | None = None,
    ) -> None:
        self.config = config
        self.docker_image = docker_image
        self.now = now
        self.remote_project_service = remote_project_service or remote_project_api.remote_project_maintenance_service()
        self.board_session_service = board_session_service or board_session_api.board_session_command_service()

    def start_build_host_connect(
        self,
        port: Any,
        *,
        start_next_command: Callable[[dict[str, Any]], Any],
    ) -> None:
        if port.active_job is not None:
            port.status = "Another build action is already running"
            return
        if port.action_running:
            port.status = "Another interactive action is already running"
            return
        item_label = menu_item_label(port, "Connect build host")
        ui_session_api.apply_state(port, ui_session_api.build_host_connect_start_state())
        command = self.remote_project_service.preflight_command_for_config(self.config, self.docker_image)
        port.active_job = job_api.create_build_connect_job(
            item_label=item_label,
            command=command,
            started_at=self.now(),
        )
        start_next_command(port.active_job)
        ui_session_api.apply_state(port, ui_session_api.connect_job_started_state())

    def start_board_host_connect(
        self,
        port: Any,
        *,
        start_next_command: Callable[[dict[str, Any]], Any],
    ) -> None:
        if port.board_job is not None:
            port.status = "Another board action is already running"
            return
        if port.action_running:
            port.status = "Another interactive action is already running"
            return
        item_label = menu_item_label(port, "Connect board host")
        ui_session_api.apply_state(port, ui_session_api.board_host_connect_start_state())
        command = self.board_session_service.connect_command_for_config(self.config)
        port.board_job = job_api.create_board_connect_job(
            item_label=item_label,
            command=command,
            started_at=self.now(),
        )
        start_next_command(port.board_job)
        ui_session_api.apply_state(port, ui_session_api.connect_job_started_state())


def connection_job_controller_for_config(
    config: dict[str, Any],
    *,
    docker_image: str,
    now: Callable[[], float] = time.monotonic,
) -> ConnectionJobController:
    return ConnectionJobController(config, docker_image=docker_image, now=now)
