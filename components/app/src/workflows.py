"""Application workflow controller."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

from components.board.api import session as board_session_api
from components.build_runtime.api import env as config_env
from components.config_workflow.api import workflow as config_workflow
from components.process.api import terminal_session as local_terminal_session
from components.remote.api import workflow as remote_workflow_api
from components.sync.api import workflow as sync_workflow
from components.ui.api import dialog_workflow as ui_dialog_workflow
from components.ui.api import session as ui_session


class AppWorkflowController:
    """Own configuration, sync, shell, and dialog workflows for the TUI app."""

    def __init__(
        self,
        *,
        app_dir: Path,
        default_config_path: Path,
        default_dockerfile: str,
        default_moulin_manifest: str,
        default_build_targets: str,
        remote_read_project_file: Callable[..., Any],
        manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
        save_config: Callable[[dict[str, Any]], Any],
        env: dict[str, str],
        read_input: Callable[[str], str],
        write_line: Callable[..., Any],
        run_commands: Callable[[Any, str, list[list[str]]], Any],
        capture_command: Callable[..., Any],
        subprocess_call: Callable[..., int] = subprocess.call,
    ) -> None:
        self.app_dir = app_dir
        self.default_config_path = default_config_path
        self.default_dockerfile = default_dockerfile
        self.default_moulin_manifest = default_moulin_manifest
        self.default_build_targets = default_build_targets
        self.remote_read_project_file = remote_read_project_file
        self.manifest_cache = manifest_cache
        self.save_config = save_config
        self.env = env
        self.read_input = read_input
        self.write_line = write_line
        self.run_commands = run_commands
        self.capture_command = capture_command
        self.subprocess_call = subprocess_call
        self.remote_command_workflow = remote_workflow_api.remote_command_workflow_service(
            default_dockerfile=default_dockerfile,
            default_moulin_manifest=default_moulin_manifest,
        )
        self.board_session_service = board_session_api.board_session_command_service()

    def dialog_workflow_controller(self) -> ui_dialog_workflow.DialogWorkflowController:
        return ui_dialog_workflow.dialog_workflow_controller()

    def config_workflow_controller(self, port: Any) -> config_workflow.ConfigWorkflowController:
        return config_workflow.config_workflow_controller(
            port.config,
            app_dir=self.app_dir,
            default_config_path=self.default_config_path,
            default_build_targets=config_env.build_targets_from_env(self.env, self.default_build_targets),
            default_moulin_manifest=self.default_moulin_manifest,
            default_dockerfile=self.default_dockerfile,
            save_config=self.save_config,
            capture_command=self.capture_command,
            remote_read_project_file=self.remote_read_project_file,
            manifest_cache=self.manifest_cache,
            confirm_action=port.confirm_sync_action,
            reload_runtime=port.load_active_project_runtime,
            restore_project_menu_input=lambda: port.screen.timeout(-1),
            reset_preflight=lambda: ui_session.reset_preflight(port),
        )

    def sync_workflow_controller(self, port: Any) -> sync_workflow.SyncWorkflowController:
        return sync_workflow.sync_workflow_controller(
            port.config,
            app_dir=self.app_dir,
            save_config=self.save_config,
            capture_command=self.capture_command,
            run_commands=self.run_commands,
        )

    def terminal_session_controller(self, port: Any) -> local_terminal_session.TerminalSessionController:
        return local_terminal_session.terminal_session_controller(
            port.config,
            suspend_tui=port.suspend_tui,
            restore_tui=port.restore_tui,
            read_input=self.read_input,
            write_line=self.write_line,
            run_remote_shell=lambda: self.remote_command_workflow.run_interactive_shell(port.config, self.subprocess_call),
            run_board_shell=lambda: self.board_session_service.run_interactive_shell(port.config, self.subprocess_call),
        )

    def run_sync_screen(self, port: Any) -> None:
        self.sync_workflow_controller(port).run_sync_screen(port)

    def confirm_sync_action(self, port: Any, label: str, description: str) -> bool:
        return self.dialog_workflow_controller().confirm_sync_action(port, label, description)

    def wait_message(self, port: Any, message: str) -> None:
        self.dialog_workflow_controller().wait_message(port, message)

    def show_message(self, port: Any, title: str, lines: list[str]) -> None:
        self.dialog_workflow_controller().show_message(port, title, lines)

    def remote_project_config_ready(self, port: Any) -> bool:
        return self.config_workflow_controller(port).remote_project_config_ready(port)

    def prompt(self, port: Any, label: str, current: str) -> str:
        return self.dialog_workflow_controller().prompt(port, label, current)


def app_workflow_controller(
    *,
    app_dir: Path,
    default_config_path: Path,
    default_dockerfile: str,
    default_moulin_manifest: str,
    default_build_targets: str,
    remote_read_project_file: Callable[..., Any],
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    save_config: Callable[[dict[str, Any]], Any],
    env: dict[str, str],
    read_input: Callable[[str], str],
    write_line: Callable[..., Any],
    run_commands: Callable[[Any, str, list[list[str]]], Any],
    capture_command: Callable[..., Any],
    subprocess_call: Callable[..., int] = subprocess.call,
) -> AppWorkflowController:
    return AppWorkflowController(
        app_dir=app_dir,
        default_config_path=default_config_path,
        default_dockerfile=default_dockerfile,
        default_moulin_manifest=default_moulin_manifest,
        default_build_targets=default_build_targets,
        remote_read_project_file=remote_read_project_file,
        manifest_cache=manifest_cache,
        save_config=save_config,
        env=env,
        read_input=read_input,
        write_line=write_line,
        run_commands=run_commands,
        capture_command=capture_command,
        subprocess_call=subprocess_call,
    )
