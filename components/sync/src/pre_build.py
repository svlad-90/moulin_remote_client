"""Mapped-file copy and build setting sequencing service."""

from __future__ import annotations

import json
import shlex
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
    """Own mapped-file push and build command sequencing."""

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

    def mapping_copy_command(self, mapping: dict[str, Any], argv: list[str]) -> list[str]:
        script = "".join(
            f"printf '%s\\n' {shlex.quote(line)}\n"
            for line in (
                f"Copy mapped files mapping: {mapping['name']}",
                f"local:  {mapping.get('local', '-')}",
                f"remote: {mapping.get('remote', '-')}",
            )
        )
        script += 'exec "$@"\n'
        return ["bash", "-lc", script, "copy-mapping", *argv]

    def mapping_snapshot_command(self, config: dict[str, Any], mappings: list[dict[str, Any]], app_dir: Path) -> list[str]:
        config_json = json.dumps(config, sort_keys=True)
        mappings_json = json.dumps(mappings, sort_keys=True)
        script = "\n".join(
            [
                "import json",
                "import sys",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(app_dir)!r})",
                "from components.build_runtime.api import runtime",
                f"config = json.loads({config_json!r})",
                f"mappings = json.loads({mappings_json!r})",
                f"runtime.save_runtime_mapping_snapshot(config, Path({str(app_dir)!r}), mappings)",
                "print('Copy mapped files: recorded incremental build baseline')",
                "print('mappings: ' + ', '.join(str(mapping['name']) for mapping in mappings))",
            ]
        )
        return ["python3", "-c", script]

    def pre_build_sync_commands(
        self,
        names: list[str],
        active_mappings: list[dict[str, Any]],
        issues: list[str],
        *,
        rsync_command: Callable[[dict[str, Any]], list[str]],
    ) -> list[list[str]]:
        if not names:
            return [
                self.local_log_command(
                    "Copy mapped files: no active mappings selected",
                )
            ]
        if issues:
            return [
                self.local_log_command(
                    "Copy mapped files skipped: local overlay is not ready",
                    "Run Sync mapped files -> Pull selected apply first.",
                    *issues[:8],
                    exit_code=1,
                )
            ]
        commands = [
            self.local_log_command(
                "Copy mapped files: pushing active mappings to remote",
                f"mappings: {', '.join(names)}",
            )
        ]
        for mapping in active_mappings:
            try:
                commands.append(self.mapping_copy_command(mapping, rsync_command(mapping)))
            except SystemExit as exc:
                commands.append(
                    self.local_log_command(
                        f"Copy mapped files failed: {mapping['name']}",
                        str(exc),
                        exit_code=1,
                    )
                )
                break
        return commands

    def pre_build_selection_error_command(self, error: BaseException) -> list[list[str]]:
        return [
            self.local_log_command(
                "Copy mapped files failed",
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
            return self.pre_build_sync_commands([], [], [], rsync_command=lambda _mapping: [])
        try:
            active_mappings = self.selection_service.select_mappings_for_config(config, names)
        except SystemExit as exc:
            return self.pre_build_selection_error_command(exc)
        local_base = config_accessors.local_project_dir_for_config(config, app_dir)
        issues = self.overlay_validation_service.local_mapping_issues(local_base, active_mappings)
        commands = self.pre_build_sync_commands(
            names,
            active_mappings,
            issues,
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
        if names and active_mappings and not issues:
            commands.append(self.mapping_snapshot_command(config, active_mappings, app_dir))
        return commands

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
        return [build_command]


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
