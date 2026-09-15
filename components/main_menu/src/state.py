"""Main menu state controller."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from components.config.api import accessors as config_accessors
from components.project.api import selection as project_selection_api
from components.ui.api import mapping_status as ui_mapping_status
from components.ui.api import menu as ui_menu
from components.ui.api import preflight as ui_preflight
from components.ui.api.menu import MenuItem


class MainMenuStateController:
    """Resolve menu availability and status for the active app state."""

    def __init__(self, *, app_dir: Path) -> None:
        self.app_dir = app_dir
        self.mapping_selection_service = project_selection_api.project_mapping_selection_service()

    def item_enabled(self, port: Any, item: MenuItem) -> bool:
        requirements = self._project_action_requirements(port)
        return ui_menu.item_enabled(
            item,
            active_job=port.active_job,
            board_job=port.board_job,
            board_host_has_ssh=config_accessors.board_host_has_ssh_for_config(port.config),
            board_connected=port.board_connection_state == "connected",
            build_connected=port.connection_state == "connected",
            remote_has_ssh=config_accessors.remote_has_ssh_for_config(port.config),
            remote_has_project_dir=config_accessors.remote_has_project_dir_for_config(port.config),
            prepare_remote_project_needed=requirements["prepare_remote_project"],
            checkout_git_ref_needed=requirements["checkout_git_ref"],
        )

    def disabled_reason(self, port: Any, item: MenuItem) -> str:
        requirements = self._project_action_requirements(port)
        return ui_menu.disabled_reason(
            item,
            active_job=port.active_job,
            board_job=port.board_job,
            board_host_user=config_accessors.board_host_user_for_config(port.config),
            board_host_host=config_accessors.board_host_host_for_config(port.config),
            board_connected=port.board_connection_state == "connected",
            build_connected=port.connection_state == "connected",
            remote_has_user=config_accessors.remote_has_user_for_config(port.config),
            remote_has_host=config_accessors.remote_has_host_for_config(port.config),
            remote_has_project_dir=config_accessors.remote_has_project_dir_for_config(port.config),
            prepare_remote_project_needed=requirements["prepare_remote_project"],
            checkout_git_ref_needed=requirements["checkout_git_ref"],
        )

    def mapping_status_snapshot(self, port: Any) -> dict[str, str]:
        names, active_mappings, error = self.mapping_selection_service.active_mapping_state_for_config(
            port.config,
            config_accessors.mapping_selection_path_for_config(port.config, self.app_dir),
        )
        return ui_mapping_status.mapping_status_snapshot(
            names,
            active_mappings,
            error,
            local_base=config_accessors.local_project_dir_for_config(port.config, self.app_dir),
        )

    def _project_action_requirements(self, port: Any) -> dict[str, bool]:
        return ui_preflight.project_action_requirements(
            port.preflight_values,
            project_git_url=config_accessors.project_git_url_for_config(port.config),
            project_git_ref=config_accessors.project_git_ref_for_config(port.config),
        )


def main_menu_state_controller(*, app_dir: Path) -> MainMenuStateController:
    return MainMenuStateController(app_dir=app_dir)
