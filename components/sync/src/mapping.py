"""Mapped-file sync command service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from components.config.api import accessors as config_accessors
from components.process.api import script as process_script_api
from components.project.api import selection as project_selection_api
from components.remote.api import transport


class SyncMappingCommandService:
    """Own rsync command plans for configured project mappings."""

    def __init__(
        self,
        *,
        selection_service: project_selection_api.ProjectMappingSelectionService | None = None,
        script_service: process_script_api.ProcessScriptService | None = None,
    ) -> None:
        self.selection_service = selection_service or project_selection_api.project_mapping_selection_service()
        self.script_service = script_service or process_script_api.process_script_service()

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
        local_path = local_base / mapping["local"]
        remote_path = f"{remote_base}/{mapping['remote']}"
        argv = transport.rsync_base_command(dry_run=dry_run)
        argv.extend(excludes)
        source_suffix = "/" if mapping["kind"] == "directory" else ""
        target_suffix = "/" if mapping["kind"] == "directory" else ""
        if direction == "pull":
            if prepare:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                if mapping["kind"] == "directory":
                    local_path.mkdir(parents=True, exist_ok=True)
            argv.extend([remote_path + source_suffix, str(local_path) + target_suffix])
        elif direction == "push":
            if not mapping["push"]:
                if dry_run:
                    return self.local_log_command(
                        f"SKIP push dry-run: {mapping['name']}",
                        "reason: mapping is marked push=false",
                        f"local:  {local_path}",
                        f"remote: {mapping['remote']}",
                    )
                raise SystemExit(f"mapping {mapping['name']} is marked push=false")
            if not local_path.exists():
                if dry_run:
                    return self.local_log_command(
                        f"SKIP push dry-run: {mapping['name']}",
                        "reason: local mapping path does not exist",
                        f"local:  {local_path}",
                        f"remote: {mapping['remote']}",
                    )
                raise SystemExit(f"local mapping path does not exist: {local_path}")
            argv.extend([str(local_path) + source_suffix, remote_path + target_suffix])
        else:
            raise ValueError(direction)
        return argv

    def local_log_command(self, *lines: str, exit_code: int = 0) -> list[str]:
        return self.script_service.local_log_command(*lines, exit_code=exit_code)

    def rsync_mapping_command_for_config(
        self,
        config: dict[str, Any],
        mapping: dict[str, Any],
        *,
        direction: str,
        dry_run: bool,
        app_dir: Path,
        excludes: list[str],
        remote_base: str,
        prepare: bool = True,
    ) -> list[str]:
        return self.rsync_mapping_command(
            mapping,
            direction=direction,
            dry_run=dry_run,
            excludes=excludes,
            local_base=config_accessors.local_project_dir_for_config(config, app_dir),
            remote_base=remote_base,
            prepare=prepare,
        )

    def mapping_sync_header(self, mapping: dict[str, Any], *, direction: str) -> list[str]:
        return [
            f"\n== {direction}: {mapping['name']} ==",
            f"role: {mapping['role']}",
            f"remote: {mapping['remote']}",
            f"local:  {mapping['local']}",
        ]

    def mapping_sync_plan_for_config(
        self,
        config: dict[str, Any],
        names: list[str],
        *,
        direction: str,
        dry_run: bool,
        app_dir: Path,
        excludes: list[str],
        remote_base: str,
    ) -> list[dict[str, Any]]:
        return [
            {
                "header": self.mapping_sync_header(mapping, direction=direction),
                "argv": self.rsync_mapping_command_for_config(
                    config,
                    mapping,
                    direction=direction,
                    dry_run=dry_run,
                    app_dir=app_dir,
                    excludes=excludes,
                    remote_base=remote_base,
                ),
            }
            for mapping in self.selection_service.select_mappings_for_config(config, names)
        ]

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
        return [
            self.rsync_mapping_command(
                mapping,
                direction=direction,
                dry_run=dry_run,
                excludes=excludes,
                local_base=local_base,
                remote_base=remote_base,
                prepare=prepare,
            )
            for mapping in mappings
        ]

    def selected_mapping_commands_for_config(
        self,
        config: dict[str, Any],
        *,
        selection_path: Path,
        direction: str,
        dry_run: bool,
        app_dir: Path,
        excludes: list[str],
        remote_base: str,
        prepare: bool = True,
    ) -> list[list[str]]:
        names = self.selection_service.read_mapping_selection_for_config(config, selection_path, required=True)
        return self.rsync_mapping_commands(
            self.selection_service.select_mappings_for_config(config, names),
            direction=direction,
            dry_run=dry_run,
            excludes=excludes,
            local_base=config_accessors.local_project_dir_for_config(config, app_dir),
            remote_base=remote_base,
            prepare=prepare,
        )

    def all_mapping_commands_for_config(
        self,
        config: dict[str, Any],
        *,
        direction: str,
        dry_run: bool,
        app_dir: Path,
        excludes: list[str],
        remote_base: str,
        prepare: bool = True,
    ) -> list[list[str]]:
        return self.rsync_mapping_commands(
            self.selection_service.select_mappings_for_config(config, ["all"]),
            direction=direction,
            dry_run=dry_run,
            excludes=excludes,
            local_base=config_accessors.local_project_dir_for_config(config, app_dir),
            remote_base=remote_base,
            prepare=prepare,
        )


def sync_mapping_command_service(
    *,
    selection_service: project_selection_api.ProjectMappingSelectionService | None = None,
    script_service: process_script_api.ProcessScriptService | None = None,
) -> SyncMappingCommandService:
    return SyncMappingCommandService(selection_service=selection_service, script_service=script_service)
