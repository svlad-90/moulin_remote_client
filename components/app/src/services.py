"""Application service composition controller."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

from components.app.src import jobs as app_jobs
from components.app.src import ui as app_ui
from components.app.src import workflows as app_workflows
from components.jobs.api import connection_workflow as job_connection_workflow
from components.jobs.api import session as job_session
from components.jobs.api import workflow as job_workflow
from components.process.api import execution as process_execution_api
from components.sync.api import display as sync_display
from components.sync.api import workflow as sync_workflow
from components.ui.api import dialog_workflow as ui_dialog_workflow
from components.ui.api import preflight as ui_preflight
from components.ui.api.menu import MenuItem


class AppServicesController:
    """Compose application use-case controllers for a TUI session."""

    def __init__(
        self,
        *,
        app_dir: Path,
        default_config_path: Path,
        default_dockerfile: str,
        default_moulin_manifest: str,
        default_build_targets: str,
        flash_bootloaders_tool: Path,
        xt_imager_tool: Path,
        remote_read_project_file: Callable[..., Any],
        manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
        save_config: Callable[[dict[str, Any]], Any],
        env: dict[str, str],
        read_input: Callable[[str], str],
        write_line: Callable[..., Any],
        subprocess_call: Callable[..., int] = subprocess.call,
    ) -> None:
        self.app_dir = app_dir
        self.default_config_path = default_config_path
        self.default_dockerfile = default_dockerfile
        self.default_moulin_manifest = default_moulin_manifest
        self.default_build_targets = default_build_targets
        self.flash_bootloaders_tool = flash_bootloaders_tool
        self.xt_imager_tool = xt_imager_tool
        self.remote_read_project_file = remote_read_project_file
        self.manifest_cache = manifest_cache
        self.save_config = save_config
        self.env = env
        self.read_input = read_input
        self.write_line = write_line
        self.subprocess_call = subprocess_call
        self.process_execution = process_execution_api.process_execution_service()
        self.ui = app_ui.app_ui_controller(
            app_dir=app_dir,
            default_config_path=default_config_path,
            default_dockerfile=default_dockerfile,
            default_moulin_manifest=default_moulin_manifest,
            flash_bootloaders_tool=flash_bootloaders_tool,
            xt_imager_tool=xt_imager_tool,
            remote_read_project_file=remote_read_project_file,
            manifest_cache=manifest_cache,
            env=env,
            confirm_action=lambda port, content: self.dialog_workflow_controller().run_confirm_dialog(port, content),
        )
        command_display = sync_display.sync_command_display_service()
        self.jobs = app_jobs.app_job_controller(
            terminate_process_group=self.process_execution.terminate_process_group,
            display_command=command_display.display_command,
            display_command_lines=command_display.display_command_lines,
            format_preflight=ui_preflight.format_preflight,
            confirm_dialog=lambda port, content: self.dialog_workflow_controller().run_confirm_dialog(port, content),
        )
        self.workflows = app_workflows.app_workflow_controller(
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
            run_commands=lambda target, title, commands: target.command_workflow_service().run_commands(target, title, commands),
            capture_command=self.process_execution.capture_command,
            subprocess_call=subprocess_call,
        )

    def build_items(self, port: Any) -> list[MenuItem]:
        return self.ui.build_items(port)

    def run(self, port: Any) -> None:
        self.ui.run(port)

    def handle_main_key(self, port: Any, ch: int) -> None:
        self.ui.handle_main_key(port, ch)

    def draw(self, port: Any) -> None:
        self.ui.draw(port)

    def run_selected(self, port: Any) -> None:
        self.ui.run_selected(port)

    def stop_running_preview(self, port: Any, slot: str | None = None) -> str:
        return self.jobs.stop_running_preview(port, slot)

    def stop_running_command(self, port: Any, slot: str | None = None) -> None:
        self.jobs.stop_running_command(port, slot)

    def finish_active_job(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.jobs.finish_active_job(port, job)

    def start_next_active_job_command(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.jobs.start_next_active_job_command(port, job)

    def poll_active_jobs(self, port: Any) -> None:
        self.jobs.poll_active_jobs(port)

    def poll_active_job(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.jobs.poll_active_job(port, job)

    def command_workflow_service(self, port: Any) -> job_workflow.CommandWorkflowService:
        return self.jobs.command_workflow_service(port)

    def connection_workflow_service(self, port: Any) -> job_connection_workflow.ConnectionWorkflowService:
        return self.jobs.connection_workflow_service(port)

    def job_session_controller(self, port: Any) -> job_session.JobSessionController:
        return self.jobs.job_session_controller(port)

    def dialog_workflow_controller(self) -> ui_dialog_workflow.DialogWorkflowController:
        return self.workflows.dialog_workflow_controller()

    def config_workflow_controller(self, port: Any) -> app_workflows.config_workflow.ConfigWorkflowController:
        return self.workflows.config_workflow_controller(port)

    def sync_workflow_controller(self, port: Any) -> sync_workflow.SyncWorkflowController:
        return self.workflows.sync_workflow_controller(port)

    def terminal_session_controller(self, port: Any) -> app_workflows.local_terminal_session.TerminalSessionController:
        return self.workflows.terminal_session_controller(port)

    def run_sync_screen(self, port: Any) -> None:
        self.workflows.run_sync_screen(port)

    def confirm_sync_action(self, port: Any, label: str, description: str) -> bool:
        return self.workflows.confirm_sync_action(port, label, description)

    def wait_message(self, port: Any, message: str) -> None:
        self.workflows.wait_message(port, message)

    def show_message(self, port: Any, title: str, lines: list[str]) -> None:
        self.workflows.show_message(port, title, lines)

    def remote_project_config_ready(self, port: Any) -> bool:
        return self.workflows.remote_project_config_ready(port)

    def prompt(self, port: Any, label: str, current: str) -> str:
        return self.workflows.prompt(port, label, current)


def app_services_controller(
    *,
    app_dir: Path,
    default_config_path: Path,
    default_dockerfile: str,
    default_moulin_manifest: str,
    default_build_targets: str,
    flash_bootloaders_tool: Path,
    xt_imager_tool: Path,
    remote_read_project_file: Callable[..., Any],
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    save_config: Callable[[dict[str, Any]], Any],
    env: dict[str, str],
    read_input: Callable[[str], str],
    write_line: Callable[..., Any],
    subprocess_call: Callable[..., int] = subprocess.call,
) -> AppServicesController:
    return AppServicesController(
        app_dir=app_dir,
        default_config_path=default_config_path,
        default_dockerfile=default_dockerfile,
        default_moulin_manifest=default_moulin_manifest,
        default_build_targets=default_build_targets,
        flash_bootloaders_tool=flash_bootloaders_tool,
        xt_imager_tool=xt_imager_tool,
        remote_read_project_file=remote_read_project_file,
        manifest_cache=manifest_cache,
        save_config=save_config,
        env=env,
        read_input=read_input,
        write_line=write_line,
        subprocess_call=subprocess_call,
    )
