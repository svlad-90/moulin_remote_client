"""Build host edit workflow service."""

from __future__ import annotations

from typing import Any, Callable

from components.host_config.api import fields as config_field_api
from components.ui.api import menu as ui_menu_api


class RemoteEditWorkflowService:
    """Orchestrate the edit-build-host use case for terminal screens."""

    def __init__(
        self,
        config: dict[str, Any],
        remote: dict[str, Any],
        *,
        save_config: Callable[[dict[str, Any]], Any],
        profile_action_controller: Any,
        field_action_controller: Any,
        browse_project_directory: Callable[[str], str | None],
        build_field_service: config_field_api.BuildHostFieldService | None = None,
    ) -> None:
        self.config = config
        self.remote = remote
        self.save_config = save_config
        self.profile_action_controller = profile_action_controller
        self.field_action_controller = field_action_controller
        self.browse_project_directory = browse_project_directory
        self.build_field_service = build_field_service or config_field_api.build_host_field_service()
        self.fields = config_field_api.remote_fields() + [("Back", "back")]
        self.index = 0

    def move(self, delta: int) -> None:
        self.index = ui_menu_api.move_index(self.index, len(self.fields), delta)

    def selected_field(self) -> tuple[str, str]:
        return self.fields[self.index]

    def is_active(self) -> bool:
        return str(self.remote.get("name", "")) == str(self.config.get("active_remote", ""))

    def field_value(self, key: str) -> str:
        if key == "back":
            return ""
        return str(self.remote.get(key, "")) or "<not set>"

    def field_enabled(self, key: str, *, connected: bool) -> bool:
        return self.build_field_service.field_enabled_for_config(
            key,
            self.remote,
            self.config,
            connected=connected,
        )

    def field_disabled_reason(self, key: str) -> str:
        return self.build_field_service.field_disabled_reason_for_config(key, self.remote, self.config)

    def field_hint(self, key: str) -> str:
        return self.build_field_service.field_hint(key)

    def set_active(self, port: Any) -> None:
        self.profile_action_controller.set_active_remote(port, self.remote)

    def browse_projects_dir(self, port: Any) -> None:
        self.field_action_controller.edit_remote_projects_dir(
            port,
            self.remote,
            browse_project_directory=self.browse_project_directory,
        )

    def handle_enter(self, port: Any) -> bool:
        label, key = self.selected_field()
        if key == "back":
            self.save_config(self.config)
            return True
        if not self.field_enabled(key, connected=port.connection_state == "connected"):
            port.status = self.field_disabled_reason(key)
            return False
        if key == "projects_dir":
            self.browse_projects_dir(port)
            return False
        self.field_action_controller.edit_remote_value(port, self.remote, key, label)
        return False

    def save_and_close(self) -> None:
        self.save_config(self.config)


def remote_edit_workflow_service(
    config: dict[str, Any],
    remote: dict[str, Any],
    *,
    save_config: Callable[[dict[str, Any]], Any],
    profile_action_controller: Any,
    field_action_controller: Any,
    browse_project_directory: Callable[[str], str | None],
    build_field_service: config_field_api.BuildHostFieldService | None = None,
) -> RemoteEditWorkflowService:
    return RemoteEditWorkflowService(
        config,
        remote,
        save_config=save_config,
        profile_action_controller=profile_action_controller,
        field_action_controller=field_action_controller,
        browse_project_directory=browse_project_directory,
        build_field_service=build_field_service,
    )
