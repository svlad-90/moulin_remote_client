"""Pre-build sync command sequencing service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.config.api import accessors as config_accessors
from components.build_runtime.api import runtime as config_runtime
from components.process.api import script as process_script_api
from components.project.api import overlay as project_overlay_api
from components.project.api import selection as project_selection_api
from components.sync.src.mapping import SyncMappingCommandService, sync_mapping_command_service
from components.sync.src.selected_paths import SyncSelectedPathService, sync_selected_path_service


class SyncPreBuildService:
    """Own automatic mapping push and build command sequencing."""

    def __init__(
        self,
        *,
        overlay_validation_service: project_overlay_api.ProjectOverlayValidationService | None = None,
        mapping_service: SyncMappingCommandService | None = None,
        selected_path_service: SyncSelectedPathService | None = None,
        selection_service: project_selection_api.ProjectMappingSelectionService | None = None,
        script_service: process_script_api.ProcessScriptService | None = None,
    ) -> None:
        self.overlay_validation_service = overlay_validation_service or project_overlay_api.project_overlay_validation_service()
        self.mapping_service = mapping_service or sync_mapping_command_service()
        self.selected_path_service = selected_path_service or sync_selected_path_service()
        self.selection_service = selection_service or project_selection_api.project_mapping_selection_service()
        self.script_service = script_service or process_script_api.process_script_service()

    def local_log_command(self, *lines: str, exit_code: int = 0) -> list[str]:
        return self.script_service.local_log_command(*lines, exit_code=exit_code)

    def pre_build_sync_commands(
        self,
        names: list[str],
        active_mappings: list[dict[str, Any]],
        issues: list[str],
        *,
        rsync_command: Callable[[dict[str, Any]], list[str]],
    ) -> list[list[str]]:
        if not names:
            return []
        if issues:
            return [
                self.local_log_command(
                    "Pre-build sync skipped: local overlay is not ready",
                    "Run Sync mapped files -> Pull selected apply first.",
                    *issues[:8],
                    exit_code=1,
                )
            ]
        commands = [
            self.local_log_command(
                "Pre-build sync: pushing active mappings to remote",
                f"mappings: {', '.join(names)}",
            )
        ]
        for mapping in active_mappings:
            try:
                commands.append(rsync_command(mapping))
            except SystemExit as exc:
                commands.append(
                    self.local_log_command(
                        f"Pre-build sync failed: {mapping['name']}",
                        str(exc),
                        exit_code=1,
                    )
                )
                break
        return commands

    def pre_build_selection_error_command(self, error: BaseException) -> list[list[str]]:
        return [
            self.local_log_command(
                "Pre-build sync failed",
                str(error),
                exit_code=1,
            )
        ]

    def pre_build_sync_commands_for_config(
        self,
        config: dict[str, Any],
        *,
        selection_path: Path,
        app_dir: Path,
    ) -> list[list[str]]:
        names = self.selection_service.read_mapping_selection_for_config(config, selection_path, required=False)
        if not names:
            return []
        try:
            active_mappings = self.selection_service.select_mappings_for_config(config, names)
        except SystemExit as exc:
            return self.pre_build_selection_error_command(exc)
        local_base = config_accessors.local_project_dir_for_config(config, app_dir)
        return self.pre_build_sync_commands(
            names,
            active_mappings,
            self.overlay_validation_service.local_mapping_issues(local_base, active_mappings),
            rsync_command=lambda mapping: self.mapping_service.rsync_mapping_command_for_config(
                config,
                mapping,
                direction="push",
                dry_run=False,
                app_dir=app_dir,
                excludes=self.selected_path_service.rsync_excludes_for_config(config),
                remote_base=self.selected_path_service.remote_base_for_config(config),
            ),
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
        config_runtime.save_current_runtime_build_settings(
            config,
            parameters=parameters,
            targets=targets,
            docker_image=docker_image,
            app_dir=app_dir,
            default_path=default_config_path,
        )
        return self.pre_build_sync_commands_for_config(
            config,
            selection_path=selection_path,
            app_dir=app_dir,
        ) + [build_command]


def sync_pre_build_service(
    *,
    overlay_validation_service: project_overlay_api.ProjectOverlayValidationService | None = None,
    mapping_service: SyncMappingCommandService | None = None,
    selected_path_service: SyncSelectedPathService | None = None,
    selection_service: project_selection_api.ProjectMappingSelectionService | None = None,
    script_service: process_script_api.ProcessScriptService | None = None,
) -> SyncPreBuildService:
    return SyncPreBuildService(
        overlay_validation_service=overlay_validation_service,
        mapping_service=mapping_service,
        selected_path_service=selected_path_service,
        selection_service=selection_service,
        script_service=script_service,
    )
