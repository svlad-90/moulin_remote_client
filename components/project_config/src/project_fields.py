"""Project configuration field service."""

from __future__ import annotations

from typing import Any

from components.config.api import accessors
from components.config.api import profiles as config_profiles


class ProjectFieldService:
    """Own project field update, availability, and enter-action use cases."""

    def project_is_active(self, project: dict[str, Any], active_project: str) -> bool:
        return str(project.get("name", "")) == str(active_project)

    def field_value(self, project: dict[str, Any], field: dict[str, Any]) -> str:
        key = str(field["key"])
        if field["kind"] == "param":
            name = key.removeprefix("param:")
            params = project.get("parameters", {})
            if isinstance(params, dict) and name in params:
                return str(params.get(name, ""))
            return str(field["param"].get("default", ""))
        return str(project.get(key, ""))

    def normalize_value(self, key: str, value: str) -> str:
        return value.strip()

    def project_dir_field_update(self, key: str, value: str) -> tuple[str, str]:
        if key != "project_dir" or not value.startswith("/"):
            return value, ""
        projects_dir, project_name = config_profiles.split_remote_project_path(value)
        return project_name or value, projects_dir

    def runtime_reload_needed(self, key: str) -> bool:
        return key in ("project_dir", "docker_image", "board_artifacts")

    def preflight_reset_needed(self, key: str) -> bool:
        return key in ("project_dir", "git_url", "git_ref")

    def docker_image_update_needed(self, key: str) -> bool:
        return key == "docker_image"

    def apply_inline_field_update_for_config(
        self,
        config: dict[str, Any],
        project: dict[str, Any],
        key: str,
        raw_value: str,
    ) -> dict[str, Any]:
        value = self.normalize_value(key, raw_value)
        value, projects_dir = self.project_dir_field_update(key, value)
        config_profiles.update_project_profile_field(config, project, key, value, projects_dir=projects_dir)
        active = self.project_is_active_for_config(project, config)
        return {
            "value": value,
            "status": f"{key} updated",
            "runtime_reload": active and self.runtime_reload_needed(key),
            "preflight_reset": active and self.preflight_reset_needed(key),
            "docker_image": value if active and self.docker_image_update_needed(key) else None,
        }

    def apply_active_file_selection_for_config(
        self,
        config: dict[str, Any],
        key: str,
        selected: str,
    ) -> dict[str, Any]:
        config_profiles.update_project_profile_field(
            config,
            config_profiles.active_project(config),
            key,
            selected,
        )
        labels = {
            "moulin_manifest": "Moulin manifest",
            "dockerfile": "Dockerfile",
        }
        return {
            "status": f"{labels.get(key, key)}: {selected}",
            "manifest_cache_reset": key == "moulin_manifest",
            "build_params_reload": key == "moulin_manifest",
            "preflight_reset": True,
        }

    def apply_active_settings_field_for_config(
        self,
        config: dict[str, Any],
        key: str,
        raw_value: str,
    ) -> dict[str, Any]:
        value = self.normalize_value(key, raw_value)
        config_profiles.update_project_profile_field(
            config,
            config_profiles.active_project(config),
            key,
            value,
        )
        return {
            "value": value,
            "preflight_reset": key == "git_url",
            "docker_image": value if key == "docker_image" else None,
        }

    def field_enabled(
        self,
        field: dict[str, Any],
        project: dict[str, Any],
        *,
        active_project: str,
        connected: bool,
        remote_has_ssh: bool,
        remote_has_project_dir: bool,
    ) -> bool:
        kind = str(field["kind"])
        if kind in ("text", "git_ref"):
            return True
        if not self.project_is_active(project, active_project):
            return False
        if kind == "param":
            return True
        if kind in ("targets", "board_artifacts"):
            return True
        if kind == "remote_dir":
            return connected and remote_has_ssh
        if kind in ("manifest", "dockerfile"):
            return connected and remote_has_ssh and remote_has_project_dir
        return True

    def field_disabled_reason(
        self,
        field: dict[str, Any],
        project: dict[str, Any],
        *,
        active_project: str,
        remote_has_user: bool,
        remote_has_host: bool,
        remote_has_project_dir: bool,
    ) -> str:
        kind = str(field["kind"])
        if not self.project_is_active(project, active_project):
            return "set this project active first"
        if kind in ("remote_dir", "manifest", "dockerfile"):
            if not remote_has_user:
                return "set SSH user first"
            if not remote_has_host:
                return "set SSH host first"
            if kind == "remote_dir":
                return "connect to the build host first"
            if not remote_has_project_dir:
                return "select remote project directory first"
            return "connect to the build host first"
        return ""

    def field_hint(
        self,
        field: dict[str, Any],
        *,
        build_host_projects_dir: str,
        app_dir: str,
    ) -> str:
        key = str(field["key"])
        kind = str(field["kind"])
        hints = {
            "name": "Unique local project id. Renaming an active project preserves active selection.",
            "label": "Display label for this project profile.",
            "project_dir": f"Project checkout directory name under Projects dir ({build_host_projects_dir or '<not set>'}).",
            "local_project_dir": f"Local overlay for mapped pull/push. Relative paths are resolved from {app_dir}.",
            "git_url": "Git URL used by Prepare remote project when checkout origin should be validated.",
            "git_ref": "Enter selects a branch from the remote Git URL when reachable, otherwise manual input. Existing checkouts are checked but not switched automatically.",
            "moulin_manifest": "Search tracked root YAML files on the active remote and save a Moulin manifest.",
            "dockerfile": "Search tracked Dockerfiles on the active remote and save a Dockerfile path.",
            "targets": "Space toggles Ninja build targets, Enter saves, Esc cancels.",
            "board_artifacts": "Space toggles artifacts copied to the board host, Enter saves, Esc cancels.",
            "docker_image": "Docker image name/tag used for remote Docker and product build commands.",
        }
        if kind == "param":
            return str(field["param"].get("desc", "")) or "Enter switches this Moulin parameter to its next allowed value."
        return hints.get(key, "")

    def project_is_active_for_config(self, project: dict[str, Any], config: dict[str, Any]) -> bool:
        return self.project_is_active(project, str(config.get("active_project", "")))

    def field_enabled_for_config(
        self,
        field: dict[str, Any],
        project: dict[str, Any],
        config: dict[str, Any],
        *,
        connected: bool,
    ) -> bool:
        return self.field_enabled(
            field,
            project,
            active_project=str(config.get("active_project", "")),
            connected=connected,
            remote_has_ssh=accessors.remote_has_ssh_for_config(config),
            remote_has_project_dir=accessors.remote_has_project_dir_for_config(config),
        )

    def field_disabled_reason_for_config(
        self,
        field: dict[str, Any],
        project: dict[str, Any],
        config: dict[str, Any],
    ) -> str:
        return self.field_disabled_reason(
            field,
            project,
            active_project=str(config.get("active_project", "")),
            remote_has_user=accessors.remote_has_user_for_config(config),
            remote_has_host=accessors.remote_has_host_for_config(config),
            remote_has_project_dir=accessors.remote_has_project_dir_for_config(config),
        )

    def field_enter_action_for_config(
        self,
        field: dict[str, Any],
        project: dict[str, Any],
        config: dict[str, Any],
        *,
        connected: bool,
    ) -> dict[str, Any]:
        if not self.field_enabled_for_config(field, project, config, connected=connected):
            return {
                "action": "status",
                "status": self.field_disabled_reason_for_config(field, project, config),
            }
        kind = str(field["kind"])
        if kind == "manifest":
            return {"action": "select-moulin-manifest"}
        if kind == "dockerfile":
            return {"action": "select-dockerfile"}
        if kind == "remote_dir":
            return {"action": "edit-project-remote-dir"}
        if kind == "git_ref":
            return {"action": "edit-project-git-ref"}
        if kind == "targets":
            return {"action": "select-build-targets"}
        if kind == "board_artifacts":
            return {"action": "select-board-artifacts"}
        if kind == "param":
            return {"action": "cycle-parameter", "param": field["param"]}
        return {
            "action": "edit-text",
            "key": str(field["key"]),
            "value": self.field_value(project, field),
            "label": str(field["label"]),
        }

    def field_hint_for_config(
        self,
        field: dict[str, Any],
        config: dict[str, Any],
        *,
        app_dir: str,
    ) -> str:
        return self.field_hint(
            field,
            build_host_projects_dir=accessors.build_host_projects_dir_for_config(config),
            app_dir=app_dir,
        )


def project_field_service() -> ProjectFieldService:
    return ProjectFieldService()
