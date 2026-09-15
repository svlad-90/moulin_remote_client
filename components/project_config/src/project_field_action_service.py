"""Project field action use-case service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.project_config.api import fields as project_field_api
from components.build_runtime.api import runtime as config_runtime_api


class ProjectFieldActionService:
    """Execute the workflow behind pressing Enter on a project field."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        app_dir: Path,
        default_config_path: Path,
        target_selection_controller_factory: Callable[[], Any] | None = None,
        project_settings_controller: Any | None = None,
        remote_file_selection_controller: Any | None = None,
        project_remote_dir_editor: Any | None = None,
        project_git_ref_selector: Any | None = None,
        field_action_controller: Any | None = None,
        reload_runtime: Callable[[], Any] | None = None,
        save_runtime_settings: Callable[..., None] = config_runtime_api.save_current_runtime_build_settings,
        project_field_service: project_field_api.ProjectFieldService | None = None,
    ) -> None:
        self.config = config
        self.app_dir = app_dir
        self.default_config_path = default_config_path
        self.target_selection_controller_factory = target_selection_controller_factory
        self.project_settings_controller = project_settings_controller
        self.remote_file_selection_controller = remote_file_selection_controller
        self.project_remote_dir_editor = project_remote_dir_editor
        self.project_git_ref_selector = project_git_ref_selector
        self.field_action_controller = field_action_controller
        self.reload_runtime = reload_runtime
        self.save_runtime_settings = save_runtime_settings
        self.project_field_service = project_field_service or project_field_api.project_field_service()

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
        if action == "edit-text":
            port.status = f"Editing {field_action['label']}"
            return {
                "action": "edit-text",
                "key": str(field_action["key"]),
                "value": str(field_action["value"]),
            }
        return {"action": "handled"}

    def apply_project_value(self, port: Any, project: dict[str, Any], key: str, value: str) -> None:
        if self.field_action_controller is None:
            port.apply_project_inline_value(project, key, value)
            return
        self.field_action_controller.apply_project_inline_value(port, project, key, value)

    def _select_moulin_manifest(self, port: Any) -> None:
        if self.remote_file_selection_controller is None:
            port.select_remote_moulin_manifest()
            return
        self.remote_file_selection_controller.select_moulin_manifest(port)

    def _select_dockerfile(self, port: Any) -> None:
        if self.remote_file_selection_controller is None:
            port.select_remote_dockerfile()
            return
        self.remote_file_selection_controller.select_dockerfile(port)

    def _edit_project_remote_dir(self, port: Any, selected_project: dict[str, Any]) -> None:
        if self.project_remote_dir_editor is None:
            port.edit_project_remote_dir(selected_project)
            return
        self.project_remote_dir_editor.edit_project_remote_dir(
            port,
            selected_project,
            connected=port.connection_state == "connected",
            apply_project_value=lambda project, key, value: self.apply_project_value(port, project, key, value),
        )

    def _edit_project_git_ref(self, port: Any, selected_project: dict[str, Any]) -> None:
        if self.project_git_ref_selector is None:
            port.edit_project_git_ref(selected_project)
            return
        self.project_git_ref_selector.edit_project_git_ref(
            port,
            selected_project,
            connected=port.connection_state == "connected",
            apply_project_value=lambda project, key, value: self.apply_project_value(port, project, key, value),
        )

    def _select_build_targets(self, port: Any) -> None:
        if self.target_selection_controller_factory is None:
            port.select_build_targets_screen()
            return
        self.target_selection_controller_factory().select_build_targets(
            port,
            reload_runtime=self.reload_runtime or _noop,
        )

    def _select_board_artifacts(self, port: Any) -> None:
        if self.target_selection_controller_factory is None:
            port.select_board_artifacts_screen()
            return
        self.target_selection_controller_factory().select_board_artifacts(
            port,
            reload_runtime=self.reload_runtime or _noop,
        )

    def _cycle_parameter(self, port: Any, param: dict[str, Any]) -> None:
        if self.project_settings_controller is None:
            port.cycle_parameter(param)
        else:
            self.project_settings_controller.cycle_parameter(port, param)
        self.save_runtime_settings(
            self.config,
            parameters=port.build_params,
            targets=port.build_targets,
            docker_image=port.docker_image,
            app_dir=self.app_dir,
            default_path=self.default_config_path,
        )


def project_field_action_service(
    config: dict[str, Any],
    *,
    app_dir: Path,
    default_config_path: Path,
    target_selection_controller_factory: Callable[[], Any] | None = None,
    project_settings_controller: Any | None = None,
    remote_file_selection_controller: Any | None = None,
    project_remote_dir_editor: Any | None = None,
    project_git_ref_selector: Any | None = None,
    field_action_controller: Any | None = None,
    reload_runtime: Callable[[], Any] | None = None,
    save_runtime_settings: Callable[..., None] = config_runtime_api.save_current_runtime_build_settings,
) -> ProjectFieldActionService:
    return ProjectFieldActionService(
        config,
        app_dir=app_dir,
        default_config_path=default_config_path,
        target_selection_controller_factory=target_selection_controller_factory,
        project_settings_controller=project_settings_controller,
        remote_file_selection_controller=remote_file_selection_controller,
        project_remote_dir_editor=project_remote_dir_editor,
        project_git_ref_selector=project_git_ref_selector,
        field_action_controller=field_action_controller,
        reload_runtime=reload_runtime,
        save_runtime_settings=save_runtime_settings,
    )


def _noop() -> None:
    return None
