"""Project mapping model service."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class ProjectMappingModelService:
    """Own mapping path normalization and mapping model conversion rules."""

    def normalize_relpath(self, path: str) -> str:
        clean = path.strip()
        if not clean:
            raise ValueError("empty path")
        clean = clean.removeprefix("./").rstrip("/")
        if clean in ("", "."):
            raise ValueError("project root is not allowed as a sync path")
        parts = Path(clean).parts
        if clean.startswith("/") or ".." in parts:
            raise ValueError(f"unsafe path: {path}")
        return clean

    def normalize_mapping_path(self, path: str) -> str:
        clean = path.strip()
        if clean in ("", "."):
            return "."
        return self.normalize_relpath(clean)

    def is_descendant_mapping_path(self, path: str, parent: str) -> bool:
        clean_path = self.normalize_mapping_path(path)
        clean_parent = self.normalize_mapping_path(parent)
        if clean_path == clean_parent:
            return False
        if clean_parent == ".":
            return clean_path != "."
        return clean_path.startswith(clean_parent.rstrip("/") + "/")

    def normalize_mappings(self, raw_source: list[Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in raw_source:
            name = str(raw["name"]).strip()
            if not name:
                raise SystemExit("mapping with empty name")
            if name in seen:
                raise SystemExit(f"duplicate mapping name: {name}")
            seen.add(name)
            kind = str(raw.get("kind", "directory"))
            if kind not in ("directory", "file"):
                raise SystemExit(f"mapping {name}: unsupported kind {kind!r}")
            result.append(
                {
                    "name": name,
                    "role": str(raw.get("role", "")),
                    "remote": self.normalize_mapping_path(str(raw["remote"])),
                    "local": self.normalize_mapping_path(str(raw.get("local", raw["remote"]))),
                    "kind": kind,
                    "push": bool(raw.get("push", True)),
                }
            )
        return result

    def mappings_from_project_config(
        self,
        project: dict[str, Any],
        legacy_mappings: list[Any],
    ) -> list[dict[str, Any]]:
        raw_project_mappings = project.get("mappings")
        raw_source = raw_project_mappings if isinstance(raw_project_mappings, list) else legacy_mappings
        return self.normalize_mappings(raw_source)


def project_mapping_model_service() -> ProjectMappingModelService:
    return ProjectMappingModelService()
