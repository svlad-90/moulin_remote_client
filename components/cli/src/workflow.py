"""CLI command dispatch workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.cli.api import arguments as cli_arguments_api
from components.project.api import cli_workflow as project_cli_workflow_api
from components.remote.api import workflow as remote_workflow_api
from components.sync.api import workflow as sync_workflow_api
from components.ui.api import session as ui_session_api


class CliWorkflowController:
    """Parse CLI arguments and dispatch the selected command domain."""

    def __init__(
        self,
        *,
        description: str | None,
        default_config: Path,
        app_dir: Path,
        default_dockerfile: str,
        default_moulin_manifest: str,
        parse_args: Callable[..., Any] = cli_arguments_api.parse_args,
        load_config: Callable[[Path], dict[str, Any]],
        run_curses_app: Callable[..., Any] = ui_session_api.run_curses_app,
        app_factory: Callable[[Any, dict[str, Any]], Any],
        curses_wrapper: Callable[[Callable[[Any], Any]], Any],
        remote_runtime_context: Callable[[dict[str, Any]], Any],
        run_command: Callable[..., Any],
        capture_command: Callable[..., str],
        read_input: Callable[..., str],
        write_line: Callable[..., Any],
        save_config: Callable[[dict[str, Any]], Any],
    ) -> None:
        self.description = description
        self.default_config = default_config
        self.app_dir = app_dir
        self.default_dockerfile = default_dockerfile
        self.default_moulin_manifest = default_moulin_manifest
        self.parse_args = parse_args
        self.load_config = load_config
        self.run_curses_app = run_curses_app
        self.app_factory = app_factory
        self.curses_wrapper = curses_wrapper
        self.remote_runtime_context = remote_runtime_context
        self.run_command = run_command
        self.capture_command = capture_command
        self.read_input = read_input
        self.write_line = write_line
        self.save_config = save_config
        self.remote_command_workflow = remote_workflow_api.remote_command_workflow_service(
            default_dockerfile=default_dockerfile,
            default_moulin_manifest=default_moulin_manifest,
        )
        self.project_cli_workflow = project_cli_workflow_api.project_cli_workflow_service()
        self.sync_command_workflow = sync_workflow_api.sync_command_workflow_service(
            app_dir=app_dir,
            default_config_path=default_config,
        )

    def run(self, argv: list[str]) -> int:
        args = self.parse_args(argv, description=self.description, default_config=self.default_config)
        config = self.load_config(args.config)
        command = str(args.command)
        if command in ("sync-menu", "menu", "tui"):
            self.run_curses_app(config, app_factory=self.app_factory, wrapper=self.curses_wrapper)
        elif self.remote_command_workflow.supports_cli_command(command):
            self._run_remote_command(config, command)
        elif self.project_cli_workflow.supports_cli_command(command):
            self._run_project_command(config, command)
        elif self.sync_command_workflow.supports_cli_command(command):
            self._run_sync_command(config, command, list(getattr(args, "names", [])))
        return 0

    def _run_remote_command(self, config: dict[str, Any], command: str) -> None:
        self.remote_command_workflow.run_cli_command(
            config,
            command,
            runtime_context=lambda: self.remote_runtime_context(config),
            structured_script=self.remote_command_workflow.structured_script,
            runner=self.run_command,
            status_runner=lambda argv: self.run_command(argv, check=False),
        )

    def _run_project_command(self, config: dict[str, Any], command: str) -> None:
        self.project_cli_workflow.run_cli_project_command_for_config(
            config,
            command,
            app_dir=self.app_dir,
            docker_image=str(self.remote_runtime_context(config).get("docker_image", "")),
            structured_script=self.remote_command_workflow.structured_script,
            capture_command=self.capture_command,
            local_runner=lambda argv: self.run_command(argv, check=False),
            remote_runner=lambda argv: self.run_command(argv, check=False),
            read_input=self.read_input,
            write_line=self.write_line,
            save_config=self.save_config,
        )

    def _run_sync_command(self, config: dict[str, Any], command: str, names: list[str]) -> None:
        self.sync_command_workflow.run_cli_command(
            config,
            command,
            names,
            runner=self.run_command,
            write_line=self.write_line,
        )


def cli_workflow_controller(
    *,
    description: str | None,
    default_config: Path,
    app_dir: Path,
    default_dockerfile: str,
    default_moulin_manifest: str,
    load_config: Callable[[Path], dict[str, Any]],
    app_factory: Callable[[Any, dict[str, Any]], Any],
    curses_wrapper: Callable[[Callable[[Any], Any]], Any],
    remote_runtime_context: Callable[[dict[str, Any]], Any],
    run_command: Callable[..., Any],
    capture_command: Callable[..., str],
    read_input: Callable[..., str],
    write_line: Callable[..., Any],
    save_config: Callable[[dict[str, Any]], Any],
) -> CliWorkflowController:
    return CliWorkflowController(
        description=description,
        default_config=default_config,
        app_dir=app_dir,
        default_dockerfile=default_dockerfile,
        default_moulin_manifest=default_moulin_manifest,
        load_config=load_config,
        app_factory=app_factory,
        curses_wrapper=curses_wrapper,
        remote_runtime_context=remote_runtime_context,
        run_command=run_command,
        capture_command=capture_command,
        read_input=read_input,
        write_line=write_line,
        save_config=save_config,
    )
