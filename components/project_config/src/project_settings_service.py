"""Project settings use-case service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.project_config.api import fields as project_field_api
from components.build_runtime.api import runtime as config_runtime_api


class ProjectSettingsService:
    """Apply and persist project settings without owning UI flow."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        app_dir: Path,
        default_config_path: Path,
        save_config: Callable[[dict[str, Any]], None],
        save_runtime_settings: Callable[..., None] = config_runtime_api.save_current_runtime_build_settings,
        settings_policy_service: project_field_api.ProjectSettingsPolicyService | None = None,
    ) -> None:
        self.config = config
        self.app_dir = app_dir
        self.default_config_path = default_config_path
        self.save_config = save_config
        self.save_runtime_settings = save_runtime_settings
        self.settings_policy_service = (
            settings_policy_service or project_field_api.project_settings_policy_service()
        )

    def cycle_parameter(self, build_params: dict[str, str], param: dict[str, Any]) -> str | None:
        name = param["name"]
        current = build_params.get(name, str(param["default"]))
        value = self.settings_policy_service.next_parameter_value(param, current)
        if value is None:
            return None
        build_params[name] = value
        return f"{name}={build_params[name]}"

    def apply_local_project_dir(self, value: str) -> None:
        project_field_api.apply_active_project_settings_field_for_config(
            self.config,
            "local_project_dir",
            value,
        )

    def apply_git_url(self, value: str) -> dict[str, Any]:
        return project_field_api.apply_active_project_settings_field_for_config(
            self.config,
            "git_url",
            value,
        )

    def apply_docker_image(self, value: str) -> str | None:
        plan = project_field_api.apply_active_project_settings_field_for_config(
            self.config,
            "docker_image",
            value,
        )
        docker_image = plan["docker_image"]
        if docker_image is None:
            return None
        return str(docker_image)

    def save_project_settings(
        self,
        *,
        parameters: dict[str, str],
        targets: list[str],
        docker_image: str,
    ) -> None:
        self.save_runtime_settings(
            self.config,
            parameters=parameters,
            targets=targets,
            docker_image=docker_image,
            app_dir=self.app_dir,
            default_path=self.default_config_path,
        )
        self.save_config(self.config)


def project_settings_service(
    config: dict[str, Any],
    *,
    app_dir: Path,
    default_config_path: Path,
    save_config: Callable[[dict[str, Any]], None],
    save_runtime_settings: Callable[..., None] = config_runtime_api.save_current_runtime_build_settings,
) -> ProjectSettingsService:
    return ProjectSettingsService(
        config,
        app_dir=app_dir,
        default_config_path=default_config_path,
        save_config=save_config,
        save_runtime_settings=save_runtime_settings,
    )
