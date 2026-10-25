"""Configuration workflow profile action controller."""

from __future__ import annotations

from typing import Any, Callable

from components.config.api import accessors as config_accessor_api
from components.config.api import entities as config_entities_api
from components.config.api import profiles as config_profile_api
from components.config.api import store as config_store_api
from components.ui.api import input as ui_input_api
from components.ui.api import session as ui_session_api


class ProfileActionController:
    """Apply profile selection and deletion workflows to the TUI session."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        config_store: config_store_api.ConfigStore,
        confirm_action: Callable[[str, str], bool],
        reload_runtime: Callable[[], None],
        restore_project_menu_input: Callable[[], None],
    ) -> None:
        self.config = config
        self.config_store = config_store
        self.confirm_action = confirm_action
        self.reload_runtime = reload_runtime
        self.restore_project_menu_input = restore_project_menu_input

    def _reload_runtime_if_build_connected(self, port: Any) -> None:
        if getattr(port, "connection_state", "disconnected") != "connected":
            return
        self.reload_runtime()

    def _config_store(self, port: Any) -> config_store_api.ConfigStore:
        return self.config_store

    @staticmethod
    def _delete_details(summary: str, plan: config_store_api.DeletionPlan) -> str:
        if not plan.impacts:
            return summary
        lines = [summary, "", "Dependent configuration:"]
        lines.extend(f"- {description}" for description in dict.fromkeys(impact.link.description for impact in plan.impacts))
        return "\n".join(lines)

    @staticmethod
    def _blocked_status(plan: config_store_api.DeletionPlan) -> str:
        descriptions = "; ".join(dict.fromkeys(impact.link.description for impact in plan.blockers))
        return f"Cannot delete {plan.target_label}: {descriptions}"

    def delete_board_host(self, port: Any, host: dict[str, Any]) -> None:
        name = str(host.get("name", ""))
        host_id = config_profile_api.ensure_profile_id(host)
        store = self._config_store(port)
        plan = store.prepare_delete(config_store_api.EntityRef("board_host", host_id))
        if plan.blockers:
            port.status = self._blocked_status(plan)
            return
        if not self.confirm_action(
            "Delete board host",
            self._delete_details(f"Delete board host profile {name}.", plan),
        ):
            port.status = "Board host delete cancelled"
            return
        was_active = str(self.config.get("active_board_host") or "") == host_id
        store.execute_delete(plan)
        if was_active:
            port.board_connection_state = "disconnected"
        port.status = f"Board host profile deleted: {name}"

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
            self._config_store(port).create_entity("board_host", {"name": name})
        except ValueError as exc:
            port.status = str(exc)
            return
        port.status = f"Board host profile added: {name}"

    def add_board(self, port: Any, host: dict[str, Any]) -> dict[str, Any] | None:
        default_name = config_profile_api.next_board_name(host)
        name = port.prompt("Board name", default_name).strip()
        if ui_input_api.prompt_was_cancelled(port) or not name:
            port.status = "Board add cancelled"
            return None
        try:
            store = self._config_store(port)
            result = store.create_entity(
                "board",
                {
                    "name": name,
                    "board_host_id": config_profile_api.ensure_profile_id(host),
                },
            )
        except ValueError as exc:
            port.status = str(exc)
            return None
        current_host = config_profile_api.board_host_for_board(
            self.config,
            result.reference.entity_id,
        )
        if current_host is not None and current_host is not host:
            host.clear()
            host.update(current_host)
        port.status = f"Board added: {name}"
        return store.entity(result.reference)

    def delete_board(self, port: Any, host: dict[str, Any], board: dict[str, Any]) -> bool:
        name = str(board.get("name") or "")
        board_id = str(board.get("id") or "")
        store = self._config_store(port)
        plan = store.prepare_delete(config_store_api.EntityRef("board", board_id))
        if plan.blockers:
            port.status = self._blocked_status(plan)
            return False
        if not self.confirm_action("Delete board", self._delete_details(f"Delete board {name}.", plan)):
            port.status = "Board delete cancelled"
            return False
        previous_host = str(self.config.get("active_board_host") or "")
        was_active = str(self.config.get("active_board") or "") == board_id
        store.execute_delete(plan)
        if was_active and str(self.config.get("active_board_host") or "") != previous_host:
            port.board_connection_state = "disconnected"
        port.status = f"Board deleted: {name}"
        return True

    def _host_switch_blocked(self, port: Any) -> bool:
        if port.active_job is not None or port.board_job is not None:
            port.status = "Wait for the running action before switching hosts"
            return True
        if port.action_running:
            port.status = "Close the interactive action before switching hosts"
            return True
        return False

    def set_active_board_host(self, port: Any, host: dict[str, Any]) -> None:
        host_id = config_profile_api.ensure_profile_id(host)
        changed = host_id != str(self.config.get("active_board_host", ""))
        if changed:
            if self._host_switch_blocked(port):
                return
            self._config_store(port).replace_references(
                "core.active_board_host",
                config_entities_api.SELECTION,
                (config_store_api.EntityRef("board_host", host_id),),
            )
            port.board_connection_state = "disconnected"
        port.status = f"Active board host: {host.get('name')}" if changed else "selected board host is already active"
        if changed and config_accessor_api.board_host_has_ssh_for_config(self.config):
            port.connection_workflow_service().start_board_host_connect(port)

    def set_active_board(self, port: Any, board: dict[str, Any]) -> None:
        name = str(board.get("name") or "")
        board_id = config_profile_api.ensure_profile_id(board)
        target_host = config_profile_api.board_host_for_board(self.config, board_id)
        target_host_id = config_profile_api.ensure_profile_id(target_host)
        board["board_host_id"] = target_host_id
        current_host = config_profile_api.active_board_access_host(self.config)
        previous_host = str(self.config.get("active_board_host") or "")
        if str(current_host.get("name") or ""):
            previous_host = config_profile_api.ensure_profile_id(current_host)
        if target_host_id != previous_host and self._host_switch_blocked(port):
            return
        try:
            changed = board_id != str(self.config.get("active_board") or "")
            if changed:
                self._config_store(port).replace_references(
                    "core.active_board",
                    config_entities_api.SELECTION,
                    (config_store_api.EntityRef("board", board_id),),
                )
        except ValueError as exc:
            port.status = str(exc)
            return
        if not changed:
            port.status = "selected board is already active"
            return
        host_changed = target_host_id != previous_host
        if host_changed:
            port.board_connection_state = "disconnected"
        port.status = f"Active board: {name}"
        if host_changed and config_accessor_api.board_host_has_ssh_for_config(self.config):
            port.connection_workflow_service().start_board_host_connect(port)

    def delete_remote(self, port: Any, remote: dict[str, Any]) -> None:
        name = str(remote.get("name", ""))
        remote_id = config_profile_api.ensure_profile_id(remote)
        store = self._config_store(port)
        plan = store.prepare_delete(config_store_api.EntityRef("build_host", remote_id))
        if plan.blockers:
            port.status = self._blocked_status(plan)
            return
        if not self.confirm_action(
            "Delete build host",
            self._delete_details(f"Delete build host profile {name}.", plan),
        ):
            port.status = "Build host delete cancelled"
            return
        was_active = str(self.config.get("active_remote") or "") == remote_id
        store.execute_delete(plan)
        if was_active:
            port.connection_state = "disconnected"
        if was_active:
            ui_session_api.reset_preflight(port)
        port.status = f"Build host profile deleted: {name}"

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
            self._config_store(port).create_entity("build_host", {"name": name})
        except ValueError as exc:
            port.status = str(exc)
            return
        port.status = f"Build host profile added: {name}"

    def create_remote_from_values(self, port: Any, values: dict[str, Any]) -> dict[str, Any]:
        name = str(values.get("name") or "").strip()
        payload = dict(values)
        payload["name"] = name
        payload["label"] = str(payload.get("label") or name)
        payload["make_active"] = True
        self._config_store(port).create_entity("build_host", payload)
        return {
            "status": f"Build host profile added: {name}",
            "connection_reset": True,
            "preflight_reset": True,
        }

    def set_active_remote(self, port: Any, remote: dict[str, Any]) -> None:
        remote_id = config_profile_api.ensure_profile_id(remote)
        changed = remote_id != str(self.config.get("active_remote", ""))
        if changed:
            if self._host_switch_blocked(port):
                return
            self._config_store(port).replace_references(
                "core.active_build_host",
                config_entities_api.SELECTION,
                (config_store_api.EntityRef("build_host", remote_id),),
            )
            port.connection_state = "disconnected"
            ui_session_api.reset_preflight(port)
        port.status = f"Active build host: {remote.get('name')}" if changed else "selected build host is already active"
        if changed and config_accessor_api.remote_has_ssh_for_config(self.config):
            port.connection_workflow_service().start_build_host_connect(port)

    def delete_project_profile(
        self,
        port: Any,
        project: dict[str, Any],
        *,
        reset_preflight: bool = True,
    ) -> None:
        name = str(project.get("name", ""))
        if not config_profile_api.can_delete_project_profile(self.config):
            port.status = "Cannot delete the only project"
            return
        project_id = config_profile_api.ensure_profile_id(project)
        store = self._config_store(port)
        plan = store.prepare_delete(config_store_api.EntityRef("project", project_id))
        if plan.blockers:
            port.status = self._blocked_status(plan)
            return
        if not self.confirm_action(
            "Delete project",
            self._delete_details(f"Remove project profile {name} from the client config.", plan),
        ):
            self.restore_project_menu_input()
            port.status = "Project delete cancelled"
            return
        try:
            was_active = str(self.config.get("active_project") or "") == project_id
            store.execute_delete(plan)
        except ValueError as exc:
            port.status = str(exc)
            return
        if was_active:
            self._reload_runtime_if_build_connected(port)
        if was_active and reset_preflight:
            ui_session_api.reset_preflight(port)
        self.restore_project_menu_input()
        port.status = f"Project deleted: {name}"

    def set_active_project(self, port: Any, project: dict[str, Any]) -> None:
        project_id = config_profile_api.ensure_profile_id(project)
        changed = project_id != str(self.config.get("active_project") or "")
        if changed:
            self._config_store(port).replace_references(
                "core.active_project",
                config_entities_api.SELECTION,
                (config_store_api.EntityRef("project", project_id),),
            )
            self._reload_runtime_if_build_connected(port)
            ui_session_api.reset_preflight(port)
        label = project.get("label") or project.get("name")
        port.status = f"Active project: {label}" if changed else "selected project is already active"

    def add_project_profile(self, port: Any) -> None:
        name = port.prompt("Project profile name", "project").strip()
        if ui_input_api.prompt_was_cancelled(port):
            port.status = "Project add cancelled"
            return
        if not name:
            port.status = "Project add cancelled: empty name"
            return
        try:
            self._config_store(port).create_entity(
                "project",
                {
                    "name": name,
                    "parameters": port.build_params,
                    "targets": port.build_targets,
                    "board_artifacts": port.board_artifacts,
                    "docker_image": port.docker_image,
                },
            )
        except ValueError as exc:
            port.status = str(exc)
            return
        self._reload_runtime_if_build_connected(port)
        port.status = f"Project added: {name}"

    def delete_active_project_profile(self, port: Any) -> None:
        self.delete_project_profile(
            port,
            config_profile_api.active_project(self.config),
            reset_preflight=False,
        )


def profile_action_controller(
    config: dict[str, Any],
    *,
    config_store: config_store_api.ConfigStore,
    confirm_action: Callable[[str, str], bool],
    reload_runtime: Callable[[], None],
    restore_project_menu_input: Callable[[], None],
) -> ProfileActionController:
    return ProfileActionController(
        config,
        config_store=config_store,
        confirm_action=confirm_action,
        reload_runtime=reload_runtime,
        restore_project_menu_input=restore_project_menu_input,
    )
