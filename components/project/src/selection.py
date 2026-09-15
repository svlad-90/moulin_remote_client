"""Project mapping selection service."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from components.config.api import profiles as config_profiles

if TYPE_CHECKING:
    from components.project.src.core import ProjectMappingCoreService


def _project_mapping_core_service() -> ProjectMappingCoreService:
    from components.project.src.core import project_mapping_core_service

    return project_mapping_core_service()


class ProjectMappingSelectionService:
    """Own active mapping selection state and selection-screen use cases."""

    def __init__(self, *, mapping_service: ProjectMappingCoreService | None = None) -> None:
        self.mapping_service = mapping_service or _project_mapping_core_service()

    def project_mapping_selection_from(self, project: dict[str, Any]) -> list[str]:
        raw_names = project.get("active_mappings", [])
        if not isinstance(raw_names, list):
            return []
        names: list[str] = []
        for raw in raw_names:
            name = str(raw).strip()
            if name:
                names.append(name)
        return names

    def read_mapping_selection_file(self, path: Path, *, required: bool) -> list[str]:
        if not path.exists():
            if required:
                raise SystemExit(f"mapping selection file does not exist: {path}")
            return []
        names = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                names.append(line)
        if required and not names:
            raise SystemExit(f"no mappings selected: {path}")
        return names

    def read_mapping_selection_from(self, project: dict[str, Any], path: Path, *, required: bool) -> list[str]:
        project_names = self.project_mapping_selection_from(project)
        if project_names:
            return project_names
        return self.read_mapping_selection_file(path, required=required)

    def read_mapping_selection_for_config(self, config: dict[str, Any], path: Path, *, required: bool) -> list[str]:
        return self.read_mapping_selection_from(config_profiles.active_project(config), path, required=required)

    def write_mapping_selection_file(self, path: Path, names: list[str]) -> None:
        text = "\n".join(names)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + ("\n" if text else ""), encoding="utf-8")

    def write_mapping_selection_for_config(self, config: dict[str, Any], path: Path, names: list[str]) -> None:
        config_profiles.active_project(config)["active_mappings"] = list(names)
        self.write_mapping_selection_file(path, names)

    def store_mapping_selection_for_config(
        self,
        config: dict[str, Any],
        path: Path,
        names: list[str],
        *,
        save_config: Callable[[dict[str, Any]], Any],
        write_line: Callable[[str], Any] | None = None,
    ) -> None:
        self.write_mapping_selection_for_config(config, path, names)
        save_config(config)
        if write_line is not None:
            write_line(f"mapping selection: {path}")

    def select_mappings_from(
        self,
        all_mappings: list[dict[str, Any]],
        names: list[str],
    ) -> list[dict[str, Any]]:
        by_name = {mapping["name"]: mapping for mapping in all_mappings}
        if not names:
            raise SystemExit("mapping names are required; use 'all' for every mapping")
        if names == ["all"]:
            return all_mappings
        missing = [name for name in names if name not in by_name]
        if missing:
            raise SystemExit("unknown mapping(s): " + ", ".join(missing))
        return [by_name[name] for name in names]

    def select_mappings_for_config(self, config: dict[str, Any], names: list[str]) -> list[dict[str, Any]]:
        return self.select_mappings_from(self.mapping_service.mappings_for_config(config), names)

    def active_mapping_state_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
    ) -> tuple[list[str], list[dict[str, Any]], str | None]:
        names = self.read_mapping_selection_for_config(config, selection_path, required=False)
        if not names:
            return names, [], None
        try:
            return names, self.select_mappings_for_config(config, names), None
        except SystemExit as exc:
            return names, [], str(exc)

    def mapping_selection_screen_state_for_config(self, config: dict[str, Any], selection_path: Path) -> dict[str, Any]:
        all_mappings = self.mapping_service.mappings_for_config(config)
        selected = set(self.read_mapping_selection_for_config(config, selection_path, required=False))
        return {"all_mappings": all_mappings, "selected": selected}

    def store_ordered_mapping_selection(
        self,
        config: dict[str, Any],
        selection_path: Path,
        all_mappings: list[dict[str, Any]],
        selected: set[str],
        *,
        save_config: Callable[[dict[str, Any]], Any],
    ) -> list[str]:
        ordered = [mapping["name"] for mapping in all_mappings if mapping["name"] in selected]
        self.store_mapping_selection_for_config(
            config,
            selection_path,
            ordered,
            save_config=save_config,
        )
        return ordered

    def toggle_mapping_selection_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        all_mappings: list[dict[str, Any]],
        selected: set[str],
        index: int,
        *,
        save_config: Callable[[dict[str, Any]], Any],
    ) -> dict[str, Any]:
        if not all_mappings:
            return {"selected": set(selected), "status": "No mappings configured"}
        mapping = all_mappings[min(max(0, index), len(all_mappings) - 1)]
        updated = set(selected)
        name = mapping["name"]
        if name in updated:
            updated.remove(name)
            status = f"Mapping deactivated: {name}"
        else:
            updated.add(name)
            status = f"Mapping activated: {name}"
        self.store_ordered_mapping_selection(
            config,
            selection_path,
            all_mappings,
            updated,
            save_config=save_config,
        )
        return {"selected": updated, "status": status}

    def select_all_mappings_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        all_mappings: list[dict[str, Any]],
        *,
        save_config: Callable[[dict[str, Any]], Any],
    ) -> dict[str, Any]:
        selected = {mapping["name"] for mapping in all_mappings}
        self.store_ordered_mapping_selection(
            config,
            selection_path,
            all_mappings,
            selected,
            save_config=save_config,
        )
        return {"selected": selected, "status": "All mappings activated"}

    def clear_mapping_selection_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        *,
        save_config: Callable[[dict[str, Any]], Any],
    ) -> dict[str, Any]:
        self.store_mapping_selection_for_config(config, selection_path, [], save_config=save_config)
        return {"selected": set(), "status": "All mappings deactivated"}

    def delete_mapping_selection_action_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        name: str,
        *,
        save_config: Callable[[dict[str, Any]], Any],
    ) -> dict[str, Any]:
        removed = self.mapping_service.remove_mapping_from_active_project_by_name(config, name)
        if not removed:
            return {
                "ok": False,
                "all_mappings": self.mapping_service.mappings_for_config(config),
                "selected": set(self.read_mapping_selection_for_config(config, selection_path, required=False)),
                "status": f"Mapping not found: {name}",
            }
        selected = set(self.read_mapping_selection_for_config(config, selection_path, required=False))
        selected.discard(name)
        save_config(config)
        all_mappings = self.mapping_service.mappings_for_config(config)
        self.store_ordered_mapping_selection(
            config,
            selection_path,
            all_mappings,
            selected,
            save_config=save_config,
        )
        return {
            "ok": True,
            "all_mappings": all_mappings,
            "selected": selected,
            "status": f"Mapping deleted: {name}",
        }

    def mapping_selection_key_action(
        self,
        *,
        mappings_exist: bool,
        up: bool = False,
        down: bool = False,
        toggle: bool = False,
        delete: bool = False,
        all_key: bool = False,
        none_key: bool = False,
        add_key: bool = False,
        close_key: bool = False,
    ) -> dict[str, Any]:
        if up and mappings_exist:
            return {"action": "move", "delta": -1}
        if down and mappings_exist:
            return {"action": "move", "delta": 1}
        if add_key:
            return {"action": "add"}
        if toggle and mappings_exist:
            return {"action": "toggle"}
        if delete and mappings_exist:
            return {"action": "delete"}
        if all_key and mappings_exist:
            return {"action": "all"}
        if none_key and mappings_exist:
            return {"action": "none"}
        if close_key:
            return {"action": "close"}
        return {"action": "noop"}


def project_mapping_selection_service(
    *,
    mapping_service: ProjectMappingCoreService | None = None,
) -> ProjectMappingSelectionService:
    return ProjectMappingSelectionService(mapping_service=mapping_service)
