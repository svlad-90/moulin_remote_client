"""Main menu item builder."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.board.api import workflow as board_workflow_api
from components.main_menu.src.commands import main_menu_command_items_service
from components.main_menu.src.setup import main_menu_setup_items_service
from components.remote.api import workflow as remote_workflow_api
from components.sync.api import workflow as sync_workflow_api
from components.ui.api.menu import MenuItem


class MainMenuBuilder:
    """Build the main TUI menu for the current application state."""

    def __init__(
        self,
        *,
        app_dir: Path,
        default_config_path: Path,
        default_dockerfile: str,
        default_moulin_manifest: str,
        flash_bootloaders_tool: Path,
        xt_imager_tool: Path,
        remote_read_project_file: Callable[..., Any],
        manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    ) -> None:
        self.app_dir = app_dir
        self.default_config_path = default_config_path
        self.default_dockerfile = default_dockerfile
        self.default_moulin_manifest = default_moulin_manifest
        self.flash_bootloaders_tool = flash_bootloaders_tool
        self.xt_imager_tool = xt_imager_tool
        self.remote_read_project_file = remote_read_project_file
        self.manifest_cache = manifest_cache
        self.remote_command_workflow = remote_workflow_api.remote_command_workflow_service(
            default_dockerfile=default_dockerfile,
            default_moulin_manifest=default_moulin_manifest,
        )
        self.sync_command_workflow = sync_workflow_api.sync_command_workflow_service(
            app_dir=app_dir,
            default_config_path=default_config_path,
        )
        self.board_command_workflow = board_workflow_api.board_command_workflow_service(
            app_dir=app_dir,
            default_moulin_manifest=default_moulin_manifest,
            flash_bootloaders_tool=flash_bootloaders_tool,
            xt_imager_tool=xt_imager_tool,
            remote_read_project_file=remote_read_project_file,
            manifest_cache=manifest_cache,
        )
        self.command_items = main_menu_command_items_service(
            remote_command_workflow=self.remote_command_workflow,
            sync_command_workflow=self.sync_command_workflow,
            board_command_workflow=self.board_command_workflow,
        )
        self.setup_items = main_menu_setup_items_service(
            remote_command_workflow=self.remote_command_workflow,
        )

    def build_items(self, app: Any) -> list[MenuItem]:
        items = self.setup_items.build_items(app)
        items.extend(self.command_items.build_items(app))
        return items


def main_menu_builder(
    *,
    app_dir: Path,
    default_config_path: Path,
    default_dockerfile: str,
    default_moulin_manifest: str,
    flash_bootloaders_tool: Path,
    xt_imager_tool: Path,
    remote_read_project_file: Callable[..., Any],
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
) -> MainMenuBuilder:
    return MainMenuBuilder(
        app_dir=app_dir,
        default_config_path=default_config_path,
        default_dockerfile=default_dockerfile,
        default_moulin_manifest=default_moulin_manifest,
        flash_bootloaders_tool=flash_bootloaders_tool,
        xt_imager_tool=xt_imager_tool,
        remote_read_project_file=remote_read_project_file,
        manifest_cache=manifest_cache,
    )
