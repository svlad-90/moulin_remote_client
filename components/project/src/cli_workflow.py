"""Command-line project workflow service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.config.api import accessors as config_accessors
from components.remote.api import build as remote_build
from components.remote.api import discovery as remote_discovery_api
from components.project.src.core import ProjectMappingCoreService, project_mapping_core_service
from components.project.src.inventory import ProjectInventoryService, project_inventory_service
from components.project.src.selection import ProjectMappingSelectionService, project_mapping_selection_service


PROJECT_CLI_COMMANDS = {
    "status",
    "mappings",
    "select-mappings",
    "inventory",
    "choose",
}


class ProjectCliWorkflowService:
    """Own command-line project mapping and inventory workflows."""

    def __init__(
        self,
        *,
        mapping_service: ProjectMappingCoreService | None = None,
        inventory_service: ProjectInventoryService | None = None,
        selection_service: ProjectMappingSelectionService | None = None,
        remote_discovery_service: remote_discovery_api.RemoteProjectDiscoveryService | None = None,
        remote_build_service: remote_build.RemoteBuildCommandService | None = None,
    ) -> None:
        self.mapping_service = mapping_service or project_mapping_core_service()
        self.inventory_service = inventory_service or project_inventory_service()
        self.selection_service = selection_service or project_mapping_selection_service(mapping_service=self.mapping_service)
        self.remote_discovery_service = remote_discovery_service or remote_discovery_api.remote_project_discovery_service()
        self.remote_build_service = remote_build_service or remote_build.remote_build_command_service()

    def supports_cli_command(self, command: str) -> bool:
        return command in PROJECT_CLI_COMMANDS

    def mapping_names_from_selection_input(self, raw: str, all_mappings: list[dict[str, Any]]) -> list[str] | None:
        clean = raw.strip().lower()
        if not clean:
            return None
        if clean == "all":
            return [mapping["name"] for mapping in all_mappings]
        if clean in ("none", "clear"):
            return []
        indexes = self.inventory_service.parse_ranges(clean, len(all_mappings))
        return [all_mappings[index - 1]["name"] for index in indexes]

    def format_mapping_listing_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        app_dir: Path,
    ) -> list[str]:
        selected = set(self.selection_service.read_mapping_selection_for_config(config, selection_path, required=False))
        lines = [
            f"local overlay: {config_accessors.local_project_dir_for_config(config, app_dir)}",
            f"remote project: {config_accessors.remote_spec_for_config(config)}:{config_accessors.remote_project_dir_for_config(config)}",
        ]
        for mapping in self.mapping_service.mappings_for_config(config):
            push = "push" if mapping["push"] else "pull-only"
            mark = "*" if mapping["name"] in selected else " "
            lines.extend(
                [
                    "",
                    f"{mark} {mapping['name']} [{mapping['kind']}, {push}]",
                    f"  role:   {mapping['role']}",
                    f"  remote: {mapping['remote']}",
                    f"  local:  {mapping['local']}",
                ]
            )
        return lines

    def format_mapping_selection_prompt_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        app_dir: Path,
    ) -> list[str]:
        all_mappings = self.mapping_service.mappings_for_config(config)
        selected = set(self.selection_service.read_mapping_selection_for_config(config, selection_path, required=False))
        lines = [
            f"local overlay: {config_accessors.local_project_dir_for_config(config, app_dir)}",
            f"remote project: {config_accessors.remote_spec_for_config(config)}:{config_accessors.remote_project_dir_for_config(config)}",
            "",
            "Mapping areas:",
        ]
        for index, mapping in enumerate(all_mappings, 1):
            mark = "*" if mapping["name"] in selected else " "
            lines.extend(
                [
                    f"{index:3d}. [{mark}] {mapping['name']}",
                    f"     {mapping['role']}",
                    f"     remote: {mapping['remote']}",
                    f"     local:  {mapping['local']}",
                ]
            )
        lines.extend(
            [
                "",
                "Input numbers/ranges, for example: 1 3-4",
                "Input 'all' to select all, 'none' to clear, or Enter to keep current.",
            ]
        )
        return lines

    def run_mapping_listing_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        app_dir: Path,
        *,
        write_line: Callable[[str], Any],
    ) -> None:
        write_line("\n".join(self.format_mapping_listing_for_config(config, selection_path, app_dir)))

    def run_project_status_for_config(
        self,
        config: dict[str, Any],
        app_dir: Path,
        *,
        remote_probe_command: list[str],
        local_runner: Callable[[list[str]], Any],
        remote_runner: Callable[[list[str]], Any],
        write_line: Callable[[str], Any],
    ) -> None:
        local_dir = config_accessors.local_project_dir_for_config(config, app_dir)
        write_line(f"local overlay: {local_dir}")
        write_line(
            f"remote project: {config_accessors.remote_spec_for_config(config)}:"
            f"{config_accessors.remote_project_dir_for_config(config)}"
        )
        write_line(f"mapped areas: {len(self.mapping_service.mappings_for_config(config))}")
        if local_dir.exists():
            local_runner(["du", "-sh", str(local_dir)])
        else:
            write_line("local overlay does not exist yet")
        remote_runner(remote_probe_command)

    def run_project_status(
        self,
        config: dict[str, Any],
        app_dir: Path,
        *,
        docker_image: str,
        structured_script: Callable[[list[tuple[str, str]]], str],
        local_runner: Callable[[list[str]], Any],
        remote_runner: Callable[[list[str]], Any],
        write_line: Callable[[str], Any],
    ) -> None:
        self.run_project_status_for_config(
            config,
            app_dir,
            remote_probe_command=self.remote_build_service.status_command_for_config(
                config,
                docker_image=docker_image,
                structured_script=structured_script,
            ),
            local_runner=local_runner,
            remote_runner=remote_runner,
            write_line=write_line,
        )

    def run_mapping_selection_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        app_dir: Path,
        *,
        read_input: Callable[[str], str],
        write_line: Callable[[str], Any],
        save_config: Callable[[dict[str, Any]], Any],
    ) -> None:
        all_mappings = self.mapping_service.mappings_for_config(config)
        write_line("\n".join(self.format_mapping_selection_prompt_for_config(config, selection_path, app_dir)))
        names = self.mapping_names_from_selection_input(read_input("> "), all_mappings)
        if names is None:
            write_line("mapping selection unchanged")
            return
        self.selection_service.store_mapping_selection_for_config(
            config,
            selection_path,
            names,
            save_config=save_config,
            write_line=write_line,
        )

    def run_inventory_fetch(
        self,
        output_path: Path,
        *,
        fetch_inventory_text: Callable[[], str],
        write_line: Callable[[str], Any],
    ) -> None:
        self.inventory_service.run_inventory_fetch(
            output_path,
            fetch_inventory_text=fetch_inventory_text,
            write_line=write_line,
        )

    def run_remote_inventory_fetch_for_config(
        self,
        config: dict[str, Any],
        app_dir: Path,
        *,
        capture_command: Callable[[list[str]], str],
        write_line: Callable[[str], Any],
    ) -> None:
        self.run_inventory_fetch(
            config_accessors.inventory_output_path_for_config(config, app_dir),
            fetch_inventory_text=lambda: capture_command(
                self.remote_discovery_service.build_inventory_fetch_command_for_config(config)
            ),
            write_line=write_line,
        )

    def run_inventory_choose(
        self,
        inventory_path: Path,
        selection_path: Path,
        *,
        read_input: Callable[[str], str],
        write_line: Callable[[str], Any],
    ) -> None:
        self.inventory_service.run_inventory_choose(
            inventory_path,
            selection_path,
            read_input=read_input,
            write_line=write_line,
        )

    def run_cli_project_command_for_config(
        self,
        config: dict[str, Any],
        command: str,
        *,
        app_dir: Path,
        docker_image: str,
        structured_script: Callable[[list[tuple[str, str]]], str],
        capture_command: Callable[[list[str]], str],
        local_runner: Callable[[list[str]], Any],
        remote_runner: Callable[[list[str]], Any],
        read_input: Callable[[str], str],
        write_line: Callable[[str], Any],
        save_config: Callable[[dict[str, Any]], Any],
    ) -> None:
        if command == "status":
            self.run_project_status(
                config,
                app_dir,
                docker_image=docker_image,
                structured_script=structured_script,
                local_runner=local_runner,
                remote_runner=remote_runner,
                write_line=write_line,
            )
            return
        if command == "mappings":
            self.run_mapping_listing_for_config(
                config,
                config_accessors.mapping_selection_path_for_config(config, app_dir),
                app_dir,
                write_line=write_line,
            )
            return
        if command == "select-mappings":
            self.run_mapping_selection_for_config(
                config,
                config_accessors.mapping_selection_path_for_config(config, app_dir),
                app_dir,
                read_input=read_input,
                write_line=write_line,
                save_config=save_config,
            )
            return
        if command == "inventory":
            self.run_remote_inventory_fetch_for_config(
                config,
                app_dir,
                capture_command=capture_command,
                write_line=write_line,
            )
            return
        if command == "choose":
            self.run_inventory_choose(
                config_accessors.inventory_output_path_for_config(config, app_dir),
                config_accessors.inventory_selection_path_for_config(config, app_dir),
                read_input=read_input,
                write_line=write_line,
            )
            return
        raise ValueError(f"unsupported project command: {command}")


def project_cli_workflow_service() -> ProjectCliWorkflowService:
    return ProjectCliWorkflowService()
