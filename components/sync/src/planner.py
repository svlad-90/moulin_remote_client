"""Sync command plan service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.process.api import script as process_script_api
from components.project.api import overlay as project_overlay_api
from components.sync.src.cli import SyncCliService, sync_cli_service
from components.sync.src.mapping import SyncMappingCommandService, sync_mapping_command_service
from components.sync.src.pre_build import SyncPreBuildService, sync_pre_build_service
from components.sync.src.selected_paths import SyncSelectedPathService, sync_selected_path_service


class SyncCommandPlanner:
    """Build concrete rsync and pre-build command plans."""

    def __init__(
        self,
        *,
        overlay_validation_service: project_overlay_api.ProjectOverlayValidationService | None = None,
        mapping_service: SyncMappingCommandService | None = None,
        selected_path_service: SyncSelectedPathService | None = None,
        pre_build_service: SyncPreBuildService | None = None,
        cli_service: SyncCliService | None = None,
        script_service: process_script_api.ProcessScriptService | None = None,
    ) -> None:
        self.overlay_validation_service = overlay_validation_service or project_overlay_api.project_overlay_validation_service()
        self.script_service = script_service or process_script_api.process_script_service()
        self.mapping_service = mapping_service or sync_mapping_command_service()
        self.selected_path_service = selected_path_service or sync_selected_path_service()
        self.pre_build_service = pre_build_service or sync_pre_build_service(
            overlay_validation_service=self.overlay_validation_service,
            mapping_service=self.mapping_service,
            selected_path_service=self.selected_path_service,
            script_service=self.script_service,
        )
        self.cli_service = cli_service or sync_cli_service(
            mapping_service=self.mapping_service,
            selected_path_service=self.selected_path_service,
        )

    def rsync_excludes_for_config(self, config: dict[str, Any]) -> list[str]:
        return self.selected_path_service.rsync_excludes_for_config(config)

    def remote_base_for_config(self, config: dict[str, Any]) -> str:
        return self.selected_path_service.remote_base_for_config(config)

    def build_rsync_path_args(self, paths: list[str], base: str) -> list[str]:
        return self.selected_path_service.build_rsync_path_args(paths, base)

    def selected_paths_pull_command_for_config(
        self,
        config: dict[str, Any],
        paths: list[str],
        *,
        dry_run: bool,
        app_dir: Path,
    ) -> list[str]:
        return self.selected_path_service.selected_paths_pull_command_for_config(
            config,
            paths,
            dry_run=dry_run,
            app_dir=app_dir,
        )

    def selected_paths_push_command_for_config(
        self,
        config: dict[str, Any],
        paths: list[str],
        *,
        dry_run: bool,
        app_dir: Path,
    ) -> list[str]:
        return self.selected_path_service.selected_paths_push_command_for_config(
            config,
            paths,
            dry_run=dry_run,
            app_dir=app_dir,
        )

    def run_selected_paths_pull_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        *,
        dry_run: bool,
        app_dir: Path,
        runner: Callable[[list[str]], Any],
    ) -> None:
        self.selected_path_service.run_selected_paths_pull_for_config(
            config,
            selection_path,
            dry_run=dry_run,
            app_dir=app_dir,
            runner=runner,
        )

    def run_selected_paths_push_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        *,
        dry_run: bool,
        app_dir: Path,
        runner: Callable[[list[str]], Any],
    ) -> None:
        self.selected_path_service.run_selected_paths_push_for_config(
            config,
            selection_path,
            dry_run=dry_run,
            app_dir=app_dir,
            runner=runner,
        )

    def build_local_log_command(self, *lines: str, exit_code: int = 0) -> list[str]:
        return self.script_service.local_log_command(*lines, exit_code=exit_code)

    def rsync_mapping_command(
        self,
        mapping: dict[str, Any],
        *,
        direction: str,
        dry_run: bool,
        excludes: list[str],
        local_base: Path,
        remote_base: str,
        prepare: bool = True,
    ) -> list[str]:
        return self.mapping_service.rsync_mapping_command(
            mapping,
            direction=direction,
            dry_run=dry_run,
            excludes=excludes,
            local_base=local_base,
            remote_base=remote_base,
            prepare=prepare,
        )

    def rsync_mapping_command_for_config(
        self,
        config: dict[str, Any],
        mapping: dict[str, Any],
        *,
        direction: str,
        dry_run: bool,
        app_dir: Path,
        prepare: bool = True,
    ) -> list[str]:
        return self.mapping_service.rsync_mapping_command_for_config(
            config,
            mapping,
            direction=direction,
            dry_run=dry_run,
            app_dir=app_dir,
            excludes=self.rsync_excludes_for_config(config),
            remote_base=self.remote_base_for_config(config),
            prepare=prepare,
        )

    def mapping_sync_header(self, mapping: dict[str, Any], *, direction: str) -> list[str]:
        return self.mapping_service.mapping_sync_header(mapping, direction=direction)

    def mapping_sync_plan_for_config(
        self,
        config: dict[str, Any],
        names: list[str],
        *,
        direction: str,
        dry_run: bool,
        app_dir: Path,
    ) -> list[dict[str, Any]]:
        return self.mapping_service.mapping_sync_plan_for_config(
            config,
            names,
            direction=direction,
            dry_run=dry_run,
            app_dir=app_dir,
            excludes=self.rsync_excludes_for_config(config),
            remote_base=self.remote_base_for_config(config),
        )

    def run_command_plan(
        self,
        plan: list[dict[str, Any]],
        *,
        runner: Callable[[list[str]], Any],
        write_line: Callable[[str], Any],
    ) -> None:
        self.cli_service.run_command_plan(plan, runner=runner, write_line=write_line)

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
        self.cli_service.run_mapping_sync_plan_for_config(
            config,
            names,
            direction=direction,
            dry_run=dry_run,
            app_dir=app_dir,
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
        self.cli_service.run_selected_mapping_sync_plan_for_config(
            config,
            selection_path,
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
        self.cli_service.run_cli_sync_command_for_config(
            config,
            command,
            names,
            app_dir=app_dir,
            runner=runner,
            write_line=write_line,
        )

    def rsync_mapping_commands(
        self,
        mappings: list[dict[str, Any]],
        *,
        direction: str,
        dry_run: bool,
        excludes: list[str],
        local_base: Path,
        remote_base: str,
        prepare: bool = True,
    ) -> list[list[str]]:
        return self.mapping_service.rsync_mapping_commands(
            mappings,
            direction=direction,
            dry_run=dry_run,
            excludes=excludes,
            local_base=local_base,
            remote_base=remote_base,
            prepare=prepare,
        )

    def selected_mapping_commands_for_config(
        self,
        config: dict[str, Any],
        *,
        selection_path: Path,
        direction: str,
        dry_run: bool,
        app_dir: Path,
        prepare: bool = True,
    ) -> list[list[str]]:
        return self.mapping_service.selected_mapping_commands_for_config(
            config,
            selection_path=selection_path,
            direction=direction,
            dry_run=dry_run,
            app_dir=app_dir,
            excludes=self.rsync_excludes_for_config(config),
            remote_base=self.remote_base_for_config(config),
            prepare=prepare,
        )

    def all_mapping_commands_for_config(
        self,
        config: dict[str, Any],
        *,
        direction: str,
        dry_run: bool,
        app_dir: Path,
        prepare: bool = True,
    ) -> list[list[str]]:
        return self.mapping_service.all_mapping_commands_for_config(
            config,
            direction=direction,
            dry_run=dry_run,
            app_dir=app_dir,
            excludes=self.rsync_excludes_for_config(config),
            remote_base=self.remote_base_for_config(config),
            prepare=prepare,
        )

    def pre_build_sync_commands(
        self,
        names: list[str],
        active_mappings: list[dict[str, Any]],
        issues: list[str],
        *,
        rsync_command: Callable[[dict[str, Any]], list[str]],
    ) -> list[list[str]]:
        return self.pre_build_service.pre_build_sync_commands(
            names,
            active_mappings,
            issues,
            rsync_command=rsync_command,
        )

    def pre_build_sync_commands_for_config(
        self,
        config: dict[str, Any],
        *,
        selection_path: Path,
        app_dir: Path,
    ) -> list[list[str]]:
        return self.pre_build_service.pre_build_sync_commands_for_config(
            config,
            selection_path=selection_path,
            app_dir=app_dir,
        )

    def command_sequence_for_config(
        self,
        config: dict[str, Any],
        build_command: list[str],
        *,
        parameters: dict[str, Any],
        targets: str,
        docker_image: str,
        selection_path: Path,
        app_dir: Path,
        default_config_path: Path,
    ) -> list[list[str]]:
        return self.pre_build_service.command_sequence_for_config(
            config,
            build_command,
            parameters=parameters,
            targets=targets,
            docker_image=docker_image,
            selection_path=selection_path,
            app_dir=app_dir,
            default_config_path=default_config_path,
        )

    def pre_build_selection_error_command(self, error: BaseException) -> list[list[str]]:
        return self.pre_build_service.pre_build_selection_error_command(error)


def sync_command_planner() -> SyncCommandPlanner:
    return SyncCommandPlanner()
