"""Sync screen workflow policy service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from components.config.api import accessors as config_accessors
from components.sync.src import planner as sync_planner


SYNC_SCREEN_ACTIONS = [
    {
        "kind": "select-mappings",
        "label": "Select mappings",
        "description": "Browse the remote project tree and save file or directory mappings to the client config.",
        "requires_remote": True,
        "confirm": False,
    },
    {
        "kind": "activate-mappings",
        "label": "Activate mappings",
        "description": "Choose the active subset of saved mappings for pull, push, and explicit build-host copy.",
        "requires_remote": False,
        "confirm": False,
    },
    {
        "kind": "run-selected",
        "label": "Pull selected dry-run",
        "description": "Preview copying active mapped areas from the remote project tree to the local overlay.",
        "requires_remote": True,
        "confirm": False,
        "title": "Pull selected mappings dry-run",
        "direction": "pull",
        "dry_run": True,
    },
    {
        "kind": "run-selected",
        "label": "Pull selected apply",
        "description": "Copy active mapped areas from the remote project tree to the local overlay.",
        "requires_remote": True,
        "confirm": True,
        "title": "Pull selected mappings apply",
        "direction": "pull",
        "dry_run": False,
    },
    {
        "kind": "run-selected",
        "label": "Push selected dry-run",
        "description": "Preview pushing active mapped areas from the local overlay to the remote project tree.",
        "requires_remote": True,
        "confirm": False,
        "title": "Push selected mappings dry-run",
        "direction": "push",
        "dry_run": True,
    },
    {
        "kind": "run-selected",
        "label": "Push selected apply",
        "description": "Push active mapped areas from the local overlay to the remote project tree.",
        "requires_remote": True,
        "confirm": True,
        "title": "Push selected mappings apply",
        "direction": "push",
        "dry_run": False,
    },
    {
        "kind": "back",
        "label": "Back",
        "description": "Return to the main menu.",
        "requires_remote": False,
        "confirm": False,
    },
]


class SyncScreenWorkflowService:
    """Own sync screen actions, availability, and command results."""

    def __init__(self, *, command_planner: Any | None = None) -> None:
        self.command_planner = command_planner or sync_planner.sync_command_planner()

    def actions(self) -> list[dict[str, Any]]:
        return [dict(action) for action in SYNC_SCREEN_ACTIONS]

    def action_enabled(self, action: dict[str, Any], *, connected: bool) -> bool:
        return connected or not action.get("requires_remote", False)

    def disabled_status(self, action: dict[str, Any], *, connected: bool) -> str:
        if self.action_enabled(action, connected=connected):
            return ""
        return "disabled until the build host is connected"

    def mapping_detail_rows(
        self,
        mappings: list[dict[str, Any]],
        selected_names: list[str],
        *,
        limit: int,
    ) -> list[str]:
        rows: list[str] = []
        for mapping in mappings[: max(0, limit)]:
            mark = "*" if mapping["name"] in selected_names else " "
            rows.append(f"[{mark}] {mapping['name']} -> {mapping['local']}")
        return rows

    def action_result_for_config(
        self,
        config: dict[str, Any],
        action: dict[str, Any],
        *,
        app_dir: Path,
    ) -> dict[str, Any]:
        kind = str(action["kind"])
        if kind in {"select-mappings", "activate-mappings", "back"}:
            return {"kind": kind}
        if kind == "run-selected":
            return {
                "kind": "run-commands",
                "title": action["title"],
                "commands": self.command_planner.selected_mapping_commands_for_config(
                    config,
                    selection_path=config_accessors.mapping_selection_path_for_config(config, app_dir),
                    direction=str(action["direction"]),
                    dry_run=bool(action["dry_run"]),
                    app_dir=app_dir,
                ),
            }
        raise ValueError(f"unsupported sync screen action: {kind}")


def sync_screen_workflow_service(*, command_planner: Any | None = None) -> SyncScreenWorkflowService:
    return SyncScreenWorkflowService(command_planner=command_planner)
