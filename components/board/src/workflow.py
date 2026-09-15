"""Board-host command workflow service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.board.src.builder import board_command_builder
from components.board.src.flash import board_flash_command_service
from components.board.src.session import board_session_command_service
from components.board.src.transfer import board_artifact_transfer_service
from components.config.api import accessors as config_accessors


class BoardCommandWorkflowService:
    """Provide board-host command use cases to other components."""

    def __init__(
        self,
        *,
        app_dir: Path,
        default_moulin_manifest: str,
        flash_bootloaders_tool: Path,
        xt_imager_tool: Path,
        remote_read_project_file: Callable[[dict[str, Any], str], str],
        manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    ) -> None:
        self.app_dir = app_dir
        self.default_moulin_manifest = default_moulin_manifest
        self.flash_bootloaders_tool = flash_bootloaders_tool
        self.xt_imager_tool = xt_imager_tool
        self.remote_read_project_file = remote_read_project_file
        self.manifest_cache = manifest_cache
        self.command_builder = board_command_builder()
        self.session_service = board_session_command_service()
        self.transfer_service = board_artifact_transfer_service(
            command_builder=self.command_builder,
            app_dir=app_dir,
            default_moulin_manifest=default_moulin_manifest,
            remote_read_project_file=remote_read_project_file,
            manifest_cache=manifest_cache,
        )
        self.flash_service = board_flash_command_service(command_builder=self.command_builder)

    def connect_command(self, config: dict[str, Any]) -> list[str]:
        return self.session_service.connect_command_for_config(config)

    def interactive_shell_command(self, config: dict[str, Any]) -> list[str]:
        return self.session_service.interactive_shell_command_for_config(config)

    def run_interactive_shell(
        self,
        config: dict[str, Any],
        runner: Callable[[list[str]], Any],
    ) -> Any:
        return self.session_service.run_interactive_shell(config, runner)

    def copy_build_artifacts_commands(
        self,
        config: dict[str, Any],
        *,
        artifact_targets: str,
        build_params: dict[str, str],
    ) -> list[list[str]]:
        return self.transfer_service.copy_build_artifacts_commands(
            config,
            artifact_targets=artifact_targets,
            build_params=build_params,
        )

    def run_copy_build_artifacts(
        self,
        config: dict[str, Any],
        *,
        artifact_targets: str,
        build_params: dict[str, str],
        runner: Callable[[str, list[list[str]]], Any],
    ) -> Any:
        return runner(
            "Copy build artifacts",
            self.copy_build_artifacts_commands(
                config,
                artifact_targets=artifact_targets,
                build_params=build_params,
            ),
        )

    def flash_bootloaders_commands(self, config: dict[str, Any]) -> list[list[str]]:
        return self.flash_service.flash_bootloaders_command_plan(
            board_host=config_accessors.board_host_spec_for_config(config),
            work_dir=config_accessors.board_work_dir_for_config(config),
            artifacts_dir=config_accessors.board_artifacts_dir_for_config(config),
            tool=self.flash_bootloaders_tool,
        )

    def run_flash_bootloaders(
        self,
        config: dict[str, Any],
        *,
        runner: Callable[[str, list[list[str]]], Any],
    ) -> Any:
        return runner("Flash bootloaders", self.flash_bootloaders_commands(config))

    def flash_ufs_image_commands(self, config: dict[str, Any]) -> list[list[str]]:
        return self.flash_service.flash_ufs_command_plan(
            board_host=config_accessors.board_host_spec_for_config(config),
            work_dir=config_accessors.board_work_dir_for_config(config),
            artifacts_dir=config_accessors.board_artifacts_dir_for_config(config),
            console=config_accessors.board_console_device_for_config(config),
            loadaddr=config_accessors.board_ufs_loadaddr_for_config(config),
            buffersize=config_accessors.board_ufs_buffersize_for_config(config),
            tool=self.xt_imager_tool,
        )

    def run_flash_ufs_image(
        self,
        config: dict[str, Any],
        *,
        runner: Callable[[str, list[list[str]]], Any],
    ) -> Any:
        return runner("Flash UFS image", self.flash_ufs_image_commands(config))


def board_command_workflow_service(
    *,
    app_dir: Path,
    default_moulin_manifest: str,
    flash_bootloaders_tool: Path,
    xt_imager_tool: Path,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
) -> BoardCommandWorkflowService:
    return BoardCommandWorkflowService(
        app_dir=app_dir,
        default_moulin_manifest=default_moulin_manifest,
        flash_bootloaders_tool=flash_bootloaders_tool,
        xt_imager_tool=xt_imager_tool,
        remote_read_project_file=remote_read_project_file,
        manifest_cache=manifest_cache,
    )
