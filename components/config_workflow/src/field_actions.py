"""Configuration field action controller."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from components.config.api import profiles as config_profile_api
from components.config.api import store as config_store_api
from components.host_config.api import host_fields as host_field_api
from components.project_config.api import project_fields as project_field_api
from components.ui.api import input as ui_input_api
from components.ui.api import session as ui_session_api


class FieldActionController:
    """Apply inline field updates and their session side effects."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        config_store: config_store_api.ConfigStore,
        reload_runtime: Callable[[], None],
        reload_project_source_runtime: Callable[[], None] | None = None,
        board_field_service: host_field_api.BoardHostFieldService | None = None,
        build_field_service: host_field_api.BuildHostFieldService | None = None,
        project_field_service: project_field_api.ProjectFieldService | None = None,
    ) -> None:
        self.config = config
        self.config_store = config_store
        self.reload_runtime = reload_runtime
        self.reload_project_source_runtime = reload_project_source_runtime
        self.board_field_service = board_field_service or host_field_api.board_host_field_service()
        self.build_field_service = build_field_service or host_field_api.build_host_field_service()
        self.project_field_service = project_field_service or project_field_api.project_field_service()

    def _config_store(self, port: Any) -> config_store_api.ConfigStore:
        return self.config_store

    def _update_entity(
        self,
        port: Any,
        kind: str,
        record: dict[str, Any],
        changes: dict[str, Any],
    ) -> None:
        entity_id = config_profile_api.ensure_profile_id(record)
        self._config_store(port).update_entity(config_store_api.EntityRef(kind, entity_id), changes)

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
        clean_value = self.board_field_service.normalize_value(key, value)
        command_id = self.board_field_service.command_id_for_field(key)
        if command_id:
            commands = deepcopy(host.get("commands")) if isinstance(host.get("commands"), dict) else {}
            if clean_value:
                commands[command_id] = clean_value
            else:
                commands.pop(command_id, None)
            changes = {"commands": commands}
            connection_reset = False
        else:
            changes = {key: clean_value}
            connection_reset = key in ("type", "user", "host", "work_dir") and str(
                self.config.get("active_board_host", "")
            ) in {str(host.get("id") or ""), str(host.get("name") or "")}
        try:
            self._update_entity(port, "board_host", host, changes)
        except (ValueError, config_store_api.ConfigStoreError) as exc:
            port.status = str(exc)
            return
        if connection_reset:
            port.board_connection_state = "disconnected"
        port.status = f"{key} updated"

    def toggle_board_host_direct_copy(self, port: Any, host: dict[str, Any]) -> None:
        value = self.board_field_service.next_direct_copy_value(str(host.get("direct_copy", "no")))
        self._update_entity(port, "board_host", host, {"direct_copy": value})
        port.status = f"Direct copy: {value}"

    def apply_board_inline_value(
        self,
        port: Any,
        board: dict[str, Any] | None,
        key: str,
        value: str,
    ) -> None:
        if board is None:
            port.status = "No board selected"
            return
        clean_value = self.board_field_service.normalize_value(key, value)
        command_id = self.board_field_service.command_id_for_field(key)
        if command_id:
            commands = deepcopy(board.get("commands")) if isinstance(board.get("commands"), dict) else {}
            if clean_value:
                commands[command_id] = clean_value
            else:
                commands.pop(command_id, None)
            changes = {"commands": commands}
        else:
            changes = {key: clean_value}
        try:
            self._update_entity(port, "board", board, changes)
        except (ValueError, config_store_api.ConfigStoreError) as exc:
            port.status = str(exc)
            return
        port.status = f"{key} updated"

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
        clean_value = self.build_field_service.normalize_value(key, value)
        connection_reset = key in ("user", "host", "projects_dir") and str(
            self.config.get("active_remote", "")
        ) in {str(remote.get("id") or ""), str(remote.get("name") or "")}
        try:
            self._update_entity(port, "build_host", remote, {key: clean_value})
        except (ValueError, config_store_api.ConfigStoreError) as exc:
            port.status = str(exc)
            return
        if connection_reset:
            port.connection_state = "disconnected"
            ui_session_api.reset_preflight(port)
        port.status = f"{key} updated"

    def edit_remote_value(self, port: Any, remote: dict[str, Any], key: str, label: str) -> None:
        value = port.prompt(label, str(remote.get(key, "")))
        if ui_input_api.prompt_was_cancelled(port):
            port.status = "Edit cancelled"
            return
        self.apply_remote_inline_value(port, remote, key, value)
        if port.status == f"{key} updated":
            port.status = f"{label} updated"

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
            try:
                self._update_entity(port, "build_host", remote, {"projects_dir": selected})
            except (ValueError, config_store_api.ConfigStoreError) as exc:
                port.status = str(exc)
                return
            port.status = f"Projects dir: {selected}"

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
        normalized = self.project_field_service.normalize_value(key, value)
        normalized, projects_dir = self.project_field_service.project_dir_field_update(key, normalized)
        active = self.project_field_service.project_is_active_for_config(project, self.config)
        changes: dict[str, Any] = {key: normalized}
        if projects_dir:
            changes["_remote_projects_dir"] = projects_dir
        try:
            self._update_entity(port, "project", project, changes)
        except (ValueError, config_store_api.ConfigStoreError) as exc:
            port.status = str(exc)
            return
        plan = {
            "status": f"{key} updated",
            "runtime_reload": active and self.project_field_service.runtime_reload_needed(key),
            "project_source_reload": active and self.project_field_service.project_source_reload_needed(key),
            "preflight_reset": active and self.project_field_service.preflight_reset_needed(key),
            "docker_image": normalized
            if active and self.project_field_service.docker_image_update_needed(key)
            else None,
        }
        reload_project_source = False
        if getattr(port, "connection_state", "disconnected") == "connected":
            if plan["project_source_reload"] and self.reload_project_source_runtime is not None:
                reload_project_source = True
            elif plan["runtime_reload"]:
                self.reload_runtime()
        if plan["preflight_reset"]:
            ui_session_api.reset_preflight(port)
        if plan["docker_image"] is not None:
            port.docker_image = str(plan["docker_image"])
        port.status = str(plan["status"])
        if reload_project_source:
            self.reload_project_source_runtime()

    def apply_project_values(
        self,
        port: Any,
        project: dict[str, Any] | None,
        changes: dict[str, Any],
        *,
        status: str,
    ) -> bool:
        """Apply a validated project field batch through one store transaction."""

        if project is None:
            port.status = "No project selected"
            return False
        try:
            self._update_entity(port, "project", project, changes)
        except (ValueError, config_store_api.ConfigStoreError) as exc:
            port.status = str(exc)
            return False
        active = self.project_field_service.project_is_active_for_config(project, self.config)
        keys = set(changes)
        if active and any(self.project_field_service.preflight_reset_needed(key) for key in keys):
            ui_session_api.reset_preflight(port)
        if active and getattr(port, "connection_state", "disconnected") == "connected":
            if any(self.project_field_service.runtime_reload_needed(key) for key in keys):
                self.reload_runtime()
        port.status = status
        return True


def field_action_controller(
    config: dict[str, Any],
    *,
    config_store: config_store_api.ConfigStore,
    reload_runtime: Callable[[], None],
    reload_project_source_runtime: Callable[[], None] | None = None,
) -> FieldActionController:
    return FieldActionController(
        config,
        config_store=config_store,
        reload_runtime=reload_runtime,
        reload_project_source_runtime=reload_project_source_runtime,
    )
