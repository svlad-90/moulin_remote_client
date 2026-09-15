"""Command job workflow service."""

from __future__ import annotations

from typing import Any, Callable

from components.jobs.src.command_lifecycle import CommandLifecycleService
from components.jobs.src.command_runner import CommandRunnerService


class CommandWorkflowService:
    """Own the command job workflow from start through polling and finish."""

    def __init__(
        self,
        *,
        runner: CommandRunnerService,
        lifecycle: CommandLifecycleService,
    ) -> None:
        self.runner = runner
        self.lifecycle = lifecycle

    def run_commands(self, port: Any, title: str, commands: list[list[str]]) -> int:
        return self.runner.start_commands(
            port,
            title,
            commands,
            start_next_command=lambda job: self.start_next_command(port, job),
        )

    def run_build_command(
        self,
        port: Any,
        title: str,
        build_command: list[str],
        *,
        config: dict[str, Any],
        parameters: dict[str, str],
        targets: str,
        docker_image: str,
        build_command_sequence: Callable[[dict[str, Any], list[str], dict[str, str], str, str], list[list[str]]],
    ) -> int:
        commands = build_command_sequence(
            config,
            build_command,
            parameters=parameters,
            targets=targets,
            docker_image=docker_image,
        )
        return self.run_commands(port, title, commands)

    def finish_job(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.lifecycle.finish_job(port, job)

    def start_next_command(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.lifecycle.start_next_command(port, job)

    def poll_jobs(self, port: Any) -> None:
        self.lifecycle.poll_jobs(port)

    def poll_job(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.lifecycle.poll_job(port, job)


def command_workflow_service(
    *,
    runner: CommandRunnerService,
    lifecycle: CommandLifecycleService,
) -> CommandWorkflowService:
    return CommandWorkflowService(runner=runner, lifecycle=lifecycle)
