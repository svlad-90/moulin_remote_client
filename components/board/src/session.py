"""Board session command service."""

from __future__ import annotations

from typing import Any, Callable

from components.config.api import accessors as config_accessors
from components.remote.api import transport


class BoardSessionCommandService:
    """Own board-host connection and shell command use cases."""

    def connect_command(self, board_host: str) -> list[str]:
        return transport.ssh_probe_command(board_host, "printf 'ssh=ok\\n'; uname -a | sed 's/^/target=/'")

    def connect_command_for_config(self, config: dict[str, Any]) -> list[str]:
        return self.connect_command(config_accessors.board_host_spec_for_config(config))

    def interactive_shell_command(self, board_host: str) -> list[str]:
        return transport.ssh_command(board_host, tty="-t")

    def interactive_shell_command_for_config(self, config: dict[str, Any]) -> list[str]:
        return self.interactive_shell_command(config_accessors.board_host_spec_for_config(config))

    def run_interactive_shell(
        self,
        config: dict[str, Any],
        runner: Callable[[list[str]], Any],
    ) -> Any:
        return runner(self.interactive_shell_command_for_config(config))


def board_session_command_service() -> BoardSessionCommandService:
    return BoardSessionCommandService()
