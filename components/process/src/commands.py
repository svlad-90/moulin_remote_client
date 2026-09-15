"""Local subprocess execution helpers."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
from typing import Callable, TextIO


def run_command(
    argv: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
    echo: bool = True,
    echo_stream: TextIO | None = None,
) -> subprocess.CompletedProcess[str]:
    if echo:
        print("+ " + shlex.join(argv), file=echo_stream or sys.stdout)
    return subprocess.run(argv, text=True, check=check, env=env)


def capture_command(
    argv: list[str],
    *,
    echo: bool = True,
    timeout: float | None = None,
    echo_stream: TextIO | None = None,
) -> str:
    if echo:
        print("+ " + shlex.join(argv), file=echo_stream or sys.stderr)
    result = subprocess.run(
        argv,
        text=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=timeout,
        check=True,
    )
    return result.stdout


def terminate_process_group(
    pid: int,
    sig: signal.Signals,
    *,
    killpg: Callable[[int, signal.Signals], None] | None = None,
) -> None:
    killpg = killpg or os.killpg
    try:
        killpg(pid, sig)
    except ProcessLookupError:
        pass
