"""Main menu setup and preflight item service."""

from __future__ import annotations

import shlex
from typing import Any

from components.config.api import accessors as config_accessor_api
from components.config.api import profiles as config_profile_api
from components.remote.api import workflow as remote_workflow_api
from components.ui.api import preflight as ui_preflight_api
from components.ui.api import session as ui_session_api
from components.ui.api.menu import MenuItem


class MainMenuSetupItemsService:
    """Build setup, build-host session, and preflight action menu items."""

    def __init__(
        self,
        *,
        remote_command_workflow: remote_workflow_api.RemoteCommandWorkflowService,
    ) -> None:
        self.remote_command_workflow = remote_command_workflow

    def build_items(self, app: Any) -> list[MenuItem]:
        items = self.setup_items()
        items.extend(self.build_host_session_items())
        items.extend(self.preflight_action_items(app))
        return items

    def setup_items(self) -> list[MenuItem]:
        return [
            MenuItem(
                "Build host configuration",
                "setup",
                "Add, delete, select, and edit build-machine SSH profiles used for Moulin and Ninja.",
                lambda app: "Open build host profile setup.",
                lambda app: app.config_workflow_controller().run_remote_configurations_screen(app),
                allow_during_job=True,
            ),
            MenuItem(
                "Board host configuration",
                "setup",
                "Add, delete, select, and edit board-access SSH profiles used for runtime checks.",
                lambda app: "Open board host profile setup.",
                lambda app: app.config_workflow_controller().run_board_host_configurations_screen(app),
                allow_during_job=True,
            ),
            MenuItem(
                "Project configurations",
                "setup",
                "Select and edit project-local build profile settings such as manifest, targets, parameters, Docker image, and local overlay.",
                lambda app: f"Active project: {config_profile_api.active_project(app.config).get('label') or config_profile_api.active_project(app.config).get('name')}",
                lambda app: app.config_workflow_controller().run_project_configurations_screen(app),
                allow_during_job=True,
            ),
        ]

    def build_host_session_items(self) -> list[MenuItem]:
        return [
            MenuItem(
                "Connect build host",
                "build host session",
                "Check SSH access and project preflight for the configured build host or mark it disconnected.",
                lambda app: ui_session_api.build_host_connection_preview(
                    app.connection_state,
                    self.remote_command_workflow.connect_command(app.config),
                ),
                lambda app: app.connection_workflow_service().toggle_build_host(app),
                requires_ssh=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Open build host shell",
                "build host session",
                "Open SSH shell in the remote product directory on the build host; exit returns to this TUI.",
                lambda app: shlex.join(self.remote_command_workflow.interactive_shell_command(app.config)),
                lambda app: app.terminal_session_controller().open_remote_shell(app),
                requires_remote=True,
                requires_project=True,
                allow_during_job=True,
            ),
        ]

    def preflight_action_items(self, app: Any) -> list[MenuItem]:
        preflight_actions = ui_preflight_api.project_action_requirements(
            app.preflight_values,
            project_git_url=config_accessor_api.project_git_url_for_config(app.config),
            project_git_ref=config_accessor_api.project_git_ref_for_config(app.config),
        )
        items = []
        if preflight_actions["prepare_remote_project"]:
            items.append(
                MenuItem(
                    "Prepare remote project",
                    "build commands",
                    "Create or repair the configured target checkout when preflight detects a missing project, non-git directory, or Git origin mismatch.",
                    lambda app: shlex.join(self.remote_command_workflow.prepare_project_command(app.config)),
                    lambda app: app.command_workflow_service().run_commands(
                        app,
                        "Prepare remote project",
                        [self.remote_command_workflow.prepare_project_command(app.config)],
                    ),
                    confirm=True,
                    requires_ssh=True,
                    requires_project=True,
                )
            )
        if preflight_actions["checkout_git_ref"]:
            items.append(
                MenuItem(
                    "Checkout project Git ref",
                    "build commands",
                    "Switch the existing remote checkout to the configured project Git branch/ref when the working tree has no tracked local changes.",
                    lambda app: shlex.join(self.remote_command_workflow.checkout_git_ref_command(app.config)),
                    lambda app: app.command_workflow_service().run_commands(
                        app,
                        "Checkout project Git ref",
                        [self.remote_command_workflow.checkout_git_ref_command(app.config)],
                    ),
                    confirm=True,
                    requires_remote=True,
                    requires_project=True,
                )
            )
        return items


def main_menu_setup_items_service(
    *,
    remote_command_workflow: remote_workflow_api.RemoteCommandWorkflowService,
) -> MainMenuSetupItemsService:
    return MainMenuSetupItemsService(remote_command_workflow=remote_command_workflow)
