"""Sync screen action controller."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.project_mapping_ui.api import screen as project_mapping_screen_api


class SyncActionController:
    """Execute sync screen action results through project and command services."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        app_dir: Path,
        fetch_project_listing: Callable[[str], list[dict[str, str]]],
        save_config: Callable[[dict[str, Any]], Any],
        run_commands: Callable[[str, list[list[str]]], Any],
    ) -> None:
        self.config = config
        self.app_dir = app_dir
        self.fetch_project_listing = fetch_project_listing
        self.save_config = save_config
        self.run_commands = run_commands

    def run_action_result(self, port: Any, result: dict[str, Any]) -> None:
        kind = result["kind"]
        if kind == "select-mappings":
            self.add_mapping_screen(port)
        elif kind == "activate-mappings":
            self.select_mappings_screen(port)
        elif kind == "run-commands":
            self.run_commands(str(result["title"]), result["commands"])
        else:
            raise ValueError(f"unsupported sync action result: {kind}")

    def add_mapping_screen(self, port: Any) -> None:
        project_mapping_screen_api.run_add_mapping_screen(
            port,
            self.config,
            self.app_dir,
            fetch_project_listing=self.fetch_project_listing,
            save_config=self.save_config,
        )

    def select_mappings_screen(self, port: Any) -> None:
        project_mapping_screen_api.run_select_mappings_screen(
            port,
            self.config,
            self.app_dir,
            save_config=self.save_config,
            add_mapping_screen=lambda: self.add_mapping_screen(port),
        )


def sync_action_controller(
    config: dict[str, Any],
    *,
    app_dir: Path,
    fetch_project_listing: Callable[[str], list[dict[str, str]]],
    save_config: Callable[[dict[str, Any]], Any],
    run_commands: Callable[[str, list[list[str]]], Any],
) -> SyncActionController:
    return SyncActionController(
        config,
        app_dir=app_dir,
        fetch_project_listing=fetch_project_listing,
        save_config=save_config,
        run_commands=run_commands,
    )
