"""GEN5 X5H board type adapter."""

from __future__ import annotations

import shlex

from components.board_types.src.base import BoardAction, BoardActionContext, BoardTypeAdapter
from components.config.api import accessors as config_accessors


class Gen5X5hBoardAdapter(BoardTypeAdapter):
    """Current built-in board workflow for GEN5 X5H over a board host."""

    type_id = "gen5_x5h"
    label = "GEN5 X5H"
    description = "GEN5 X5H board connected through a board host."

    def actions(self, _config: dict[str, object]) -> list[BoardAction]:
        return [
            BoardAction(
                "copy_build_artifacts",
                "Copy build artifacts",
                "Copy configured build target artifacts from the build host project checkout to the board host artifacts directory.",
                requires_remote=True,
                requires_project=True,
            ),
            BoardAction(
                "flash_bootloaders",
                "Flash bootloaders",
                "Deploy the bootloader flashing helper to the board host, enter flash mode, flash x5h_bootloaders.yaml, then switch the board to boot mode.",
            ),
            BoardAction(
                "flash_ufs_image",
                "Flash UFS image",
                "Deploy the UFS imager to the board host and flash artifacts/full_ufs.img.gz to UFS over /dev/GEN5_CONSOLE.",
            ),
        ]

    def action_commands(self, ctx: BoardActionContext, action_id: str) -> list[list[str]]:
        if action_id == "copy_build_artifacts":
            return ctx.transfer_service.copy_build_artifacts_commands(
                ctx.config,
                artifact_targets=ctx.artifact_targets,
                build_params=ctx.build_params or {},
            )
        if action_id == "flash_bootloaders":
            if ctx.flash_bootloaders_tool is None:
                raise ValueError("flash bootloader helper tool is not configured")
            return self.flash_bootloaders_command_plan(
                ctx,
                board_host=config_accessors.board_host_spec_for_config(ctx.config),
                work_dir=config_accessors.board_work_dir_for_config(ctx.config),
                artifacts_dir=config_accessors.board_artifacts_dir_for_config(ctx.config),
                tool=ctx.flash_bootloaders_tool,
            )
        if action_id == "flash_ufs_image":
            if ctx.xt_imager_tool is None:
                raise ValueError("UFS imager helper tool is not configured")
            return self.flash_ufs_command_plan(
                ctx,
                board_host=config_accessors.board_host_spec_for_config(ctx.config),
                work_dir=config_accessors.board_work_dir_for_config(ctx.config),
                artifacts_dir=config_accessors.board_artifacts_dir_for_config(ctx.config),
                console=config_accessors.board_console_device_for_config(ctx.config),
                loadaddr=config_accessors.board_ufs_loadaddr_for_config(ctx.config),
                buffersize=config_accessors.board_ufs_buffersize_for_config(ctx.config),
                tool=ctx.xt_imager_tool,
            )
        return super().action_commands(ctx, action_id)

    def flash_bootloaders_command_plan(
        self,
        ctx: BoardActionContext,
        *,
        board_host: str,
        work_dir: str,
        artifacts_dir: str,
        tool: object,
    ) -> list[list[str]]:
        builder = ctx.command_builder
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
        ctx: BoardActionContext,
        *,
        board_host: str,
        work_dir: str,
        artifacts_dir: str,
        console: str,
        loadaddr: str,
        buffersize: str,
        tool: object,
    ) -> list[list[str]]:
        builder = ctx.command_builder
        remote_tool = builder.board_tool_remote_path(work_dir, tool)
        helper_tool = self.ufs_helper_tool(ctx)
        remote_helper = builder.board_tool_remote_path(work_dir, helper_tool)
        extra_args = []
        if loadaddr:
            extra_args.extend(["--loadaddr", shlex.quote(loadaddr)])
        if buffersize:
            extra_args.extend(["--buffersize", shlex.quote(buffersize)])
        extra_text = " ".join(extra_args)
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
            f"python3 {builder.quote_remote_shell_path(remote_helper)} "
            f"--image \"$image\" --console \"$console\" "
            f"--tool {shlex.quote(builder.remote_shell_path(str(remote_tool)))} "
            f"{extra_text}\n"
        )
        return [
            builder.board_prepare_work_dir_command(board_host, artifacts_dir),
            builder.board_deploy_tool_command(board_host, work_dir, tool),
            builder.board_deploy_tool_command(board_host, work_dir, helper_tool),
            builder.board_ssh_command(board_host, script, tty=True),
        ]

    def ufs_helper_tool(self, ctx: BoardActionContext) -> object:
        if ctx.xt_imager_tool is None:
            raise ValueError("UFS imager helper tool is not configured")
        return ctx.xt_imager_tool.parent / "gen5_x5h_flash_ufs.py"
