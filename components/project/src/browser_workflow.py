"""Project tree browser workflow service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.config.api import profiles as config_profiles
from components.project.src.core import ProjectMappingCoreService, project_mapping_core_service
from components.project.src.presentation import ProjectMappingPresentationService, project_mapping_presentation_service
from components.project.src.selection import ProjectMappingSelectionService, project_mapping_selection_service


class ProjectBrowserWorkflowService:
    """Own project tree browser state and mapping toggle use cases."""

    def __init__(
        self,
        *,
        mapping_service: ProjectMappingCoreService | None = None,
        presentation_service: ProjectMappingPresentationService | None = None,
        selection_service: ProjectMappingSelectionService | None = None,
    ) -> None:
        self.mapping_service = mapping_service or project_mapping_core_service()
        self.presentation_service = presentation_service or project_mapping_presentation_service()
        self.selection_service = selection_service or project_mapping_selection_service(mapping_service=self.mapping_service)

    def path_state(self, config: dict[str, Any], selection_path: Path) -> dict[str, Any]:
        raw_project_mappings = config_profiles.active_project(config).get("mappings", [])
        selected_names = set(self.selection_service.read_mapping_selection_for_config(config, selection_path, required=False))
        mapped_paths, selected_paths = self.presentation_service.mapping_path_sets(raw_project_mappings, selected_names)
        return {
            "raw_project_mappings": raw_project_mappings,
            "selected_names": selected_names,
            "mapped_paths": mapped_paths,
            "selected_paths": selected_paths,
        }

    def current_entry(self, entries: list[dict[str, str]], index: int) -> dict[str, str]:
        if not entries:
            return {"path": "", "kind": "directory"}
        return entries[min(max(0, index), len(entries) - 1)]

    def toggle_action_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        entry: dict[str, str],
        draft: dict[str, Any],
        *,
        mapped_paths: set[str],
        save_config: Callable[[dict[str, Any]], Any],
    ) -> dict[str, Any]:
        if entry["path"] in mapped_paths:
            return self.mapping_service.remove_mapping_by_remote_path_action_for_config(
                config,
                selection_path,
                entry["path"],
                save_config=save_config,
            )
        return self.mapping_service.store_mapping_from_tree_entry_action_for_config(
            config,
            selection_path,
            entry,
            name=str(draft["name"]),
            local=str(draft["local"]),
            role=str(draft["role"]),
            push=bool(draft["push"]),
            save_config=save_config,
        )

    def key_action(
        self,
        *,
        entries_exist: bool,
        current_kind: str,
        up: bool = False,
        down: bool = False,
        enter: bool = False,
        toggle: bool = False,
        edit_name: bool = False,
        edit_local: bool = False,
        edit_role: bool = False,
        edit_push: bool = False,
        quit_key: bool = False,
    ) -> dict[str, Any]:
        if up and entries_exist:
            return {"action": "move", "delta": -1}
        if down and entries_exist:
            return {"action": "move", "delta": 1}
        if enter and entries_exist:
            if current_kind in ("directory", "parent"):
                return {"action": "open"}
            return {"action": "status", "status": "Space toggles the selected file mapping"}
        if toggle and entries_exist:
            return {"action": "toggle"}
        if edit_name and entries_exist:
            return {"action": "edit_name"}
        if edit_local and entries_exist:
            return {"action": "edit_local"}
        if edit_role and entries_exist:
            return {"action": "edit_role"}
        if edit_push and entries_exist:
            return {"action": "edit_push"}
        if quit_key:
            return {"action": "quit"}
        return {"action": "noop"}


def project_browser_workflow_service() -> ProjectBrowserWorkflowService:
    return ProjectBrowserWorkflowService()
