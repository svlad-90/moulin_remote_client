"""Local process execution service."""

from __future__ import annotations

import signal
import subprocess
from typing import TextIO

from components.process.src import commands as process_commands


class ProcessExecutionService:
    """Own local subprocess execution and termination use cases."""

    def run_command(
        self,
        argv: list[str],
        *,
        check: bool = True,
        env: dict[str, str] | None = None,
        echo: bool = True,
        echo_stream: TextIO | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return process_commands.run_command(
            argv,
            check=check,
            env=env,
            echo=echo,
            echo_stream=echo_stream,
        )

    def capture_command(
        self,
        argv: list[str],
        *,
        echo: bool = True,
        timeout: float | None = None,
        echo_stream: TextIO | None = None,
    ) -> str:
        return process_commands.capture_command(
            argv,
            echo=echo,
            timeout=timeout,
            echo_stream=echo_stream,
        )

    def terminate_process_group(self, pid: int, sig: signal.Signals) -> None:
        process_commands.terminate_process_group(pid, sig)


def process_execution_service() -> ProcessExecutionService:
    return ProcessExecutionService()
