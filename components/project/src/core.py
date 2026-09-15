"""Core project mapping CRUD service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.config.api import profiles as config_profiles
from components.project.src.model import ProjectMappingModelService, project_mapping_model_service


def _project_mapping_selection_service(mapping_service: "ProjectMappingCoreService") -> Any:
    from components.project.src.selection import project_mapping_selection_service

    return project_mapping_selection_service(mapping_service=mapping_service)


class ProjectMappingCoreService:
    """Own core project mapping CRUD and persistence use cases."""

    def __init__(self, *, model_service: ProjectMappingModelService | None = None) -> None:
        self.model_service = model_service or project_mapping_model_service()

    def mappings_for_config(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        raw_config_mappings = config.get("mappings", [])
        legacy_mappings = raw_config_mappings if isinstance(raw_config_mappings, list) else []
        return self.model_service.mappings_from_project_config(config_profiles.active_project(config), legacy_mappings)

    def add_mapping_to_active_project(
        self,
        config: dict[str, Any],
        *,
        name: str,
        role: str,
        remote: str,
        local: str,
        kind: str,
        push: bool,
    ) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("empty name")
        existing = {mapping["name"] for mapping in self.mappings_for_config(config)}
        if clean_name in existing:
            raise ValueError(f"already exists: {clean_name}")
        clean_remote = self.model_service.normalize_mapping_path(remote)
        clean_local = self.model_service.normalize_mapping_path(local)
        if kind not in ("file", "directory"):
            raise ValueError("kind must be file or directory")
        mapping = {
            "name": clean_name,
            "role": role or clean_name,
            "remote": clean_remote,
            "local": clean_local,
            "kind": kind,
            "push": push,
        }
        project = config_profiles.active_project(config)
        raw_mappings = list(project.setdefault("mappings", []))
        raw_mappings.append(mapping)
        project["mappings"] = raw_mappings
        return mapping

    def store_mapping_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        *,
        name: str,
        role: str,
        remote: str,
        local: str,
        kind: str,
        push: bool,
        save_config: Callable[[dict[str, Any]], Any],
    ) -> dict[str, Any]:
        mapping = self.add_mapping_to_active_project(
            config,
            name=name,
            role=role.strip() or name.strip(),
            remote=remote,
            local=local,
            kind=kind,
            push=push,
        )
        save_config(config)
        selection_service = _project_mapping_selection_service(self)
        selected = selection_service.read_mapping_selection_for_config(config, selection_path, required=False)
        if mapping["name"] not in selected:
            selected.append(mapping["name"])
            selection_service.store_mapping_selection_for_config(
                config,
                selection_path,
                selected,
                save_config=save_config,
            )
        return mapping

    def store_mapping_action_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        *,
        name: str,
        role: str,
        remote: str,
        local: str,
        kind: str,
        push: bool,
        save_config: Callable[[dict[str, Any]], Any],
    ) -> dict[str, Any]:
        if not name:
            return {"ok": False, "status": "Mapping add cancelled: empty name"}
        try:
            mapping = self.store_mapping_for_config(
                config,
                selection_path,
                name=name,
                role=role,
                remote=remote,
                local=local,
                kind=kind,
                push=push,
                save_config=save_config,
            )
        except ValueError as exc:
            if str(exc).startswith("already exists: "):
                return {"ok": False, "status": f"Mapping already exists: {name}"}
            return {"ok": False, "status": f"Mapping add failed: {exc}"}
        return {"ok": True, "status": f"Mapping added: {mapping['name']}", "mapping": mapping}

    def store_mapping_from_tree_entry_action_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        entry: dict[str, str],
        *,
        name: str,
        local: str,
        role: str,
        push: bool,
        save_config: Callable[[dict[str, Any]], Any],
    ) -> dict[str, Any]:
        clean_name = name.strip()
        return self.store_mapping_action_for_config(
            config,
            selection_path,
            name=clean_name,
            role=role.strip() or clean_name,
            remote=entry["path"],
            local=local,
            kind="directory" if entry["kind"] == "parent" else entry["kind"],
            push=push,
            save_config=save_config,
        )

    def remove_mapping_from_active_project_by_name(self, config: dict[str, Any], name: str) -> bool:
        project = config_profiles.active_project(config)
        raw_mappings = [mapping for mapping in project.get("mappings", []) if isinstance(mapping, dict)]
        remaining = [mapping for mapping in raw_mappings if str(mapping.get("name", "")).strip() != name]
        project["mappings"] = remaining
        return len(remaining) != len(raw_mappings)

    def remove_mapping_from_active_project_by_remote_path(self, config: dict[str, Any], remote_path: str) -> list[str]:
        target = self.model_service.normalize_mapping_path(remote_path)
        project = config_profiles.active_project(config)
        raw_mappings = [mapping for mapping in project.get("mappings", []) if isinstance(mapping, dict)]
        removed_names = [
            str(mapping.get("name", ""))
            for mapping in raw_mappings
            if self.model_service.normalize_mapping_path(str(mapping.get("remote", ""))) == target
        ]
        if not removed_names:
            return []
        project["mappings"] = [
            mapping
            for mapping in raw_mappings
            if self.model_service.normalize_mapping_path(str(mapping.get("remote", ""))) != target
        ]
        return removed_names

    def remove_mapping_by_remote_path_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        remote_path: str,
        *,
        save_config: Callable[[dict[str, Any]], Any],
    ) -> list[str]:
        target = self.model_service.normalize_mapping_path(remote_path)
        removed_names = self.remove_mapping_from_active_project_by_remote_path(config, target)
        if not removed_names:
            return []
        removed = set(removed_names)
        save_config(config)
        selection_service = _project_mapping_selection_service(self)
        selected = [
            name
            for name in selection_service.read_mapping_selection_for_config(config, selection_path, required=False)
            if name not in removed
        ]
        selection_service.store_mapping_selection_for_config(
            config,
            selection_path,
            selected,
            save_config=save_config,
        )
        return removed_names

    def remove_mapping_by_remote_path_action_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        remote_path: str,
        *,
        save_config: Callable[[dict[str, Any]], Any],
    ) -> dict[str, Any]:
        try:
            target = self.model_service.normalize_mapping_path(remote_path)
            removed_names = self.remove_mapping_by_remote_path_for_config(
                config,
                selection_path,
                target,
                save_config=save_config,
            )
        except ValueError as exc:
            return {"ok": False, "status": f"Mapping remove failed: {exc}"}
        if not removed_names:
            return {"ok": False, "status": f"Mapping not found: {target}"}
        return {"ok": True, "status": f"Mapping removed: {', '.join(removed_names)}", "removed_names": removed_names}


def project_mapping_core_service() -> ProjectMappingCoreService:
    return ProjectMappingCoreService()
