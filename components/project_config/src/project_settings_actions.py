"""Project settings action controller."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.config.api import accessors as config_accessor_api
from components.config.api import profiles as config_profile_api
from components.project_config.api import project_settings_service as config_project_settings_api
from components.build_runtime.api import runtime as config_runtime_api
from components.ui.api import session as ui_session_api


class ProjectSettingsActionController:
    """Dispatch project settings actions through the TUI workflow."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        app_dir: Path,
        default_config_path: Path,
        save_config: Callable[[dict[str, Any]], None],
        save_runtime_settings: Callable[..., None] = config_runtime_api.save_current_runtime_build_settings,
        target_selection_controller_factory: Callable[[], Any] | None = None,
        remote_file_selection_controller: Any | None = None,
        profile_action_controller: Any | None = None,
        project_picker_controller: Any | None = None,
        reload_runtime: Callable[[], Any] | None = None,
        settings_service: config_project_settings_api.ProjectSettingsService | None = None,
    ) -> None:
        self.config = config
        self.target_selection_controller_factory = target_selection_controller_factory
        self.remote_file_selection_controller = remote_file_selection_controller
        self.profile_action_controller = profile_action_controller
        self.project_picker_controller = project_picker_controller
        self.reload_runtime = reload_runtime
        self.settings_service = settings_service or config_project_settings_api.ProjectSettingsService(
            config,
            app_dir=app_dir,
            default_config_path=default_config_path,
            save_config=save_config,
            save_runtime_settings=save_runtime_settings,
        )

    def run_action(self, port: Any, action: dict[str, Any]) -> bool:
        kind = action["kind"]
        if kind == "select_project":
            if self.project_picker_controller is None:
                port.select_project_screen()
            else:
                self.project_picker_controller.select_project(
                    port,
                    reload_runtime=self.reload_runtime or _noop,
                )
            return False
        if kind == "add_project":
            if self.profile_action_controller is None:
                port.add_project_profile()
            else:
                self.profile_action_controller.add_project_profile(port)
            return False
        if kind == "delete_project":
            if self.profile_action_controller is None:
                port.delete_active_project_profile()
            else:
                self.profile_action_controller.delete_active_project_profile(port)
            return False
        if kind == "param":
            self.cycle_parameter(port, action["param"])
            return False
        if kind == "local_project_dir":
            self._edit_local_project_dir(port)
            return False
        if kind == "manifest":
            self._select_moulin_manifest(port)
            return False
        if kind == "git_url":
            self._edit_git_url(port)
            return False
        if kind == "dockerfile":
            self._select_dockerfile(port)
            return False
        if kind == "targets":
            self._select_build_targets(port)
            return False
        if kind == "board_artifacts":
            self._select_board_artifacts(port)
            return False
        if kind == "docker":
            self._edit_docker_image(port)
            return False
        if kind == "save":
            self._save_project(port)
            return True
        if kind == "back":
            port.status = "Project changes kept in memory, not saved"
            return True
        return False

    def cycle_parameter(self, port: Any, param: dict[str, Any]) -> None:
        status = self.settings_service.cycle_parameter(port.build_params, param)
        if status is None:
            return
        port.status = status

    def _edit_local_project_dir(self, port: Any) -> None:
        value = port.prompt(
            "Local overlay dir",
            str(config_profile_api.active_project(self.config).get("local_project_dir", "")),
        )
        self.settings_service.apply_local_project_dir(value)

    def _edit_git_url(self, port: Any) -> None:
        plan = self.settings_service.apply_git_url(
            port.prompt("Project Git URL", config_accessor_api.project_git_url_for_config(self.config))
        )
        if plan["preflight_reset"]:
            ui_session_api.reset_preflight(port)

    def _edit_docker_image(self, port: Any) -> None:
        docker_image = self.settings_service.apply_docker_image(
            port.prompt("Docker image name", port.docker_image)
        )
        if docker_image is not None:
            port.docker_image = docker_image

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

    def _save_project(self, port: Any) -> None:
        self.settings_service.save_project_settings(
            parameters=port.build_params,
            targets=port.build_targets,
            docker_image=port.docker_image,
        )
        port.status = "Project saved"


def project_settings_action_controller(
    config: dict[str, Any],
    *,
    app_dir: Path,
    default_config_path: Path,
    save_config: Callable[[dict[str, Any]], None],
    save_runtime_settings: Callable[..., None] = config_runtime_api.save_current_runtime_build_settings,
    target_selection_controller_factory: Callable[[], Any] | None = None,
    remote_file_selection_controller: Any | None = None,
    profile_action_controller: Any | None = None,
    project_picker_controller: Any | None = None,
    reload_runtime: Callable[[], Any] | None = None,
) -> ProjectSettingsActionController:
    return ProjectSettingsActionController(
        config,
        app_dir=app_dir,
        default_config_path=default_config_path,
        save_config=save_config,
        save_runtime_settings=save_runtime_settings,
        target_selection_controller_factory=target_selection_controller_factory,
        remote_file_selection_controller=remote_file_selection_controller,
        profile_action_controller=profile_action_controller,
        project_picker_controller=project_picker_controller,
        reload_runtime=reload_runtime,
    )


def _noop() -> None:
    return None
