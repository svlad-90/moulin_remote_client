"""Project local overlay validation service."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class ProjectOverlayValidationService:
    """Own validation of local overlay paths for active mappings."""

    def local_mapping_issue(self, local_base: Path, mapping: dict[str, Any]) -> str | None:
        path = local_base / mapping["local"]
        if not path.exists():
            return f"{mapping['name']}: local path missing: {path}"
        kind = str(mapping.get("kind", "directory"))
        if kind == "directory":
            if not path.is_dir():
                return f"{mapping['name']}: local path is not a directory: {path}"
            try:
                has_entries = any(path.iterdir())
            except OSError as exc:
                return f"{mapping['name']}: cannot inspect local directory: {exc}"
            if not has_entries:
                return f"{mapping['name']}: local directory is empty: {path}"
            return None
        if kind == "file" and not path.is_file():
            return f"{mapping['name']}: local path is not a file: {path}"
        return None

    def local_mapping_issues(self, local_base: Path, active_mappings: list[dict[str, Any]]) -> list[str]:
        return [
            issue
            for mapping in active_mappings
            for issue in [self.local_mapping_issue(local_base, mapping)]
            if issue is not None
        ]


def project_overlay_validation_service() -> ProjectOverlayValidationService:
    return ProjectOverlayValidationService()
