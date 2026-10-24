"""Project configuration field service."""

from __future__ import annotations

from typing import Any

from components.config.api import accessors
from components.config.api import profiles as config_profiles
from components.product_types.api import registry as product_type_registry_api


class ProjectFieldService:
    """Own project field update, availability, and enter-action use cases."""

    def project_is_active(self, project: dict[str, Any], active_project: str) -> bool:
        return str(active_project) in {
            str(project.get("id") or ""),
            str(project.get("name") or ""),
        }

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

    def available_product_type_options(self) -> list[dict[str, str]]:
        return [
            {
                "type": adapter.type_id,
                "label": adapter.label or adapter.type_id,
                "description": adapter.description,
            }
            for adapter in product_type_registry_api.product_type_registry().adapters()
        ]

    def available_product_types(self) -> list[str]:
        return [option["type"] for option in self.available_product_type_options()]

    def next_product_type_value(self, current: str) -> str:
        product_types = self.available_product_types()
        if not product_types:
            return "gen5_xen_android"
        clean_current = current.strip()
        if clean_current not in product_types:
            return product_types[0]
        return product_types[(product_types.index(clean_current) + 1) % len(product_types)]

    def project_dir_field_update(self, key: str, value: str) -> tuple[str, str]:
        if key != "project_dir" or not value.startswith("/"):
            return value, ""
        projects_dir, project_name = config_profiles.split_remote_project_path(value)
        return project_name or value, projects_dir

    def runtime_reload_needed(self, key: str) -> bool:
        return key in ("project_dir", "docker_image", "board_artifacts")

    def project_source_reload_needed(self, key: str) -> bool:
        return key in ("git_url", "git_ref")

    def preflight_reset_needed(self, key: str) -> bool:
        return key in ("project_dir", "git_url", "git_ref")

    def docker_image_update_needed(self, key: str) -> bool:
        return key == "docker_image"

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
        if kind in ("text", "git_ref", "product_type"):
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
            "product_type": "Enter selects the product model used to derive domains and runtime capabilities.",
            "project_dir": f"Project checkout directory name under Projects dir ({build_host_projects_dir or '<not set>'}).",
            "local_project_dir": f"Local overlay for mapped pull/push. Relative paths are resolved from {app_dir}.",
            "git_url": "Git URL used by Prepare remote project when checkout origin should be validated.",
            "git_ref": "Enter selects a branch from the remote Git URL when reachable, otherwise manual input. Parameters are read from the selected ref; the checkout is switched separately.",
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
        active = config_profiles.active_project(config)
        return self.project_is_active(project, str(config.get("active_project", ""))) or (
            bool(str(project.get("name") or ""))
            and str(project.get("name") or "") == str(active.get("name") or "")
        )

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
            active_project=(
                str(project.get("id") or project.get("name") or "")
                if self.project_is_active_for_config(project, config)
                else str(config.get("active_project", ""))
            ),
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
            active_project=(
                str(project.get("id") or project.get("name") or "")
                if self.project_is_active_for_config(project, config)
                else str(config.get("active_project", ""))
            ),
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
        if kind == "product_type":
            return {"action": "select-product-type"}
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
