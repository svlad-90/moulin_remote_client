"""Terminal session workflows that temporarily leave the TUI."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Callable

from components.remote.api import transport

from components.config.api import accessors as config_accessor_api


class TerminalSessionController:
    """Run interactive terminal workflows outside the curses UI."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        suspend_tui: Callable[[], Any],
        restore_tui: Callable[[], Any],
        read_input: Callable[[str], str],
        write_line: Callable[..., Any],
        run_remote_shell: Callable[[], int],
        run_board_shell: Callable[[], int],
        run_command: Callable[[list[str]], int],
    ) -> None:
        self.config = config
        self.suspend_tui = suspend_tui
        self.restore_tui = restore_tui
        self.read_input = read_input
        self.write_line = write_line
        self.run_remote_shell = run_remote_shell
        self.run_board_shell = run_board_shell
        self.run_command = run_command

    def run_local_callable(self, port: Any, title: str, callback: Callable[[], None]) -> None:
        self.suspend_tui()
        try:
            self.write_line()
            self.write_line(f"== {title} ==")
            callback()
            self.read_input("Press Enter to return to Moulin client...")
            port.status = f"{title}: done"
            port.last_exit = 0
        except SystemExit as exc:
            self.write_line(exc)
            self.read_input("Press Enter to return to Moulin client...")
            port.status = f"{title}: failed"
            port.last_exit = 1
        finally:
            self.restore_tui()

    def open_remote_shell(self, port: Any) -> None:
        self.suspend_tui()
        try:
            self.write_line()
            self.write_line("Moulin build host shell")
            self.write_line(f"build host: {config_accessor_api.remote_spec_for_config(self.config)}")
            self.write_line(f"cwd: {config_accessor_api.remote_project_dir_for_config(self.config)}")
            self.write_line("Return to TUI: type 'exit' or press Ctrl-D.")
            self.write_line()
            rc = self.run_remote_shell()
            port.last_exit = rc
            self.read_input("Shell exited. Press Enter to return to Moulin client...")
            port.status = f"Remote shell closed: exit {rc}"
        finally:
            self.restore_tui()

    def open_board_shell(self, port: Any) -> None:
        self.suspend_tui()
        try:
            self.write_line()
            self.write_line("Moulin board host shell")
            self.write_line(f"board host: {config_accessor_api.board_host_spec_for_config(self.config)}")
            self.write_line("Return to TUI: type 'exit' or press Ctrl-D.")
            self.write_line()
            rc = self.run_board_shell()
            port.last_exit = rc
            self.read_input("Shell exited. Press Enter to return to Moulin client...")
            port.status = f"Board host shell closed: exit {rc}"
        finally:
            self.restore_tui()

    def open_local_directory_shell(self, port: Any, title: str, path: Path) -> None:
        script = (
            f"dir={shlex.quote(str(path))}\n"
            "[ -d \"$dir\" ] || { echo \"directory not found: $dir\"; echo 'Pull or create the workspace first.'; exit 2; }\n"
            "cd \"$dir\" && exec bash -l\n"
        )
        self.open_command_shell(
            port,
            title,
            ["local directory", str(path)],
            ["bash", "-lc", script],
        )

    def open_build_host_directory_shell(self, port: Any, title: str, path: str) -> None:
        host = config_accessor_api.remote_spec_for_config(self.config)
        command = f"cd {shlex.quote(path)} && exec bash -l"
        self.open_command_shell(
            port,
            title,
            [f"build host: {host}", f"cwd: {path}"],
            transport.ssh_command(host, command, tty="-t"),
        )

    def open_board_host_directory_shell(self, port: Any, title: str, path: str) -> None:
        host = config_accessor_api.board_host_spec_for_config(self.config)
        command = f"cd {shlex.quote(path)} && exec bash -l"
        self.open_command_shell(
            port,
            title,
            [f"board host: {host}", f"cwd: {path}"],
            transport.ssh_command(host, command, tty="-t"),
        )

    def open_command_shell(self, port: Any, title: str, lines: list[str], command: list[str]) -> None:
        self.suspend_tui()
        try:
            self.write_line()
            self.write_line(title)
            for line in lines:
                self.write_line(line)
            self.write_line("Return to TUI: type 'exit' or press Ctrl-D.")
            self.write_line()
            rc = self.run_command(command)
            port.last_exit = rc
            self.read_input("Shell exited. Press Enter to return to Moulin client...")
            port.status = f"{title} closed: exit {rc}"
        finally:
            self.restore_tui()


def terminal_session_controller(
    config: dict[str, Any],
    *,
    suspend_tui: Callable[[], Any],
    restore_tui: Callable[[], Any],
    read_input: Callable[[str], str],
    write_line: Callable[..., Any],
    run_remote_shell: Callable[[], int],
    run_board_shell: Callable[[], int],
    run_command: Callable[[list[str]], int],
) -> TerminalSessionController:
    return TerminalSessionController(
        config,
        suspend_tui=suspend_tui,
        restore_tui=restore_tui,
        read_input=read_input,
        write_line=write_line,
        run_remote_shell=run_remote_shell,
        run_board_shell=run_board_shell,
        run_command=run_command,
    )
