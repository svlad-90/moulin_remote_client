"""Project settings use-case service."""

from __future__ import annotations

from typing import Any

from components.project_config.api import fields as project_field_api


class ProjectSettingsService:
    """Apply project settings policy without owning persistence."""

    def __init__(
        self,
        *,
        settings_policy_service: project_field_api.ProjectSettingsPolicyService | None = None,
    ) -> None:
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

def project_settings_service() -> ProjectSettingsService:
    return ProjectSettingsService()
