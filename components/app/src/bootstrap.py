"""Application bootstrap controller."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from components.app.api import client as app_client
from components.cli.api import workflow as cli_workflow
from components.build_runtime.api import runtime as config_runtime
from components.moulin.api import manifest as moulin_manifest
from components.process.api import execution as process_execution_api
from components.remote.api import discovery as remote_discovery_api


@dataclass(frozen=True)
class AppBootstrapSettings:
    app_dir: Path
    default_config: Path
    default_config_example: Path
    default_docker_image: str
    default_dockerfile: str
    default_build_targets: str
    default_moulin_manifest: str
    flash_bootloaders_tool: Path
    xt_imager_tool: Path
    profile_slow_ms: float


class AppBootstrapController:
    """Build and run the configured Moulin remote client application."""

    def __init__(
        self,
        settings: AppBootstrapSettings,
        *,
        env: dict[str, str],
        manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
        curses_wrapper: Callable[[Callable[[Any], Any]], Any] = curses.wrapper,
        capture_command: Callable[..., str] | None = None,
        run_command: Callable[..., Any] | None = None,
        read_input: Callable[[str], str] = input,
        write_line: Callable[..., Any] = print,
        monotonic: Callable[[], float],
    ) -> None:
        self.settings = settings
        self.env = env
        self.manifest_cache = manifest_cache
        self.curses_wrapper = curses_wrapper
        self.process_execution = process_execution_api.process_execution_service()
        self.capture_command = capture_command or self.process_execution.capture_command
        self.run_command = run_command or self.process_execution.run_command
        self.read_input = read_input
        self.write_line = write_line
        self.monotonic = monotonic
        self.remote_project_file_reader = remote_discovery_api.remote_project_discovery_service().project_file_reader(
            lambda argv: self.capture_command(argv, echo=False, timeout=15)
        )
        self.load_config = self._build_load_config()
        self.save_config = self._build_save_config()

    def _build_load_config(self) -> Callable[[Path], dict[str, Any]]:
        return lambda path: config_runtime.load_runtime_config_for_env(
            path,
            example_path=self.settings.default_config_example,
            app_dir=self.settings.app_dir,
            env=self.env,
            default_build_targets=self.settings.default_build_targets,
            default_moulin_manifest=self.settings.default_moulin_manifest,
            default_dockerfile=self.settings.default_dockerfile,
        )

    def _build_save_config(self) -> Callable[[dict[str, Any]], None]:
        return lambda config: config_runtime.save_runtime_config(config, default_path=self.settings.default_config)

    def cli_runtime_context(self, config: dict[str, Any]) -> dict[str, Any]:
        return moulin_manifest.build_runtime_context_for_config(
            config,
            app_dir=self.settings.app_dir,
            env=self.env,
            default_docker_image=self.settings.default_docker_image,
            default_build_targets=self.settings.default_build_targets,
            default_moulin_manifest=self.settings.default_moulin_manifest,
            remote_read_project_file=self.remote_project_file_reader,
            cache=self.manifest_cache,
        )

    def client_app_class(self) -> type[Any]:
        return app_client.client_app_class(
            app_client.ClientAppDependencies(
                app_dir=self.settings.app_dir,
                default_config_path=self.settings.default_config,
                default_docker_image=self.settings.default_docker_image,
                default_dockerfile=self.settings.default_dockerfile,
                default_build_targets=self.settings.default_build_targets,
                default_moulin_manifest=self.settings.default_moulin_manifest,
                flash_bootloaders_tool=self.settings.flash_bootloaders_tool,
                xt_imager_tool=self.settings.xt_imager_tool,
                remote_read_project_file=self.remote_project_file_reader,
                manifest_cache=self.manifest_cache,
                save_config=self.save_config,
                env=self.env,
                read_input=self.read_input,
                write_line=self.write_line,
                monotonic=self.monotonic,
                profile_slow_ms=self.settings.profile_slow_ms,
            )
        )

    def run(self, argv: list[str], *, description: str | None) -> int:
        return cli_workflow.cli_workflow_controller(
            description=description,
            default_config=self.settings.default_config,
            app_dir=self.settings.app_dir,
            default_dockerfile=self.settings.default_dockerfile,
            default_moulin_manifest=self.settings.default_moulin_manifest,
            load_config=self.load_config,
            app_factory=self.client_app_class(),
            curses_wrapper=self.curses_wrapper,
            remote_runtime_context=self.cli_runtime_context,
            run_command=self.run_command,
            capture_command=self.capture_command,
            read_input=self.read_input,
            write_line=self.write_line,
            save_config=self.save_config,
        ).run(argv)


def app_bootstrap_controller(
    settings: AppBootstrapSettings,
    *,
    env: dict[str, str],
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    curses_wrapper: Callable[[Callable[[Any], Any]], Any] = curses.wrapper,
    capture_command: Callable[..., str] | None = None,
    run_command: Callable[..., Any] | None = None,
    read_input: Callable[[str], str] = input,
    write_line: Callable[..., Any] = print,
    monotonic: Callable[[], float],
) -> AppBootstrapController:
    return AppBootstrapController(
        settings,
        env=env,
        manifest_cache=manifest_cache,
        curses_wrapper=curses_wrapper,
        capture_command=capture_command,
        run_command=run_command,
        read_input=read_input,
        write_line=write_line,
        monotonic=monotonic,
    )
