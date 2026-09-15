"""Application TUI use-case controller."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.build_runtime.api import env as config_env
from components.main_menu.api import items as main_menu_items
from components.ui.api import action_execution as ui_action_execution
from components.ui.api import main_draw as ui_main_draw
from components.ui.api import main_keys as ui_main_keys
from components.ui.api import main_run_loop as ui_main_run_loop
from components.ui.api.menu import MenuItem


class AppUiController:
    """Own main TUI use cases for a session."""

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
        env: dict[str, str],
        confirm_action: Callable[[Any, Any], bool],
    ) -> None:
        self.app_dir = app_dir
        self.default_config_path = default_config_path
        self.default_dockerfile = default_dockerfile
        self.default_moulin_manifest = default_moulin_manifest
        self.flash_bootloaders_tool = flash_bootloaders_tool
        self.xt_imager_tool = xt_imager_tool
        self.remote_read_project_file = remote_read_project_file
        self.manifest_cache = manifest_cache
        self.env = env
        self.confirm_action = confirm_action

    def build_items(self, port: Any) -> list[MenuItem]:
        return main_menu_items.main_menu_builder(
            app_dir=self.app_dir,
            default_config_path=self.default_config_path,
            default_dockerfile=self.default_dockerfile,
            default_moulin_manifest=self.default_moulin_manifest,
            flash_bootloaders_tool=self.flash_bootloaders_tool,
            xt_imager_tool=self.xt_imager_tool,
            remote_read_project_file=self.remote_read_project_file,
            manifest_cache=self.manifest_cache,
        ).build_items(port)

    def run(self, port: Any) -> None:
        ui_main_run_loop.main_run_loop_controller(
            auto_connect_enabled=config_env.auto_connect_enabled(self.env),
        ).run(port)

    def handle_main_key(self, port: Any, ch: int) -> None:
        ui_main_keys.main_key_controller().handle_key(port, ch)

    def draw(self, port: Any) -> None:
        ui_main_draw.main_draw_controller(app_dir=self.app_dir).draw(port)

    def run_selected(self, port: Any) -> None:
        ui_action_execution.action_execution_controller(
            confirm_dialog=lambda content: self.confirm_action(port, content),
            show_message=port.show_message,
            refresh_after_action=port.refresh_mapping_selection_cache,
        ).run_selected(port)


def app_ui_controller(
    *,
    app_dir: Path,
    default_config_path: Path,
    default_dockerfile: str,
    default_moulin_manifest: str,
    flash_bootloaders_tool: Path,
    xt_imager_tool: Path,
    remote_read_project_file: Callable[..., Any],
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    env: dict[str, str],
    confirm_action: Callable[[Any, Any], bool],
) -> AppUiController:
    return AppUiController(
        app_dir=app_dir,
        default_config_path=default_config_path,
        default_dockerfile=default_dockerfile,
        default_moulin_manifest=default_moulin_manifest,
        flash_bootloaders_tool=flash_bootloaders_tool,
        xt_imager_tool=xt_imager_tool,
        remote_read_project_file=remote_read_project_file,
        manifest_cache=manifest_cache,
        env=env,
        confirm_action=confirm_action,
    )
