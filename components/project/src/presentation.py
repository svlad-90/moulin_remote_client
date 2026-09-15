"""Project mapping presentation service."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from components.config.api import accessors as config_accessors
from components.project.src.model import ProjectMappingModelService, project_mapping_model_service


class ProjectMappingPresentationService:
    """Own browser and selection display policy for project mappings."""

    def __init__(self, *, model_service: ProjectMappingModelService | None = None) -> None:
        self.model_service = model_service or project_mapping_model_service()

    def mapping_path_mark(self, path: str, selected_paths: set[str], mapped_paths: set[str]) -> str:
        clean = self.model_service.normalize_mapping_path(path)
        if clean in selected_paths:
            return "S"
        if any(self.model_service.is_descendant_mapping_path(selected, clean) for selected in selected_paths):
            return "s"
        if clean in mapped_paths:
            return "*"
        if any(self.model_service.is_descendant_mapping_path(mapped, clean) for mapped in mapped_paths):
            return "+"
        return " "

    def mapping_name_from_path(self, path: str) -> str:
        clean = path.strip("/").replace("/", "-").replace("_", "-")
        clean = "-".join(part for part in clean.split("-") if part)
        return clean or "mapping"

    def mapping_draft_for_entry(self, entry: dict[str, str]) -> dict[str, Any]:
        name = self.mapping_name_from_path(entry.get("path", ""))
        return {
            "path": entry.get("path", ""),
            "name": name,
            "local": entry.get("path", ""),
            "role": name,
            "push": True,
        }

    def refresh_mapping_draft_for_entry(self, draft: dict[str, Any], entry: dict[str, str]) -> dict[str, Any]:
        if entry.get("path", "") == draft.get("path", ""):
            return draft
        return self.mapping_draft_for_entry(entry)

    def mapping_path_sets(
        self,
        raw_project_mappings: list[Any],
        selected_names: set[str],
    ) -> tuple[set[str], set[str]]:
        mapped_paths = {
            self.model_service.normalize_mapping_path(str(mapping.get("remote", "")))
            for mapping in raw_project_mappings
            if isinstance(mapping, dict) and str(mapping.get("remote", "")).strip()
        }
        selected_paths = {
            self.model_service.normalize_mapping_path(str(mapping.get("remote", "")))
            for mapping in raw_project_mappings
            if isinstance(mapping, dict)
            and str(mapping.get("name", "")) in selected_names
            and str(mapping.get("remote", "")).strip()
        }
        return mapped_paths, selected_paths

    def mapping_state_label(self, path: str, selected_paths: set[str], mapped_paths: set[str]) -> str:
        selected = path in selected_paths
        mapped = path in mapped_paths
        has_selected_children = any(
            self.model_service.is_descendant_mapping_path(child, path) for child in selected_paths
        )
        has_mapped_children = any(self.model_service.is_descendant_mapping_path(child, path) for child in mapped_paths)
        if selected:
            return "selected"
        if has_selected_children:
            return "selected children"
        if mapped:
            return "yes"
        if has_mapped_children:
            return "mapped children"
        return "no"

    def listing_with_parent_entry(self, current_dir: str, entries: list[dict[str, str]]) -> list[dict[str, str]]:
        if current_dir == ".":
            return list(entries)
        parent = str(PurePosixPath(current_dir).parent)
        return [{"path": "." if parent in ("", ".") else parent, "kind": "parent"}] + list(entries)

    def mapping_browser_entry_name(self, entry: dict[str, str]) -> str:
        return "../" if entry["kind"] == "parent" else PurePosixPath(entry["path"]).name

    def mapping_browser_entry_kind(self, entry: dict[str, str]) -> str:
        return "directory" if entry["kind"] == "parent" else entry["kind"]

    def mapping_browser_entry_label(
        self,
        entry: dict[str, str],
        *,
        selected_paths: set[str],
        mapped_paths: set[str],
    ) -> str:
        mark = self.mapping_path_mark(entry["path"], selected_paths, mapped_paths)
        name = self.mapping_browser_entry_name(entry)
        if entry["kind"] in ("directory", "parent"):
            return f"{mark} [d] {name}/"
        return f"{mark} [f] {name}"

    def mapping_selection_row_label(self, mapping: dict[str, Any], selected: set[str]) -> str:
        selected_mark = "*" if mapping["name"] in selected else " "
        push = "push" if mapping["push"] else "pull-only"
        return f"[{selected_mark}] {mapping['name']} ({mapping['kind']}, {push})"

    def mapping_selection_detail_for_config(
        self,
        config: dict[str, Any],
        app_dir: Path,
        mapping: dict[str, Any],
        *,
        selected_count: int,
        total_count: int,
    ) -> dict[str, str]:
        local_path = config_accessors.local_project_dir_for_config(config, app_dir) / mapping["local"]
        return {
            "name": str(mapping["name"]),
            "role": str(mapping["role"]),
            "kind": str(mapping["kind"]),
            "push": "yes" if mapping["push"] else "no",
            "remote": str(mapping["remote"]),
            "local": str(local_path),
            "selected": f"{selected_count}/{total_count}",
        }


def project_mapping_presentation_service() -> ProjectMappingPresentationService:
    return ProjectMappingPresentationService()
