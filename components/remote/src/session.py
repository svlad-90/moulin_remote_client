"""Remote build-host session command service."""

from __future__ import annotations

import shlex
from typing import Any, Callable

from components.config.api import accessors as config_accessors


class RemoteSessionCommandService:
    """Own build-host SSH session and shell command use cases."""

    def remote_shell_command(self, remote: str, project_dir: str, command: str) -> list[str]:
        if not project_dir:
            raise SystemExit("Remote project directory is not configured")
        return ["ssh", remote, f"cd {shlex.quote(project_dir)} && {command}"]

    def interactive_shell_command(self, remote: str, project_dir: str) -> list[str]:
        if not project_dir:
            raise SystemExit("Remote project directory is not configured")
        command = f"cd {shlex.quote(project_dir)} && exec bash -l"
        return ["ssh", "-t", remote, command]

    def interactive_shell_command_for_config(self, config: dict[str, Any]) -> list[str]:
        return self.interactive_shell_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
        )

    def connect_command(self, remote: str, project_dir: str = "") -> list[str]:
        check = (
            f"cd {shlex.quote(project_dir)} && printf 'ssh=ok\\n'; pwd | sed 's/^/cwd=/'"
            if project_dir
            else "printf 'ssh=ok\\n'; pwd | sed 's/^/cwd=/'"
        )
        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            remote,
            check,
        ]

    def connect_command_for_config(self, config: dict[str, Any]) -> list[str]:
        project_dir = config_accessors.remote_project_dir_for_config(config)
        return self.connect_command(
            config_accessors.remote_spec_for_config(config),
            project_dir if project_dir else "",
        )

    def run_interactive_shell(
        self,
        config: dict[str, Any],
        runner: Callable[[list[str]], Any],
    ) -> Any:
        return runner(self.interactive_shell_command_for_config(config))


def remote_session_command_service() -> RemoteSessionCommandService:
    return RemoteSessionCommandService()
