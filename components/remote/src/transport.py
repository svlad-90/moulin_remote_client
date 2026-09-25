"""Shared SSH/rsync transport command options."""

from __future__ import annotations

import shlex
from collections.abc import Iterable


SSH_TRANSPORT_OPTIONS = [
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=8",
    "-o",
    "ServerAliveInterval=15",
    "-o",
    "ServerAliveCountMax=2",
    "-o",
    "ControlMaster=auto",
    "-o",
    "ControlPersist=60",
    "-o",
    "ControlPath=/tmp/mrc-%C",
]

RSYNC_TRANSPORT_OPTIONS = [
    "--timeout=60",
]


def ssh_options(*, accept_new_host_key: bool = False) -> list[str]:
    argv = list(SSH_TRANSPORT_OPTIONS)
    if accept_new_host_key:
        argv.extend(["-o", "StrictHostKeyChecking=accept-new"])
    return argv


def ssh_command(
    remote: str,
    command: str = "",
    *,
    tty: str = "",
    accept_new_host_key: bool = False,
) -> list[str]:
    argv = ["ssh", *ssh_options(accept_new_host_key=accept_new_host_key)]
    if tty:
        argv.append(tty)
    argv.append(remote)
    if command:
        argv.append(command)
    return argv


def ssh_probe_command(remote: str, command: str) -> list[str]:
    return ssh_command(remote, command)


def rsync_base_command(*, dry_run: bool, relative: bool = False) -> list[str]:
    argv = ["rsync", "-az"]
    if relative:
        argv.append("--relative")
    argv.extend(["--delete", *RSYNC_TRANSPORT_OPTIONS, "-e", rsync_ssh_command()])
    if dry_run:
        argv.extend(["--dry-run", "--itemize-changes"])
    else:
        argv.extend(["--progress", "--info=progress2", "--stats", "--human-readable"])
    return argv


def shell_command(argv: Iterable[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in argv)


def ssh_command_string(
    remote: str,
    command: str = "",
    *,
    tty: str = "",
    accept_new_host_key: bool = False,
) -> str:
    return shell_command(
        ssh_command(
            remote,
            command,
            tty=tty,
            accept_new_host_key=accept_new_host_key,
        )
    )


def rsync_ssh_command(*, accept_new_host_key: bool = False) -> str:
    return shell_command(["ssh", *ssh_options(accept_new_host_key=accept_new_host_key)])


def rsync_options() -> list[str]:
    return list(RSYNC_TRANSPORT_OPTIONS)
