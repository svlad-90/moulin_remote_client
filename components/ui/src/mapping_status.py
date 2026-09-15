"""Mapping status helpers for UI display."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from components.project.api import overlay as project_overlay_api
from components.ui.src import status_segments


def local_mapping_issue(local_base: Path, mapping: dict[str, Any]) -> str | None:
    return project_overlay_api.project_overlay_validation_service().local_mapping_issue(local_base, mapping)


def local_mapping_issues(local_base: Path, active_mappings: list[dict[str, Any]]) -> list[str]:
    return project_overlay_api.project_overlay_validation_service().local_mapping_issues(local_base, active_mappings)


def mapping_status_text(
    names: list[str],
    active_mappings: list[dict[str, Any]],
    error: str | None,
    issues: list[str],
) -> str:
    if not names:
        return "0 active | pre-build push no"
    if error is not None:
        return f"{len(names)} selected | invalid selection"
    if issues:
        return f"{len(active_mappings)} active | needs pull before build"
    return f"{len(active_mappings)} active | pre-build push yes"


def mapping_status_snapshot(
    names: list[str],
    active_mappings: list[dict[str, Any]],
    error: str | None,
    *,
    local_base: Path,
) -> dict[str, str]:
    issues = local_mapping_issues(local_base, active_mappings) if error is None else []
    return {
        "text": mapping_status_text(names, active_mappings, error, issues),
        "role": status_segments.mapping_status_role(names, error, issues),
    }
