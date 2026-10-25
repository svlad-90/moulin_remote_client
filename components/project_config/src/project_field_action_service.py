"""Project field action use-case service."""

from __future__ import annotations

from typing import Any, Callable

from components.config.api import profiles as config_profile_api
from components.project_config.api import fields as project_field_api


class ProjectFieldActionService:
    """Execute the workflow behind pressing Enter on a project field."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        target_selection_controller_factory: Callable[[], Any],
        project_settings_controller: Any,
        remote_file_selection_controller: Any,
        project_remote_dir_editor: Any,
        project_git_ref_selector: Any,
        field_action_controller: Any,
        reload_runtime: Callable[[], Any],
        project_field_service: project_field_api.ProjectFieldService | None = None,
        product_type_selector: Callable[[Any, project_field_api.ProjectFieldService, str], str | None]
        | None = None,
    ) -> None:
        self.config = config
        self.target_selection_controller_factory = target_selection_controller_factory
        self.project_settings_controller = project_settings_controller
        self.remote_file_selection_controller = remote_file_selection_controller
        self.project_remote_dir_editor = project_remote_dir_editor
        self.project_git_ref_selector = project_git_ref_selector
        self.field_action_controller = field_action_controller
        self.reload_runtime = reload_runtime
        self.project_field_service = project_field_service or project_field_api.project_field_service()
        self.product_type_selector = product_type_selector

    def handle_enter_field(
        self,
        port: Any,
        field: dict[str, Any],
        selected_project: dict[str, Any],
    ) -> dict[str, Any]:
        field_action = self.project_field_service.field_enter_action_for_config(
            field,
            selected_project,
            self.config,
            connected=port.connection_state == "connected",
        )
        action = field_action["action"]
        if action == "status":
            port.status = str(field_action["status"])
            return {"action": "handled"}
        if action == "select-moulin-manifest":
            self._select_moulin_manifest(port)
            return {"action": "handled"}
        if action == "select-dockerfile":
            self._select_dockerfile(port)
            return {"action": "handled"}
        if action == "edit-project-remote-dir":
            self._edit_project_remote_dir(port, selected_project)
            return {"action": "handled"}
        if action == "edit-project-git-ref":
            self._edit_project_git_ref(port, selected_project)
            return {"action": "handled"}
        if action == "select-build-targets":
            self._select_build_targets(port)
            return {"action": "handled"}
        if action == "select-board-artifacts":
            self._select_board_artifacts(port)
            return {"action": "handled"}
        if action == "cycle-parameter":
            self._cycle_parameter(port, field_action["param"])
            return {"action": "handled"}
        if action == "select-product-type":
            current = str(selected_project.get("product_type", ""))
            value = (
                self.product_type_selector(port, self.project_field_service, current)
                if self.product_type_selector is not None
                else self.project_field_service.next_product_type_value(current)
            )
            if value is not None:
                self.apply_project_value(port, selected_project, "product_type", value)
                port.status = f"Product type: {value}"
            return {"action": "handled"}
        if action == "edit-text":
            port.status = f"Editing {field_action['label']}"
            return {
                "action": "edit-text",
                "key": str(field_action["key"]),
                "value": str(field_action["value"]),
            }
        return {"action": "handled"}

    def apply_project_value(self, port: Any, project: dict[str, Any], key: str, value: str) -> None:
        self.field_action_controller.apply_project_inline_value(port, project, key, value)

    def _select_moulin_manifest(self, port: Any) -> None:
        self.remote_file_selection_controller.select_moulin_manifest(port)

    def _select_dockerfile(self, port: Any) -> None:
        self.remote_file_selection_controller.select_dockerfile(port)

    def _edit_project_remote_dir(self, port: Any, selected_project: dict[str, Any]) -> None:
        self.project_remote_dir_editor.edit_project_remote_dir(
            port,
            selected_project,
            connected=port.connection_state == "connected",
            apply_project_value=lambda project, key, value: self.apply_project_value(port, project, key, value),
        )

    def _edit_project_git_ref(self, port: Any, selected_project: dict[str, Any]) -> None:
        self.project_git_ref_selector.edit_project_git_ref(
            port,
            selected_project,
            connected=port.connection_state == "connected",
            apply_project_value=lambda project, key, value: self.apply_project_value(port, project, key, value),
        )

    def _select_build_targets(self, port: Any) -> None:
        self.target_selection_controller_factory().select_build_targets(
            port,
            reload_runtime=self.reload_runtime,
        )

    def _select_board_artifacts(self, port: Any) -> None:
        self.target_selection_controller_factory().select_board_artifacts(
            port,
            reload_runtime=self.reload_runtime,
        )

    def _cycle_parameter(self, port: Any, param: dict[str, Any]) -> None:
        self.project_settings_controller.cycle_parameter(port, param)
        self.field_action_controller.apply_project_values(
            port,
            config_profile_api.active_project(self.config),
            {
                "parameters": dict(port.build_params),
                "targets": port.build_targets,
                "docker_image": port.docker_image,
            },
            status=port.status,
        )


def project_field_action_service(
    config: dict[str, Any],
    *,
    target_selection_controller_factory: Callable[[], Any],
    project_settings_controller: Any,
    remote_file_selection_controller: Any,
    project_remote_dir_editor: Any,
    project_git_ref_selector: Any,
    field_action_controller: Any,
    reload_runtime: Callable[[], Any],
    product_type_selector: Callable[[Any, project_field_api.ProjectFieldService, str], str | None]
    | None = None,
) -> ProjectFieldActionService:
    return ProjectFieldActionService(
        config,
        target_selection_controller_factory=target_selection_controller_factory,
        project_settings_controller=project_settings_controller,
        remote_file_selection_controller=remote_file_selection_controller,
        project_remote_dir_editor=project_remote_dir_editor,
        project_git_ref_selector=project_git_ref_selector,
        field_action_controller=field_action_controller,
        reload_runtime=reload_runtime,
        product_type_selector=product_type_selector,
    )
