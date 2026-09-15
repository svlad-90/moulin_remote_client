"""Project profile screen use-case service."""

from __future__ import annotations

from typing import Any

from components.config.api import profiles as config_profile_api


class ProjectProfileScreenService:
    """Execute project profile actions and return updated screen state."""

    def __init__(self, config: dict[str, Any], *, profile_action_controller: Any | None = None) -> None:
        self.config = config
        self.profile_action_controller = profile_action_controller

    def add_project(self, port: Any) -> dict[str, Any]:
        if self.profile_action_controller is None:
            port.add_project_profile()
        else:
            self.profile_action_controller.add_project_profile(port)
        projects = self._projects()
        return {
            "projects": projects,
            "project_index": config_profile_api.active_profile_index(projects, str(self.config.get("active_project", ""))),
            "focus": "fields" if projects else "projects",
        }

    def delete_project(self, port: Any, selected_project: dict[str, Any], current_index: int) -> dict[str, Any]:
        if self.profile_action_controller is None:
            port.delete_project_profile(selected_project)
        else:
            self.profile_action_controller.delete_project_profile(port, selected_project)
        projects = self._projects()
        return {
            "projects": projects,
            "project_index": min(current_index, max(0, len(projects) - 1)),
            "focus": "projects",
        }

    def set_active_project(self, port: Any, selected_project: dict[str, Any]) -> None:
        if self.profile_action_controller is None:
            port.set_active_project(selected_project)
            return
        self.profile_action_controller.set_active_project(port, selected_project)

    def _projects(self) -> list[dict[str, Any]]:
        return [item for item in self.config.get("projects", []) if isinstance(item, dict)]


def project_profile_screen_service(
    config: dict[str, Any],
    *,
    profile_action_controller: Any | None = None,
) -> ProjectProfileScreenService:
    return ProjectProfileScreenService(config, profile_action_controller=profile_action_controller)
