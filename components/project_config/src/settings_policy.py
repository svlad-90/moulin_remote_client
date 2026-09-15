"""Project settings action policy service."""

from __future__ import annotations

from typing import Any


class ProjectSettingsPolicyService:
    """Own project settings labels, descriptions, and parameter cycling rules."""

    def action_label(
        self,
        action: dict[str, Any],
        *,
        active_project: dict[str, Any],
        build_params: dict[str, str],
        local_project_dir: str,
        moulin_manifest_name: str,
        project_git_url: str,
        configured_dockerfile: str,
        build_targets: str,
        board_artifacts: str,
        docker_image: str,
    ) -> str:
        kind = action["kind"]
        if kind == "select_project":
            return f"Active project: {active_project.get('label') or active_project.get('name')}"
        if kind == "add_project":
            return "Add project"
        if kind == "delete_project":
            return "Delete active project"
        if kind == "param":
            param = action["param"]
            name = param["name"]
            value = build_params.get(name, str(param["default"]))
            choices = "/".join(str(choice) for choice in param.get("choices", []))
            return f"Edit {name}: {value} ({choices})"
        if kind == "local_project_dir":
            return f"Edit local overlay dir: {local_project_dir}"
        if kind == "manifest":
            return f"Select Moulin manifest: {moulin_manifest_name}"
        if kind == "git_url":
            return f"Edit project Git URL: {project_git_url or '<not set>'}"
        if kind == "dockerfile":
            return f"Select Dockerfile: {configured_dockerfile}"
        if kind == "targets":
            return f"Select build targets: {build_targets}"
        if kind == "board_artifacts":
            return f"Select board artifacts: {board_artifacts or build_targets}"
        if kind == "docker":
            return f"Edit Docker image name: {docker_image}"
        if kind == "save":
            return "Save project"
        if kind == "back":
            return "Back to main menu"
        return str(kind)

    def action_description(self, action: dict[str, Any]) -> str:
        kind = action["kind"]
        if kind == "select_project":
            return "Choose which project profile provides manifest, build parameters, targets, Docker image, and local overlay."
        if kind == "add_project":
            return "Create a new project profile initialized from the current project values."
        if kind == "delete_project":
            return "Remove the active project profile. At least one project profile is kept."
        if kind == "param":
            param = action["param"]
            desc = str(param.get("desc", ""))
            return desc or "Switch this Moulin parameter to its next allowed value."
        if kind == "local_project_dir":
            return "Local overlay directory used for mapped file pull/push operations."
        if kind == "manifest":
            return "Search the remote project checkout for YAML files, validate Moulin-shaped files, and save the selected path in the active project."
        if kind == "git_url":
            return "Git URL used by Prepare remote project when the checkout is missing or origin should be validated."
        if kind == "dockerfile":
            return "Search the remote project checkout for Dockerfiles, validate files that start with FROM, and save the selected path in the active project."
        if kind == "targets":
            return "Choose Ninja targets from the Moulin manifest and selected parameter overrides."
        if kind == "board_artifacts":
            return "Choose built artifacts copied from the build host to the board host."
        if kind == "docker":
            return "Edit the Docker image name/tag stored in the active project and used for remote Docker and product build commands."
        if kind == "save":
            return "Persist current project parameters, targets, manifest, Dockerfile, Docker image, and local overlay."
        if kind == "back":
            return "Return to the main Moulin client menu without writing project changes."
        return ""

    def next_parameter_value(self, param: dict[str, Any], current: str) -> str | None:
        choices = [str(choice) for choice in param.get("choices", [])]
        if not choices:
            return None
        try:
            index = choices.index(current)
        except ValueError:
            index = -1
        return choices[(index + 1) % len(choices)]


def project_settings_policy_service() -> ProjectSettingsPolicyService:
    return ProjectSettingsPolicyService()
