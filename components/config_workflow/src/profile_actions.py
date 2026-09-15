"""Configuration workflow profile action controller."""

from __future__ import annotations

from typing import Any, Callable

from components.config.api import profiles as config_profile_api
from components.ui.api import input as ui_input_api
from components.ui.api import session as ui_session_api


class ProfileActionController:
    """Apply profile selection and deletion workflows to the TUI session."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        save_config: Callable[[dict[str, Any]], None],
        confirm_action: Callable[[str, str], bool],
        reload_runtime: Callable[[], None],
        restore_project_menu_input: Callable[[], None],
    ) -> None:
        self.config = config
        self.save_config = save_config
        self.confirm_action = confirm_action
        self.reload_runtime = reload_runtime
        self.restore_project_menu_input = restore_project_menu_input

    def _reload_runtime_if_build_connected(self, port: Any) -> None:
        if getattr(port, "connection_state", "disconnected") != "connected":
            return
        self.reload_runtime()

    def delete_board_host(self, port: Any, host: dict[str, Any]) -> None:
        name = str(host.get("name", ""))
        if not self.confirm_action("Delete board host", f"Delete board host profile {name}."):
            port.status = "Board host delete cancelled"
            return
        plan = config_profile_api.apply_delete_board_host_profile_for_config(self.config, host)
        if plan["connection_reset"]:
            port.board_connection_state = "disconnected"
        self.save_config(self.config)
        port.status = str(plan["status"])

    def add_board_host(self, port: Any) -> None:
        default_name = config_profile_api.next_board_host_name(self.config.get("board_hosts", []))
        name = port.prompt("Board host profile name", default_name).strip()
        if ui_input_api.prompt_was_cancelled(port):
            port.status = "Board host add cancelled"
            return
        if not name:
            port.status = "Board host add cancelled"
            return
        try:
            plan = config_profile_api.apply_add_board_host_profile_for_config(self.config, name)
        except ValueError as exc:
            port.status = str(exc)
            return
        self.save_config(self.config)
        port.status = str(plan["status"])

    def set_active_board_host(self, port: Any, host: dict[str, Any]) -> None:
        plan = config_profile_api.apply_active_board_host_profile_for_config(self.config, host)
        if plan["connection_reset"]:
            port.board_connection_state = "disconnected"
        if plan["changed"]:
            self.save_config(self.config)
        port.status = str(plan["status"])

    def delete_remote(self, port: Any, remote: dict[str, Any]) -> None:
        name = str(remote.get("name", ""))
        if not self.confirm_action("Delete build host", f"Delete build host profile {name}."):
            port.status = "Build host delete cancelled"
            return
        plan = config_profile_api.apply_delete_remote_profile_for_config(self.config, remote)
        if plan["connection_reset"]:
            port.connection_state = "disconnected"
        if plan["preflight_reset"]:
            ui_session_api.reset_preflight(port)
        self.save_config(self.config)
        port.status = str(plan["status"])

    def add_remote(self, port: Any) -> None:
        default_name = config_profile_api.next_remote_name(self.config.get("remotes", []))
        name = port.prompt("Build host profile name", default_name).strip()
        if ui_input_api.prompt_was_cancelled(port):
            port.status = "Build host add cancelled"
            return
        if not name:
            port.status = "Build host add cancelled"
            return
        try:
            plan = config_profile_api.apply_add_remote_profile_for_config(self.config, name)
        except ValueError as exc:
            port.status = str(exc)
            return
        self.save_config(self.config)
        port.status = str(plan["status"])

    def set_active_remote(self, port: Any, remote: dict[str, Any]) -> None:
        plan = config_profile_api.apply_active_remote_profile_for_config(self.config, remote)
        if plan["connection_reset"]:
            port.connection_state = "disconnected"
        if plan["preflight_reset"]:
            ui_session_api.reset_preflight(port)
        if plan["changed"]:
            self.save_config(self.config)
        port.status = str(plan["status"])

    def delete_project_profile(self, port: Any, project: dict[str, Any]) -> None:
        name = str(project.get("name", ""))
        if not config_profile_api.can_delete_project_profile(self.config):
            port.status = "Cannot delete the only project"
            return
        if not self.confirm_action("Delete project", f"Remove project profile {name} from the client config."):
            self.restore_project_menu_input()
            port.status = "Project delete cancelled"
            return
        try:
            plan = config_profile_api.apply_delete_project_profile_for_config(self.config, project)
        except ValueError as exc:
            port.status = str(exc)
            return
        if plan["runtime_reload"]:
            self._reload_runtime_if_build_connected(port)
        if plan["preflight_reset"]:
            ui_session_api.reset_preflight(port)
        self.save_config(self.config)
        self.restore_project_menu_input()
        port.status = str(plan["status"])

    def set_active_project(self, port: Any, project: dict[str, Any]) -> None:
        plan = config_profile_api.apply_active_project_profile_for_config(self.config, project)
        if plan["runtime_reload"]:
            self._reload_runtime_if_build_connected(port)
        if plan["preflight_reset"]:
            ui_session_api.reset_preflight(port)
        if plan["changed"]:
            self.save_config(self.config)
        port.status = str(plan["status"])

    def add_project_profile(self, port: Any) -> None:
        name = port.prompt("Project profile name", "project").strip()
        if ui_input_api.prompt_was_cancelled(port):
            port.status = "Project add cancelled"
            return
        if not name:
            port.status = "Project add cancelled: empty name"
            return
        try:
            plan = config_profile_api.apply_add_project_profile_for_config(
                self.config,
                name,
                parameters=port.build_params,
                targets=port.build_targets,
                board_artifacts=port.board_artifacts,
                docker_image=port.docker_image,
            )
        except ValueError as exc:
            port.status = str(exc)
            return
        if plan["runtime_reload"]:
            self._reload_runtime_if_build_connected(port)
        self.save_config(self.config)
        port.status = str(plan["status"])

    def delete_active_project_profile(self, port: Any) -> None:
        active = str(self.config.get("active_project", ""))
        if not config_profile_api.can_delete_project_profile(self.config):
            port.status = "Cannot delete the only project"
            return
        if not self.confirm_action("Delete project", f"Remove project profile {active} from the client config."):
            self.restore_project_menu_input()
            port.status = "Project delete cancelled"
            return
        try:
            plan = config_profile_api.apply_delete_project_profile_for_config(
                self.config,
                config_profile_api.active_project(self.config),
            )
        except ValueError as exc:
            port.status = str(exc)
            return
        if plan["runtime_reload"]:
            self._reload_runtime_if_build_connected(port)
        self.save_config(self.config)
        self.restore_project_menu_input()
        port.status = str(plan["status"])


def profile_action_controller(
    config: dict[str, Any],
    *,
    save_config: Callable[[dict[str, Any]], None],
    confirm_action: Callable[[str, str], bool],
    reload_runtime: Callable[[], None],
    restore_project_menu_input: Callable[[], None],
) -> ProfileActionController:
    return ProfileActionController(
        config,
        save_config=save_config,
        confirm_action=confirm_action,
        reload_runtime=reload_runtime,
        restore_project_menu_input=restore_project_menu_input,
    )
