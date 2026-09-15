"""Sync CLI dispatch service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.config.api import accessors as config_accessors
from components.project.api import selection as project_selection_api
from components.sync.src.mapping import SyncMappingCommandService, sync_mapping_command_service
from components.sync.src.selected_paths import SyncSelectedPathService, sync_selected_path_service


SYNC_CLI_COMMANDS = {
    "pull",
    "pull-dry-run",
    "push",
    "push-dry-run",
    "pull-map",
    "pull-map-dry-run",
    "push-map",
    "push-map-dry-run",
    "pull-selected-map",
    "pull-selected-map-dry-run",
    "push-selected-map",
    "push-selected-map-dry-run",
}


class SyncCliService:
    """Own dispatch from sync CLI verbs to concrete sync use cases."""

    def __init__(
        self,
        *,
        mapping_service: SyncMappingCommandService | None = None,
        selected_path_service: SyncSelectedPathService | None = None,
        selection_service: project_selection_api.ProjectMappingSelectionService | None = None,
    ) -> None:
        self.mapping_service = mapping_service or sync_mapping_command_service()
        self.selected_path_service = selected_path_service or sync_selected_path_service()
        self.selection_service = selection_service or project_selection_api.project_mapping_selection_service()

    def supports_command(self, command: str) -> bool:
        return command in SYNC_CLI_COMMANDS

    def run_command_plan(
        self,
        plan: list[dict[str, Any]],
        *,
        runner: Callable[[list[str]], Any],
        write_line: Callable[[str], Any],
    ) -> None:
        for step in plan:
            for line in step["header"]:
                write_line(line)
            runner(step["argv"])

    def run_mapping_sync_plan_for_config(
        self,
        config: dict[str, Any],
        names: list[str],
        *,
        direction: str,
        dry_run: bool,
        app_dir: Path,
        runner: Callable[[list[str]], Any],
        write_line: Callable[[str], Any],
    ) -> None:
        self.run_command_plan(
            self.mapping_service.mapping_sync_plan_for_config(
                config,
                names,
                direction=direction,
                dry_run=dry_run,
                app_dir=app_dir,
                excludes=self.selected_path_service.rsync_excludes_for_config(config),
                remote_base=self.selected_path_service.remote_base_for_config(config),
            ),
            runner=runner,
            write_line=write_line,
        )

    def run_selected_mapping_sync_plan_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        *,
        direction: str,
        dry_run: bool,
        app_dir: Path,
        runner: Callable[[list[str]], Any],
        write_line: Callable[[str], Any],
    ) -> None:
        self.run_mapping_sync_plan_for_config(
            config,
            self.selection_service.read_mapping_selection_for_config(config, selection_path, required=True),
            direction=direction,
            dry_run=dry_run,
            app_dir=app_dir,
            runner=runner,
            write_line=write_line,
        )

    def run_cli_sync_command_for_config(
        self,
        config: dict[str, Any],
        command: str,
        names: list[str],
        *,
        app_dir: Path,
        runner: Callable[[list[str]], Any],
        write_line: Callable[[str], Any],
    ) -> None:
        if command in {"pull", "pull-dry-run"}:
            self.selected_path_service.run_selected_paths_pull_for_config(
                config,
                config_accessors.inventory_selection_path_for_config(config, app_dir),
                dry_run=command.endswith("-dry-run"),
                app_dir=app_dir,
                runner=runner,
            )
            return
        if command in {"push", "push-dry-run"}:
            self.selected_path_service.run_selected_paths_push_for_config(
                config,
                config_accessors.inventory_selection_path_for_config(config, app_dir),
                dry_run=command.endswith("-dry-run"),
                app_dir=app_dir,
                runner=runner,
            )
            return
        if command in {"pull-map", "pull-map-dry-run", "push-map", "push-map-dry-run"}:
            self.run_mapping_sync_plan_for_config(
                config,
                names,
                direction="push" if command.startswith("push") else "pull",
                dry_run=command.endswith("-dry-run"),
                app_dir=app_dir,
                runner=runner,
                write_line=write_line,
            )
            return
        if command in {"pull-selected-map", "pull-selected-map-dry-run", "push-selected-map", "push-selected-map-dry-run"}:
            self.run_selected_mapping_sync_plan_for_config(
                config,
                config_accessors.mapping_selection_path_for_config(config, app_dir),
                direction="push" if command.startswith("push") else "pull",
                dry_run=command.endswith("-dry-run"),
                app_dir=app_dir,
                runner=runner,
                write_line=write_line,
            )
            return
        raise ValueError(f"unsupported sync command: {command}")


def sync_cli_service(
    *,
    mapping_service: SyncMappingCommandService | None = None,
    selected_path_service: SyncSelectedPathService | None = None,
    selection_service: project_selection_api.ProjectMappingSelectionService | None = None,
) -> SyncCliService:
    return SyncCliService(
        mapping_service=mapping_service,
        selected_path_service=selected_path_service,
        selection_service=selection_service,
    )
