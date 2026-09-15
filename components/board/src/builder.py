"""Shared board-host shell command builder."""

from __future__ import annotations

import shlex
from pathlib import Path, PurePosixPath

from components.process.api import script as process_script_api


class BoardCommandBuilder:
    """Build low-level board-host shell and transfer command fragments."""

    def __init__(self, *, script_service: process_script_api.ProcessScriptService | None = None) -> None:
        self.script_service = script_service or process_script_api.process_script_service()

    def remote_shell_path(self, path: str) -> str:
        if path == "~":
            return "$HOME"
        if path.startswith("~/"):
            return "$HOME/" + path[2:]
        return path

    def quote_remote_shell_path(self, path: str) -> str:
        shell_path = self.remote_shell_path(path)
        if shell_path == "$HOME":
            return '"$HOME"'
        if shell_path.startswith("$HOME/"):
            return '"$HOME"/' + shlex.quote(shell_path[len("$HOME/") :])
        return shlex.quote(shell_path)

    def board_tool_remote_path(self, work_dir: str, tool: Path) -> str:
        return str(PurePosixPath(work_dir) / tool.name)

    def board_ssh_command(self, board_host: str, command: str, *, tty: bool = False) -> list[str]:
        argv = ["ssh"]
        if tty:
            argv.append("-tt")
            command = f"bash -lic {shlex.quote(command)}"
        argv.extend([board_host, command])
        return argv

    def board_interactive_shell_command(self, board_host: str) -> list[str]:
        return ["ssh", "-t", board_host]

    def board_deploy_tool_command(self, board_host: str, work_dir: str, tool: Path) -> list[str]:
        remote_path = self.board_tool_remote_path(work_dir, tool)
        script = (
            f"mkdir -p {self.quote_remote_shell_path(work_dir)} && "
            f"cat > {self.quote_remote_shell_path(remote_path)} && chmod +x {self.quote_remote_shell_path(remote_path)}"
        )
        return ["bash", "-lc", f"cat {shlex.quote(str(tool))} | ssh {shlex.quote(board_host)} {shlex.quote(script)}"]

    def board_deploy_tool_log_command(self, board_host: str, work_dir: str, tool: Path) -> list[str]:
        return self.local_log_command(
            "Deploy board helper",
            f"from: {tool}",
            f"to:   {board_host}:{self.board_tool_remote_path(work_dir, tool)}",
        )

    def local_log_command(self, *lines: str, exit_code: int = 0) -> list[str]:
        return self.script_service.local_log_command(*lines, exit_code=exit_code)

    def board_prepare_work_dir_command(self, board_host: str, artifacts_dir: str) -> list[str]:
        script = f"mkdir -p {self.quote_remote_shell_path(artifacts_dir)}"
        return self.board_ssh_command(board_host, script)


def board_command_builder() -> BoardCommandBuilder:
    return BoardCommandBuilder()
