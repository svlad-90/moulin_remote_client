"""Main menu command item service."""

from __future__ import annotations

import shlex
from typing import Any

from components.board.api import workflow as board_workflow_api
from components.remote.api import workflow as remote_workflow_api
from components.sync.api import workflow as sync_workflow_api
from components.ui.api import menu as ui_menu_api
from components.ui.api import session as ui_session_api
from components.ui.api.menu import MenuItem


class MainMenuCommandItemsService:
    """Build command-oriented main menu items and handlers."""

    def __init__(
        self,
        *,
        remote_command_workflow: remote_workflow_api.RemoteCommandWorkflowService,
        sync_command_workflow: sync_workflow_api.SyncCommandWorkflowService,
        board_command_workflow: board_workflow_api.BoardCommandWorkflowService,
    ) -> None:
        self.remote_command_workflow = remote_command_workflow
        self.sync_command_workflow = sync_command_workflow
        self.board_command_workflow = board_command_workflow

    def build_items(self) -> list[MenuItem]:
        return [
            MenuItem(
                "Build Docker image",
                "build commands",
                "Rebuild the configured Docker image on the remote target.",
                lambda app: shlex.join(
                    self.remote_command_workflow.docker_image_command(
                        app.config,
                        docker_image=app.docker_image,
                    )
                ),
                lambda app: self.run_build_command(
                    app,
                    "Build Docker image",
                    self.remote_command_workflow.docker_image_command(
                        app.config,
                        docker_image=app.docker_image,
                    ),
                ),
                confirm=True,
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Regenerate Moulin/Ninja",
                "build commands",
                "Run Moulin on the remote target and refresh Ninja files.",
                lambda app: shlex.join(
                    self.remote_command_workflow.moulin_regen_command(
                        app.config,
                        docker_image=app.docker_image,
                        build_params=app.build_params,
                    )
                ),
                lambda app: self.run_build_command(
                    app,
                    "Regenerate Moulin/Ninja",
                    self.remote_command_workflow.moulin_regen_command(
                        app.config,
                        docker_image=app.docker_image,
                        build_params=app.build_params,
                    ),
                ),
                confirm=True,
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Run product build",
                "build commands",
                "Run configured Ninja targets on the remote target.",
                lambda app: shlex.join(
                    self.remote_command_workflow.product_build_command(
                        app.config,
                        docker_image=app.docker_image,
                        targets=app.build_targets,
                    )
                ),
                lambda app: self.run_build_command(
                    app,
                    "Run product build",
                    self.remote_command_workflow.product_build_command(
                        app.config,
                        docker_image=app.docker_image,
                        targets=app.build_targets,
                    ),
                ),
                confirm=True,
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Stop running command",
                "build commands",
                "Gracefully stop the currently running build or sync command, then force-kill it if it does not exit.",
                lambda app: app.stop_running_preview("build"),
                lambda app: app.stop_running_command("build"),
                confirm=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Connect board host",
                "board host session",
                "Check SSH access to the configured board host or mark it disconnected.",
                lambda app: ui_session_api.board_host_connection_preview(
                    app.board_connection_state,
                    self.board_command_workflow.connect_command(app.config),
                ),
                lambda app: app.connection_workflow_service().toggle_board_host(app),
                allow_during_job=True,
            ),
            MenuItem(
                "Open board host shell",
                "board host session",
                "Open SSH shell on the board host; exit returns to this TUI.",
                lambda app: shlex.join(self.board_command_workflow.interactive_shell_command(app.config)),
                lambda app: app.terminal_session_controller().open_board_shell(app),
                allow_during_job=True,
            ),
            MenuItem(
                "Copy build artifacts",
                "board commands",
                "Copy configured build target artifacts from the build host project checkout to the board host artifacts directory.",
                lambda app: ui_menu_api.command_preview(self.copy_build_artifacts_commands(app)),
                lambda app: self.board_command_workflow.run_copy_build_artifacts(
                    app.config,
                    artifact_targets=getattr(app, "board_artifacts", "") or app.build_targets,
                    build_params=app.build_params,
                    runner=lambda title, commands: app.command_workflow_service().run_commands(app, title, commands),
                ),
                confirm=True,
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Flash bootloaders",
                "board commands",
                "Deploy the bootloader flashing helper to the board host, enter flash mode, flash x5h_bootloaders.yaml, then switch the board to boot mode.",
                lambda app: ui_menu_api.command_preview(
                    self.board_command_workflow.flash_bootloaders_commands(app.config)
                ),
                lambda app: self.board_command_workflow.run_flash_bootloaders(
                    app.config,
                    runner=lambda title, commands: app.command_workflow_service().run_commands(app, title, commands),
                ),
                confirm=True,
                allow_during_job=False,
            ),
            MenuItem(
                "Flash UFS image",
                "board commands",
                "Deploy the UFS imager to the board host and flash artifacts/full_ufs.img.gz to UFS over /dev/GEN5_CONSOLE.",
                lambda app: ui_menu_api.command_preview(
                    self.board_command_workflow.flash_ufs_image_commands(app.config)
                ),
                lambda app: self.board_command_workflow.run_flash_ufs_image(
                    app.config,
                    runner=lambda title, commands: app.command_workflow_service().run_commands(app, title, commands),
                ),
                confirm=True,
                allow_during_job=False,
            ),
            MenuItem(
                "Stop board command",
                "board commands",
                "Gracefully stop the currently running board command, then force-kill it if it does not exit.",
                lambda app: app.stop_running_preview("board"),
                lambda app: app.stop_running_command("board"),
                confirm=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Sync mapped files",
                "sync",
                "Pull or push the configured local/remote source mappings used for patch development.",
                lambda app: "Open the sync workflow for configured mappings.",
                lambda app: app.sync_screen(),
                requires_remote=True,
                requires_project=True,
            ),
        ]

    def run_build_command(self, app: Any, title: str, command: list[str]) -> int:
        return app.command_workflow_service().run_build_command(
            app,
            title,
            command,
            config=app.config,
            parameters=app.build_params,
            targets=app.build_targets,
            docker_image=app.docker_image,
            build_command_sequence=self.sync_command_workflow.build_command_sequence,
        )

    def copy_build_artifacts_commands(self, app: Any) -> list[list[str]]:
        return self.board_command_workflow.copy_build_artifacts_commands(
            app.config,
            artifact_targets=getattr(app, "board_artifacts", "") or app.build_targets,
            build_params=app.build_params,
        )


def main_menu_command_items_service(
    *,
    remote_command_workflow: remote_workflow_api.RemoteCommandWorkflowService,
    sync_command_workflow: sync_workflow_api.SyncCommandWorkflowService,
    board_command_workflow: board_workflow_api.BoardCommandWorkflowService,
) -> MainMenuCommandItemsService:
    return MainMenuCommandItemsService(
        remote_command_workflow=remote_command_workflow,
        sync_command_workflow=sync_command_workflow,
        board_command_workflow=board_command_workflow,
    )
