"""Configuration field action controller."""

from __future__ import annotations

from typing import Any, Callable

from components.host_config.api import host_fields as host_field_api
from components.project_config.api import project_fields as project_field_api
from components.ui.api import session as ui_session_api


class FieldActionController:
    """Apply inline field updates and their session side effects."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        save_config: Callable[[dict[str, Any]], None],
        reload_runtime: Callable[[], None],
        board_field_service: host_field_api.BoardHostFieldService | None = None,
        build_field_service: host_field_api.BuildHostFieldService | None = None,
        project_field_service: project_field_api.ProjectFieldService | None = None,
    ) -> None:
        self.config = config
        self.save_config = save_config
        self.reload_runtime = reload_runtime
        self.board_field_service = board_field_service or host_field_api.board_host_field_service()
        self.build_field_service = build_field_service or host_field_api.build_host_field_service()
        self.project_field_service = project_field_service or project_field_api.project_field_service()

    def apply_board_host_inline_value(
        self,
        port: Any,
        host: dict[str, Any] | None,
        key: str,
        value: str,
    ) -> None:
        if host is None:
            port.status = "No board host selected"
            return
        try:
            plan = self.board_field_service.apply_inline_field_update_for_config(
                self.config,
                host,
                key,
                value,
            )
        except ValueError as exc:
            port.status = str(exc)
            return
        if plan["connection_reset"]:
            port.board_connection_state = "disconnected"
        self.save_config(self.config)
        port.status = str(plan["status"])

    def toggle_board_host_direct_copy(self, port: Any, host: dict[str, Any]) -> None:
        plan = self.board_field_service.apply_direct_copy_toggle_for_config(self.config, host)
        self.save_config(self.config)
        port.status = str(plan["status"])

    def apply_remote_inline_value(
        self,
        port: Any,
        remote: dict[str, Any] | None,
        key: str,
        value: str,
    ) -> None:
        if remote is None:
            port.status = "No build host selected"
            return
        try:
            plan = self.build_field_service.apply_inline_field_update_for_config(
                self.config,
                remote,
                key,
                value,
            )
        except ValueError as exc:
            port.status = str(exc)
            return
        if plan["connection_reset"]:
            port.connection_state = "disconnected"
            ui_session_api.reset_preflight(port)
        self.save_config(self.config)
        port.status = str(plan["status"])

    def edit_remote_value(self, port: Any, remote: dict[str, Any], key: str, label: str) -> None:
        try:
            plan = self.build_field_service.apply_labeled_field_update_for_config(
                self.config,
                remote,
                key,
                port.prompt(label, str(remote.get(key, ""))),
                label,
            )
        except ValueError as exc:
            port.status = str(exc)
            return
        if plan["connection_reset"]:
            port.connection_state = "disconnected"
            ui_session_api.reset_preflight(port)
        self.save_config(self.config)
        port.status = str(plan["status"])

    def edit_remote_projects_dir(
        self,
        port: Any,
        remote: dict[str, Any],
        *,
        browse_project_directory: Callable[[str], str | None],
    ) -> None:
        if not self.build_field_service.field_enabled_for_config(
            "projects_dir",
            remote,
            self.config,
            connected=port.connection_state == "connected",
        ):
            port.status = self.build_field_service.field_disabled_reason_for_config("projects_dir", remote, self.config)
            return
        selected = browse_project_directory(str(remote.get("projects_dir", "")) or "~")
        if selected:
            plan = self.build_field_service.apply_projects_dir_selection_for_config(self.config, remote, selected)
            self.save_config(self.config)
            port.status = str(plan["status"])

    def apply_project_inline_value(
        self,
        port: Any,
        project: dict[str, Any] | None,
        key: str,
        value: str,
    ) -> None:
        if project is None:
            port.status = "No project selected"
            return
        try:
            plan = self.project_field_service.apply_inline_field_update_for_config(
                self.config,
                project,
                key,
                value,
            )
        except ValueError as exc:
            port.status = str(exc)
            return
        if plan["runtime_reload"]:
            self.reload_runtime()
        if plan["preflight_reset"]:
            ui_session_api.reset_preflight(port)
        if plan["docker_image"] is not None:
            port.docker_image = str(plan["docker_image"])
        self.save_config(self.config)
        port.status = str(plan["status"])


def field_action_controller(
    config: dict[str, Any],
    *,
    save_config: Callable[[dict[str, Any]], None],
    reload_runtime: Callable[[], None],
) -> FieldActionController:
    return FieldActionController(
        config,
        save_config=save_config,
        reload_runtime=reload_runtime,
    )
