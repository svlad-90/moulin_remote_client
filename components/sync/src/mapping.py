"""Mapped-file sync command service."""

from __future__ import annotations

import shlex
from pathlib import Path, PurePosixPath
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
            remote_dir = self.remote_mapping_directory(mapping, remote_base=remote_base)
            argv.extend(["--rsync-path", f"mkdir -p {shlex.quote(remote_dir)} && rsync"])
            argv.extend([str(local_path) + source_suffix, remote_path + target_suffix])
        else:
            raise ValueError(direction)
        return argv

    def local_log_command(self, *lines: str, exit_code: int = 0) -> list[str]:
        return self.script_service.local_log_command(*lines, exit_code=exit_code)

    def remote_mapping_directory(self, mapping: dict[str, Any], *, remote_base: str) -> str:
        _remote, separator, base_path = remote_base.partition(":")
        if not separator:
            raise SystemExit(f"remote project path is not an rsync remote path: {remote_base}")
        remote_path = PurePosixPath(base_path) / mapping["remote"]
        remote_dir = remote_path if mapping["kind"] == "directory" else remote_path.parent
        return str(remote_dir)

    def remote_project_directory(self, *, remote_base: str) -> str:
        _remote, separator, base_path = remote_base.partition(":")
        if not separator:
            raise SystemExit(f"remote project path is not an rsync remote path: {remote_base}")
        return str(PurePosixPath(base_path))

    def relative_local_mapping_path(self, mapping: dict[str, Any], *, local_base: Path) -> str:
        return f"{local_base}/./{mapping['local']}"

    def rsync_mappings_push_command(
        self,
        mappings: list[dict[str, Any]],
        *,
        dry_run: bool,
        excludes: list[str],
        local_base: Path,
        remote_base: str,
    ) -> list[str]:
        if not mappings:
            raise SystemExit("no mappings selected")
        missing: list[str] = []
        disabled: list[str] = []
        for mapping in mappings:
            if not mapping["push"]:
                disabled.append(mapping["name"])
            if not (local_base / mapping["local"]).exists():
                missing.append(str(local_base / mapping["local"]))
        if disabled:
            raise SystemExit("push disabled for mappings:\n" + "\n".join(disabled))
        if missing:
            raise SystemExit("local mapping paths do not exist:\n" + "\n".join(missing))
        argv = transport.rsync_base_command(dry_run=dry_run, relative=True)
        argv.extend(excludes)
        remote_project_dir = self.remote_project_directory(remote_base=remote_base)
        argv.extend(["--rsync-path", f"mkdir -p {shlex.quote(remote_project_dir)} && rsync"])
        argv.extend(self.relative_local_mapping_path(mapping, local_base=local_base) for mapping in mappings)
        argv.append(remote_base + "/")
        return argv

    def remote_mapping_directory_prepare_command(
        self,
        mapping: dict[str, Any],
        *,
        remote_base: str,
    ) -> list[str]:
        remote, separator, base_path = remote_base.partition(":")
        if not separator:
            raise SystemExit(f"remote project path is not an rsync remote path: {remote_base}")
        remote_dir = self.remote_mapping_directory(mapping, remote_base=remote_base)
        return transport.ssh_command(remote, f"mkdir -p {shlex.quote(remote_dir)}")

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

    def rsync_mappings_push_command_for_config(
        self,
        config: dict[str, Any],
        mappings: list[dict[str, Any]],
        *,
        dry_run: bool,
        app_dir: Path,
        excludes: list[str],
        remote_base: str,
    ) -> list[str]:
        return self.rsync_mappings_push_command(
            mappings,
            dry_run=dry_run,
            excludes=excludes,
            local_base=config_accessors.local_project_dir_for_config(config, app_dir),
            remote_base=remote_base,
        )

    def remote_mapping_directory_prepare_command_for_config(
        self,
        config: dict[str, Any],
        mapping: dict[str, Any],
        *,
        app_dir: Path,
        remote_base: str,
    ) -> list[str]:
        return self.remote_mapping_directory_prepare_command(
            mapping,
            remote_base=remote_base,
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
