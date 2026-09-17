"""Board flashing command service."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any


class BoardFlashCommandService:
    """Own board bootloader and UFS flashing command plans."""

    def __init__(self, *, command_builder: Any) -> None:
        self.command_builder = command_builder

    def flash_bootloaders_command_plan(
        self,
        *,
        board_host: str,
        work_dir: str,
        artifacts_dir: str,
        tool: Path,
    ) -> list[list[str]]:
        builder = self.command_builder
        remote_tool = builder.board_tool_remote_path(work_dir, tool)
        enter_flash_script = (
            "set -euo pipefail\n"
            f"cd {builder.quote_remote_shell_path(work_dir)}\n"
            "echo 'run: x5h_flash'\n"
            "x5h_flash\n"
            "echo 'done: x5h_flash'\n"
        )
        boot_archive_find = (
            f"archive=$(find {builder.quote_remote_shell_path(artifacts_dir)} -type f \\( "
            "-name '*boot-artifacts*.tar.bz2' -o -name '*boot_artifacts*.tar.bz2' -o "
            "-name '*boot-artifacts*.tar.gz' -o -name '*boot_artifacts*.tar.gz' -o "
            "-name '*boot-artifacts*.tar' -o -name '*boot_artifacts*.tar' \\) -print -quit)\n"
        )
        unpack_script = (
            "set -euo pipefail\n"
            f"cd {builder.quote_remote_shell_path(work_dir)}\n"
            f"{boot_archive_find}"
            "if [ -z \"$archive\" ]; then echo 'boot artifacts archive not found under artifacts' >&2; exit 2; fi\n"
            "archive_dir=$(dirname \"$archive\")\n"
            "archive_base=$(basename \"$archive\")\n"
            "artifact_name=${archive_base%.tar.bz2}\n"
            "artifact_name=${artifact_name%.tar.gz}\n"
            "artifact_name=${artifact_name%.tar}\n"
            "artifact_dir=\"$archive_dir/$artifact_name\"\n"
            "rm -rf \"$artifact_dir\"\n"
            "mkdir -p \"$artifact_dir\"\n"
            "echo 'unpack boot artifacts: '\"$archive\"\n"
            "echo 'to: '\"$artifact_dir\"\n"
            "tar -xf \"$archive\" -C \"$artifact_dir\" --strip-components=1\n"
            "ipls_dir=\"$artifact_dir/build-domd/ipls\"\n"
            "if [ ! -d \"$ipls_dir\" ]; then echo 'build-domd/ipls not found in unpacked boot artifacts: '\"$artifact_dir\" >&2; exit 2; fi\n"
            "config=\"$ipls_dir/x5h_bootloaders.yaml\"\n"
            "if [ ! -f \"$config\" ]; then echo 'x5h_bootloaders.yaml not found in: '\"$ipls_dir\" >&2; exit 2; fi\n"
            "echo 'ipls dir: '\"$ipls_dir\"\n"
            "echo 'config: '\"$config\"\n"
        )
        install_helper_script = (
            "set -euo pipefail\n"
            f"{boot_archive_find}"
            "if [ -z \"$archive\" ]; then echo 'boot artifacts archive not found under artifacts' >&2; exit 2; fi\n"
            "archive_dir=$(dirname \"$archive\")\n"
            "archive_base=$(basename \"$archive\")\n"
            "artifact_name=${archive_base%.tar.bz2}\n"
            "artifact_name=${artifact_name%.tar.gz}\n"
            "artifact_name=${artifact_name%.tar}\n"
            "ipls_dir=\"$archive_dir/$artifact_name/build-domd/ipls\"\n"
            "if [ ! -d \"$ipls_dir\" ]; then echo 'build-domd/ipls not found: '\"$ipls_dir\" >&2; exit 2; fi\n"
            "echo 'install bootloader flasher to: '\"$ipls_dir/flash_bootloaders.py\"\n"
            f"cp {builder.quote_remote_shell_path(remote_tool)} \"$ipls_dir/flash_bootloaders.py\"\n"
            "chmod +x \"$ipls_dir/flash_bootloaders.py\"\n"
        )
        run_flasher_script = (
            "set -euo pipefail\n"
            f"{boot_archive_find}"
            "if [ -z \"$archive\" ]; then echo 'boot artifacts archive not found under artifacts' >&2; exit 2; fi\n"
            "archive_dir=$(dirname \"$archive\")\n"
            "archive_base=$(basename \"$archive\")\n"
            "artifact_name=${archive_base%.tar.bz2}\n"
            "artifact_name=${artifact_name%.tar.gz}\n"
            "artifact_name=${artifact_name%.tar}\n"
            "ipls_dir=\"$archive_dir/$artifact_name/build-domd/ipls\"\n"
            "if [ ! -d \"$ipls_dir\" ]; then echo 'build-domd/ipls not found: '\"$ipls_dir\" >&2; exit 2; fi\n"
            "if [ ! -f \"$ipls_dir/x5h_bootloaders.yaml\" ]; then echo 'x5h_bootloaders.yaml not found in: '\"$ipls_dir\" >&2; exit 2; fi\n"
            "if [ ! -f \"$ipls_dir/flash_bootloaders.py\" ]; then echo 'flash_bootloaders.py not installed in: '\"$ipls_dir\" >&2; exit 2; fi\n"
            "cd \"$ipls_dir\"\n"
            "echo 'run bootloader flasher from: '\"$PWD\"\n"
            "PYTHONUNBUFFERED=1 python3 -u ./flash_bootloaders.py --port /dev/GEN5_CONSOLE --config x5h_bootloaders.yaml --mode all\n"
            "echo 'bootloader flasher done'\n"
            "echo 'run: x5h_boot'\n"
            "x5h_boot\n"
            "echo 'done: x5h_boot'\n"
        )
        return [
            builder.board_prepare_work_dir_command(board_host, artifacts_dir),
            builder.board_deploy_tool_command(board_host, work_dir, tool),
            builder.board_ssh_command(board_host, enter_flash_script, tty=True),
            builder.board_ssh_command(board_host, unpack_script, tty=True),
            builder.board_ssh_command(board_host, install_helper_script, tty=True),
            builder.board_ssh_command(board_host, run_flasher_script, tty=True),
        ]

    def flash_ufs_command_plan(
        self,
        *,
        board_host: str,
        work_dir: str,
        artifacts_dir: str,
        console: str,
        loadaddr: str,
        buffersize: str,
        tool: Path,
    ) -> list[list[str]]:
        builder = self.command_builder
        remote_tool = builder.board_tool_remote_path(work_dir, tool)
        extra_args = []
        if loadaddr:
            extra_args.extend(["--loadaddr", loadaddr])
        if buffersize:
            extra_args.extend(["--buffersize", buffersize])
        extra_json = json.dumps(extra_args)
        confirm_wrapper = r"""
import json
import os
import pty
import re
import select
import shlex
import subprocess
import sys

image = os.environ["XT_FLASH_IMAGE"]
console = os.environ["XT_FLASH_CONSOLE"]
tool = os.environ["XT_FLASH_TOOL"]
extra_args = json.loads(os.environ.get("XT_FLASH_EXTRA_ARGS", "[]"))
launcher = r'''
import importlib.util
import os
import sys
import time

tool = os.environ["XT_FLASH_TOOL"]
spec = importlib.util.spec_from_file_location("xt_imager_vendor", tool)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
original_wait = module.conn_wait_for_any

def drain_serial_tail(conn, duration=0.08):
    old_timeout = conn.timeout
    conn.timeout = 0.01
    deadline = time.monotonic() + duration
    try:
        while time.monotonic() < deadline:
            if not conn.read(4096):
                break
    finally:
        conn.timeout = old_timeout

def conn_wait_for_any(conn, expect):
    result = original_wait(conn, expect)
    if "=>" in expect:
        drain_serial_tail(conn)
    return result

module.conn_wait_for_any = conn_wait_for_any
sys.argv = [tool] + sys.argv[1:]
module.main()
'''
launcher_args = [
    "python3",
    "-c",
    launcher,
    "--target",
    "ufs",
    "-s",
    console,
    "-b",
    "1843200",
    *[str(arg) for arg in extra_args],
]
command = "zcat " + shlex.quote(image) + " | " + shlex.join(launcher_args)
master, slave = pty.openpty()
process = subprocess.Popen(
    ["bash", "-lc", command],
    stdin=slave,
    stdout=slave,
    stderr=slave,
    close_fds=True,
    start_new_session=True,
)
os.close(slave)
buffer = ""
confirmed = False
try:
    while True:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                data = os.read(master, 4096)
            except OSError:
                break
            if not data:
                break
            text = data.decode(errors="replace")
            sys.stdout.write(text)
            sys.stdout.flush()
            buffer = (buffer + text)[-4096:]
            if (
                not confirmed
                and "To continue, type exactly: FLASH UFS 1" in buffer
                and re.search(r">\s*$", buffer)
            ):
                os.write(master, b"FLASH UFS 1\r")
                confirmed = True
        if process.poll() is not None and not ready:
            break
finally:
    try:
        os.close(master)
    except OSError:
        pass
sys.exit(process.wait())
"""
        script = (
            "set -euo pipefail\n"
            f"cd {builder.quote_remote_shell_path(work_dir)}\n"
            f"image=$(find {builder.quote_remote_shell_path(artifacts_dir)} -name full_ufs.img.gz -print -quit)\n"
            "if [ -z \"$image\" ]; then echo 'full_ufs.img.gz not found under artifacts' >&2; exit 2; fi\n"
            f"console={shlex.quote(console)}\n"
            "if [ -z \"$console\" ]; then console=$(ls -1 /dev/GEN5_CONSOLE* 2>/dev/null | head -n 1 || true); fi\n"
            "if [ -z \"$console\" ]; then echo 'GEN5 console device not found under /dev/GEN5_CONSOLE*' >&2; exit 2; fi\n"
            "echo 'flash UFS image: '\"$image\"\n"
            "echo 'GEN5 console: '\"$console\"\n"
            "echo 'board power: x5h_off'\n"
            "x5h_off\n"
            "sleep 1\n"
            "echo 'board power: x5h_on'\n"
            "x5h_on\n"
            "sleep 1\n"
            "echo 'board boot mode: x5h_boot'\n"
            "x5h_boot\n"
            "echo 'board power after boot mode: x5h_off'\n"
            "x5h_off\n"
            "sleep 1\n"
            "echo 'board power after boot mode: x5h_on'\n"
            "x5h_on\n"
            "sleep 1\n"
            "echo 'board console: drain stale output before xt-imager'\n"
            "python3 - \"$console\" <<'PY'\n"
            "import serial\n"
            "import sys\n"
            "import time\n"
            "\n"
            "deadline = time.monotonic() + 1.0\n"
            "conn = serial.Serial(port=sys.argv[1], baudrate=1843200, timeout=0.05)\n"
            "try:\n"
            "    while time.monotonic() < deadline:\n"
            "        conn.read(4096)\n"
            "finally:\n"
            "    conn.close()\n"
            "PY\n"
            "echo 'board console: start xt-imager'\n"
            f"export XT_FLASH_TOOL={shlex.quote(builder.remote_shell_path(str(remote_tool)))}\n"
            "export XT_FLASH_IMAGE=\"$image\"\n"
            "export XT_FLASH_CONSOLE=\"$console\"\n"
            f"export XT_FLASH_EXTRA_ARGS={shlex.quote(extra_json)}\n"
            f"python3 -c {shlex.quote(confirm_wrapper)}\n"
        )
        return [
            builder.board_prepare_work_dir_command(board_host, artifacts_dir),
            builder.board_deploy_tool_command(board_host, work_dir, tool),
            builder.board_ssh_command(board_host, script, tty=True),
        ]


def board_flash_command_service(*, command_builder: Any) -> BoardFlashCommandService:
    return BoardFlashCommandService(command_builder=command_builder)
