"""Connection session use-case controller."""

from __future__ import annotations

from typing import Any, Callable

from components.config.api import accessors as config_accessor_api
from components.ui.api import dialogs as ui_dialog_api
from components.ui.api import session as ui_session_api


class ConnectionSessionController:
    """Coordinate build-host and board-host connection session actions."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        confirm_dialog: Callable[[Any], bool],
        draw: Callable[[], None],
        start_build_host_connect: Callable[[], None],
        start_board_host_connect: Callable[[], None],
    ) -> None:
        self.config = config
        self.confirm_dialog = confirm_dialog
        self.draw = draw
        self.start_build_host_connect = start_build_host_connect
        self.start_board_host_connect = start_board_host_connect

    def toggle_build_host(self, port: Any) -> None:
        plan = ui_session_api.build_host_toggle_plan(
            action_running=port.action_running,
            active_job_exists=port.active_job is not None,
            connected=port.connection_state == "connected",
            remote_has_user=config_accessor_api.remote_has_user_for_config(self.config),
            remote_has_host=config_accessor_api.remote_has_host_for_config(self.config),
            remote_label=config_accessor_api.remote_label_for_config(self.config),
            remote_spec=config_accessor_api.remote_spec_for_config(self.config),
        )
        self._apply_toggle_plan(port, plan, self.start_build_host_connect)

    def toggle_board_host(self, port: Any) -> None:
        plan = ui_session_api.board_host_toggle_plan(
            action_running=port.action_running,
            board_job_exists=port.board_job is not None,
            connected=port.board_connection_state == "connected",
            board_has_user=bool(config_accessor_api.board_host_user_for_config(self.config)),
            board_has_host=bool(config_accessor_api.board_host_host_for_config(self.config)),
            board_label=config_accessor_api.board_host_label_for_config(self.config),
            board_spec=config_accessor_api.board_host_spec_for_config(self.config),
        )
        self._apply_toggle_plan(port, plan, self.start_board_host_connect)

    def auto_connect(self, port: Any) -> None:
        plan = ui_session_api.auto_connect_plan(
            auto_connect_done=port.auto_connect_done,
            board_has_ssh=config_accessor_api.board_host_has_ssh_for_config(self.config),
            remote_has_ssh=config_accessor_api.remote_has_ssh_for_config(self.config),
        )
        if plan["action"] == "noop":
            return
        ui_session_api.apply_state(port, plan["state"])
        if plan["action"] == "start_board":
            self.start_board_host_connect()
            return
        if plan["action"] == "start_build":
            self.start_build_host_connect()

    def start_pending_auto_board_connect(self, port: Any) -> bool:
        plan = ui_session_api.pending_board_connect_plan(
            pending_auto_board_connect=port.pending_auto_board_connect,
            action_running=port.action_running,
            board_job_exists=port.board_job is not None,
            board_has_ssh=config_accessor_api.board_host_has_ssh_for_config(self.config),
            board_connected=port.board_connection_state == "connected",
        )
        if plan["action"] == "noop":
            return False
        ui_session_api.apply_state(port, plan["state"])
        if plan["action"] != "start_board":
            return False
        self.start_board_host_connect()
        return True

    def _apply_toggle_plan(
        self,
        port: Any,
        plan: dict[str, Any],
        start_connect: Callable[[], None],
    ) -> None:
        if plan["action"] == "status":
            port.status = str(plan["status"])
            return
        if plan["action"] == "confirm_disconnect":
            if not self.confirm_dialog(
                ui_dialog_api.disconnect_confirm_content(
                    str(plan["confirm_title"]),
                    str(plan["confirm_subject"]),
                )
            ):
                port.status = str(plan["cancel_status"])
                return
            port.action_running = True
            try:
                ui_session_api.apply_state(port, plan["start_state"])
                self.draw()
                ui_session_api.apply_state(port, plan["done_state"])
            finally:
                port.action_running = False
            return
        start_connect()


def connection_session_controller(
    config: dict[str, Any],
    *,
    confirm_dialog: Callable[[Any], bool],
    draw: Callable[[], None],
    start_build_host_connect: Callable[[], None],
    start_board_host_connect: Callable[[], None],
) -> ConnectionSessionController:
    return ConnectionSessionController(
        config,
        confirm_dialog=confirm_dialog,
        draw=draw,
        start_build_host_connect=start_build_host_connect,
        start_board_host_connect=start_board_host_connect,
    )
