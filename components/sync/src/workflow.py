"""Sync workflow controller."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.config.api import accessors as config_accessors
from components.remote.api import discovery as remote_discovery_api
from components.sync.api import actions as sync_actions_api
from components.sync.api import cli as sync_cli_api
from components.sync.api import pre_build as sync_pre_build_api
from components.sync.api import screen as sync_screen_api


class SyncWorkflowController:
    """Run the mapped-file sync screen with its action dependencies."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        app_dir: Path,
        fetch_project_listing: Callable[[str], list[dict[str, str]]],
        save_config: Callable[[dict[str, Any]], Any],
        run_commands: Callable[[Any, str, list[list[str]]], Any],
    ) -> None:
        self.config = config
        self.app_dir = app_dir
        self.fetch_project_listing = fetch_project_listing
        self.save_config = save_config
        self.run_commands = run_commands

    def run_sync_screen(self, port: Any) -> None:
        sync_screen_api.run_sync_screen(
            port,
            self.config,
            self.app_dir,
            connected=lambda: port.connection_state == "connected",
            action_controller=sync_actions_api.sync_action_controller(
                self.config,
                app_dir=self.app_dir,
                fetch_project_listing=self.fetch_project_listing,
                save_config=self.save_config,
                run_commands=lambda title, commands: self.run_commands(port, title, commands),
            ),
        )


class SyncCommandWorkflowService:
    """Provide sync-aware command sequencing use cases."""

    def __init__(
        self,
        *,
        app_dir: Path,
        default_config_path: Path,
        pre_build_service: sync_pre_build_api.SyncPreBuildService | None = None,
        cli_service: sync_cli_api.SyncCliService | None = None,
    ) -> None:
        self.app_dir = app_dir
        self.default_config_path = default_config_path
        self.pre_build_service = pre_build_service or sync_pre_build_api.sync_pre_build_service()
        self.cli_service = cli_service or sync_cli_api.sync_cli_service()

    def supports_cli_command(self, command: str) -> bool:
        return self.cli_service.supports_command(command)

    def mapping_selection_path(self, config: dict[str, Any]) -> Path:
        return config_accessors.mapping_selection_path_for_config(config, self.app_dir)

    def build_command_sequence(
        self,
        config: dict[str, Any],
        build_command: list[str],
        *,
        parameters: dict[str, str],
        targets: str,
        docker_image: str,
    ) -> list[list[str]]:
        return self.pre_build_service.command_sequence_for_config(
            config,
            build_command,
            parameters=parameters,
            targets=targets,
            docker_image=docker_image,
            selection_path=config_accessors.mapping_selection_path_for_config(config, self.app_dir),
            app_dir=self.app_dir,
            default_config_path=self.default_config_path,
        )

    def mapped_files_push_sequence(self, config: dict[str, Any]) -> list[list[str]]:
        return self.pre_build_service.pre_build_sync_commands_for_config(
            config,
            selection_path=config_accessors.mapping_selection_path_for_config(config, self.app_dir),
            app_dir=self.app_dir,
        )

    def run_cli_command(
        self,
        config: dict[str, Any],
        command: str,
        names: list[str],
        *,
        runner: Callable[[list[str]], Any],
        write_line: Callable[[str], Any],
    ) -> None:
        self.cli_service.run_cli_sync_command_for_config(
            config,
            command,
            names,
            app_dir=self.app_dir,
            runner=runner,
            write_line=write_line,
        )


def sync_workflow_controller(
    config: dict[str, Any],
    *,
    app_dir: Path,
    save_config: Callable[[dict[str, Any]], Any],
    capture_command: Callable[..., Any],
    run_commands: Callable[[Any, str, list[list[str]]], Any],
) -> SyncWorkflowController:
    remote_discovery = remote_discovery_api.remote_project_discovery_service()
    return SyncWorkflowController(
        config,
        app_dir=app_dir,
        fetch_project_listing=lambda current_dir: remote_discovery.fetch_project_listing_for_config(
            config,
            current_dir,
            lambda argv: capture_command(argv, echo=False, timeout=30),
        ),
        save_config=save_config,
        run_commands=run_commands,
    )


def sync_command_workflow_service(
    *,
    app_dir: Path,
    default_config_path: Path,
    pre_build_service: sync_pre_build_api.SyncPreBuildService | None = None,
    cli_service: sync_cli_api.SyncCliService | None = None,
) -> SyncCommandWorkflowService:
    return SyncCommandWorkflowService(
        app_dir=app_dir,
        default_config_path=default_config_path,
        pre_build_service=pre_build_service,
        cli_service=cli_service,
    )
