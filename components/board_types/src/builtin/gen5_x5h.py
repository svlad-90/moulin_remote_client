"""GEN5 X5H board type adapter."""

from __future__ import annotations

import shlex

from components.board_types.src.base import BoardAction, BoardActionContext, BoardTypeAdapter
from components.config.api import accessors as config_accessors
from components.remote.api import transport


class Gen5X5hBoardAdapter(BoardTypeAdapter):
    """Current built-in board workflow for GEN5 X5H over a board host."""

    type_id = "gen5_x5h"
    label = "GEN5 X5H"
    description = "GEN5 X5H board connected through a board host."

    def rsync_progress_args(self, *, sparse: bool = False) -> list[str]:
        argv = ["rsync", "-az"]
        if sparse:
            argv[-1] += "S"
            argv.extend(["--inplace"])
        argv.extend([*transport.rsync_options(), "--info=progress2", "--stats", "--human-readable"])
        return argv

    def rsync_progress_shell_prefix(self, *, sparse: bool = False, accept_new_host_key: bool = False) -> str:
        return transport.shell_command(
            [
                *self.rsync_progress_args(sparse=sparse),
                "-e",
                transport.rsync_ssh_command(accept_new_host_key=accept_new_host_key),
            ]
        )

    def stream_file_with_progress_script(self, file_expr: str, label: str) -> str:
        python_script = r"""
import os
import sys
import time

path = os.environ["MOULIN_STREAM_FILE"]
label = os.environ.get("MOULIN_STREAM_LABEL", "stream")
total = max(1, os.path.getsize(path))
copied = 0
last_reported = -1
last_time = 0.0
with open(path, "rb") as handle:
    while True:
        chunk = handle.read(1024 * 1024)
        if not chunk:
            break
        sys.stdout.buffer.write(chunk)
        copied += len(chunk)
        now = time.monotonic()
        pct = min(100, int(copied * 100 / total))
        if pct != last_reported and (pct == 100 or now - last_time >= 1.0):
            print(f"progress: {pct}% ({copied}/{total} bytes) {label}", file=sys.stderr, flush=True)
            last_reported = pct
            last_time = now
sys.stdout.buffer.flush()
"""
        return (
            f"MOULIN_STREAM_FILE={file_expr} "
            f"MOULIN_STREAM_LABEL={shlex.quote(label)} "
            f"python3 -c {shlex.quote(python_script)}\n"
        )

    def actions(self, _config: dict[str, object]) -> list[BoardAction]:
        return [
            BoardAction(
                "open_board_host_shell",
                "Open board host shell",
                "Open SSH shell on the board host; exit returns to this TUI.",
                allow_during_job=True,
                interactive=True,
            ),
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
            BoardAction(
                "restart_board",
                "Restart board",
                "Power-cycle the GEN5 X5H board on the board host and leave it in boot mode.",
                confirm=True,
            ),
            BoardAction(
                "open_board_serial_console",
                "Open board serial console",
                "Open picocom on the configured board serial console without changing board power state.",
                interactive=True,
                allow_during_job=True,
            ),
            BoardAction(
                "open_uboot_console",
                "Open U-Boot console",
                "Power-cycle the board, enter boot mode, then open picocom so U-Boot autoboot can be stopped interactively.",
                interactive=True,
                allow_during_job=True,
            ),
            BoardAction(
                "deploy_network_boot",
                "Deploy TFTP boot artifacts",
                "Initial or refreshed network-boot deploy: copy GEN5 boot artifacts from the build host into the board-host TFTP project directory and update the current symlink.",
                requires_remote=True,
                requires_project=True,
            ),
            BoardAction(
                "deploy_network_domd_rootfs",
                "Deploy DomD NFS rootfs",
                "Initial or refreshed network-boot deploy: copy the DomD rootfs artifact to the board host, extract it into the NFS project directory, and update the current symlink.",
                requires_remote=True,
                requires_project=True,
            ),
            BoardAction(
                "deploy_network_android",
                "Deploy Android image to NFS",
                "Initial or refreshed network-boot deploy: copy android_only.img from the build host into the board-host NFS project directory and update the current symlink.",
                requires_remote=True,
                requires_project=True,
            ),
            BoardAction(
                "deploy_network_full",
                "Deploy full TFTP/NFS set",
                "First step for a full network-boot setup: deploy TFTP boot artifacts, DomD NFS rootfs, and Android image for the active project.",
                requires_remote=True,
                requires_project=True,
            ),
            BoardAction(
                "install_nfs_deploy_helper",
                "Install NFS deploy helper",
                "One-time interactive board-host setup: install the root-owned NFS rootfs deploy helper and sudoers rule.",
                requires_project=True,
                interactive=True,
            ),
            BoardAction(
                "pull_network_workspace",
                "Pull TFTP/NFS workspace",
                "Before file-level edits: mirror the active board-host TFTP/NFS project directories into workspace/board-network.",
                requires_project=True,
            ),
            BoardAction(
                "push_network_workspace",
                "Push TFTP/NFS workspace",
                "After file-level edits: push workspace/board-network TFTP/NFS changes back to the active board-host project directories.",
                requires_project=True,
            ),
            BoardAction(
                "pull_dom0_initramfs_workspace",
                "Pull Dom0 initramfs workspace",
                "Before Dom0 initramfs edits: copy TFTP uInitramfs locally and unpack it into workspace/board-network.",
                requires_project=True,
            ),
            BoardAction(
                "push_dom0_initramfs_workspace",
                "Push Dom0 initramfs workspace",
                "After Dom0 initramfs edits: repack the local workspace, push uInitramfs to TFTP, and update the current symlink.",
                requires_project=True,
            ),
            BoardAction(
                "apply_uboot_network_env",
                "Apply U-Boot network env",
                "Board setup step: send GEN5 TFTP/NFS boot environment commands over the configured board serial console.",
                requires_project=True,
            ),
            BoardAction(
                "apply_uboot_ufs_env",
                "Apply U-Boot UFS env",
                "Board setup step: restore U-Boot bootcmd to boot the flashed UFS image set.",
            ),
        ]

    def action_commands(self, ctx: BoardActionContext, action_id: str) -> list[list[str]]:
        if action_id == "copy_build_artifacts":
            return ctx.transfer_service.copy_build_artifacts_commands(
                ctx.config,
                artifact_targets=ctx.artifact_targets,
                build_params=ctx.build_params or {},
            )
        if action_id == "open_board_host_shell":
            return [ctx.command_builder.board_ssh_command(config_accessors.board_host_spec_for_config(ctx.config), "exec bash -l", tty=True)]
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
        if action_id == "restart_board":
            return self.restart_board_command_plan(ctx)
        if action_id == "open_board_serial_console":
            return self.open_board_serial_console_command_plan(ctx)
        if action_id == "open_uboot_console":
            return self.open_uboot_console_command_plan(ctx)
        if action_id == "deploy_network_boot":
            return self.deploy_network_boot_command_plan(ctx)
        if action_id == "deploy_network_domd_rootfs":
            return self.deploy_network_domd_rootfs_command_plan(ctx)
        if action_id == "deploy_network_android":
            return self.deploy_network_android_command_plan(ctx)
        if action_id == "deploy_network_full":
            return (
                self.deploy_network_boot_command_plan(ctx)
                + self.deploy_network_domd_rootfs_command_plan(ctx)
                + self.deploy_network_android_command_plan(ctx)
            )
        if action_id == "install_nfs_deploy_helper":
            return self.install_nfs_deploy_helper_command_plan(ctx)
        if action_id == "pull_network_workspace":
            return self.pull_network_workspace_command_plan(ctx)
        if action_id == "push_network_workspace":
            return self.push_network_workspace_command_plan(ctx)
        if action_id == "pull_dom0_initramfs_workspace":
            return self.pull_dom0_initramfs_workspace_command_plan(ctx)
        if action_id == "push_dom0_initramfs_workspace":
            return self.push_dom0_initramfs_workspace_command_plan(ctx)
        if action_id == "apply_uboot_network_env":
            return self.apply_uboot_network_env_command_plan(ctx)
        if action_id == "apply_uboot_ufs_env":
            return self.apply_uboot_ufs_env_command_plan(ctx)
        return super().action_commands(ctx, action_id)

    def nfs_deploy_helper_path(self) -> str:
        return "/usr/local/sbin/moulin-deploy-rootfs"

    def nfs_deploy_helper_script(self) -> str:
        return """#!/bin/sh
set -eu

dest=${1:?dest is required}
if [ "$dest" = "--check" ]; then
  exit 0
fi

if [ "$dest" = "--prepare" ]; then
  dest=${2:?dest is required}
  user=${3:?user is required}
  case "$dest" in
    /srv/nfs/*) ;;
    *) echo "refuse dest outside /srv/nfs: $dest" >&2; exit 2 ;;
  esac
  mkdir -p "$dest"
  chown "$user:" "$dest"
  exit 0
fi

if [ "$dest" = "--prepare-android" ]; then
  dest=${2:?dest is required}
  user=${3:?user is required}
  case "$dest" in
    /srv/nfs/*) ;;
    *) echo "refuse dest outside /srv/nfs: $dest" >&2; exit 2 ;;
  esac
  mkdir -p "$dest"
  : > "$dest/.moulin-android_only.img"
  chown "$user:" "$dest/.moulin-android_only.img"
  chmod 0644 "$dest/.moulin-android_only.img"
  exit 0
fi

if [ "$dest" = "--install-android" ]; then
  dest=${2:?dest is required}
  image=${3:?image is required}
  case "$dest" in
    /srv/nfs/*) ;;
    *) echo "refuse dest outside /srv/nfs: $dest" >&2; exit 2 ;;
  esac
  case "$image" in
    "$dest"/.moulin-android_only.img) ;;
    *) echo "refuse unexpected android image path: $image" >&2; exit 2 ;;
  esac
  [ -f "$image" ] || { echo "android image not found: $image" >&2; exit 2; }
  mv -f "$image" "$dest/android_only.img"
  chown root:root "$dest/android_only.img"
  chmod 0644 "$dest/android_only.img"
  exit 0
fi

tarball=${2:?tarball is required}

case "$dest" in
  /srv/nfs/*) ;;
  *) echo "refuse dest outside /srv/nfs: $dest" >&2; exit 2 ;;
esac

case "$tarball" in
  "$dest"/.moulin-domd-rootfs.tar.bz2) ;;
  *) echo "refuse unexpected tarball path: $tarball" >&2; exit 2 ;;
esac

[ -f "$tarball" ] || { echo "rootfs tarball not found: $tarball" >&2; exit 2; }

echo "rootfs deploy: cleaning old NFS rootfs under $dest" >&2
find "$dest" -mindepth 1 -maxdepth 1 ! -name '.moulin-domd-rootfs.tar.bz2' ! -name 'android_only.img' -exec rm -rf {} +
echo "rootfs deploy: extracting $tarball into $dest" >&2
tar --numeric-owner --same-owner -xjf "$tarball" -C "$dest"
echo "rootfs deploy: preparing Xen log directories" >&2
mkdir -p "$dest/var/volatile/log/xen"
chmod 755 "$dest/var/volatile" "$dest/var/volatile/log" "$dest/var/volatile/log/xen"
echo "rootfs deploy: removing uploaded tarball" >&2
rm -f "$tarball"
echo "rootfs deploy: done" >&2
"""

    def install_nfs_deploy_helper_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        paths = self.network_paths(ctx)
        helper = self.nfs_deploy_helper_path()
        sudoers_line = f"{paths['board_user']} ALL=(root) NOPASSWD: {helper}"
        install_script = (
            "set -e\n"
            "tmp=$(mktemp)\n"
            "cleanup() { rm -f \"$tmp\"; }\n"
            "trap cleanup EXIT\n"
            "cat > \"$tmp\" <<'MOULIN_HELPER'\n"
            f"{self.nfs_deploy_helper_script()}"
            "MOULIN_HELPER\n"
            f"sudo install -o root -g root -m 0755 \"$tmp\" {shlex.quote(helper)}\n"
            f"printf '%s\\n' {shlex.quote(sudoers_line)} | sudo tee /etc/sudoers.d/moulin-rootfs-deploy >/dev/null\n"
            "sudo chmod 0440 /etc/sudoers.d/moulin-rootfs-deploy\n"
            "sudo visudo -cf /etc/sudoers.d/moulin-rootfs-deploy\n"
            "echo 'NFS deploy helper installed.'\n"
        )
        return [
            [
                "ssh",
                "-tt",
                paths["board_host"],
                "bash -lc " + shlex.quote(install_script),
            ],
        ]

    def network_paths(self, ctx: BoardActionContext) -> dict[str, str]:
        return {
            "project": config_accessors.network_deploy_project_name_for_config(ctx.config),
            "build_host": config_accessors.remote_spec_for_config(ctx.config),
            "board_host": config_accessors.board_host_spec_for_config(ctx.config),
            "board_user": config_accessors.board_host_user_for_config(ctx.config),
            "remote_project": config_accessors.remote_project_dir_for_config(ctx.config),
            "tftp_project": config_accessors.board_tftp_project_dir_for_config(ctx.config),
            "nfs_project": config_accessors.board_nfs_project_dir_for_config(ctx.config),
            "tftp_current": config_accessors.board_tftp_current_dir_for_config(ctx.config),
            "nfs_current": config_accessors.board_nfs_current_dir_for_config(ctx.config),
            "server_ip": config_accessors.board_server_ip_for_config(ctx.config),
            "board_ip": config_accessors.board_ipaddr_for_config(ctx.config),
            "console": config_accessors.board_console_device_for_config(ctx.config),
        }

    def refresh_current_symlinks_script(self, ctx: BoardActionContext) -> str:
        builder = ctx.command_builder
        paths = self.network_paths(ctx)
        tftp_base = config_accessors.board_network_base_dir(
            config_accessors.board_tftp_root_for_config(ctx.config),
            config_accessors.board_deploy_subdir_for_config(ctx.config),
        )
        nfs_base = config_accessors.board_network_base_dir(
            config_accessors.board_nfs_root_for_config(ctx.config),
            config_accessors.board_deploy_subdir_for_config(ctx.config),
        )
        return (
            f"mkdir -p {builder.quote_remote_shell_path(tftp_base)} {builder.quote_remote_shell_path(nfs_base)}\n"
            f"ln -sfn {shlex.quote(paths['project'])} {builder.quote_remote_shell_path(paths['tftp_current'])}\n"
            f"ln -sfn {shlex.quote(paths['project'])} {builder.quote_remote_shell_path(paths['nfs_current'])}\n"
            f"echo 'TFTP current -> {paths['project']}'\n"
            f"echo 'NFS current -> {paths['project']}'\n"
        )

    def deploy_network_boot_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        builder = ctx.command_builder
        paths = self.network_paths(ctx)
        tftp_project = paths["tftp_project"]
        rsync_target = f"{paths['board_host']}:{tftp_project.rstrip('/')}/"
        prepare_board_script = (
            "set -euo pipefail\n"
            f"mkdir -p {builder.quote_remote_shell_path(tftp_project)}\n"
        )
        refresh_board_script = "set -euo pipefail\n" + self.refresh_current_symlinks_script(ctx)
        build_script = (
            "set -euo pipefail\n"
            "echo 'Deploy TFTP boot artifacts' >&2\n"
            f"echo 'from: {paths['build_host']}:{paths['remote_project']}' >&2\n"
            f"echo 'to:   {paths['board_host']}:{paths['tftp_project']}' >&2\n"
            f"src={shlex.quote(paths['remote_project'])}\n"
            "search_roots=(\"$src\")\n"
            "[ -d \"$src/artifacts\" ] && search_roots=(\"$src/artifacts\" \"$src\")\n"
            "archive=$(find \"${search_roots[@]}\" -maxdepth 3 -type f \\( "
            "-name '*boot-artifacts*.tar.bz2' -o -name '*boot_artifacts*.tar.bz2' -o "
            "-name '*boot-artifacts*.tar.gz' -o -name '*boot_artifacts*.tar.gz' -o "
            "-name '*boot-artifacts*.tar' -o -name '*boot_artifacts*.tar' \\) -print -quit 2>/dev/null)\n"
            "if [ -z \"$archive\" ]; then echo 'boot artifacts archive not found under build project' >&2; exit 2; fi\n"
            "tmp=$(mktemp -d)\n"
            "cleanup() { rm -rf \"$tmp\"; }\n"
            "trap cleanup EXIT\n"
            "tar -xf \"$archive\" -C \"$tmp\"\n"
            "root=$(find \"$tmp\" -type d -name build-dom0 -print -quit)\n"
            "if [ -z \"$root\" ]; then echo 'build-dom0 not found in boot artifacts archive' >&2; exit 2; fi\n"
            "domd=$(find \"$tmp\" -type d -name build-domd -print -quit)\n"
            "if [ -z \"$domd\" ]; then echo 'build-domd not found in boot artifacts archive' >&2; exit 2; fi\n"
            "out=\"$tmp/out\"\n"
            "mkdir -p \"$out\"\n"
            "cp -v \"$root/Image\" \"$root/uInitramfs\" \"$out/\" >&2\n"
            "cp -v \"$domd/r8a78000-ironhide-xen.dtb\" \"$domd/xen-ironhide.uImage\" \"$domd/xenpolicy-ironhide\" \"$out/\" >&2\n"
            f"{transport.ssh_command_string(paths['board_host'], prepare_board_script, accept_new_host_key=True)}\n"
            f"{self.rsync_progress_shell_prefix(accept_new_host_key=True)} "
            f"\"$out\"/ {shlex.quote(rsync_target)}\n"
            f"{transport.ssh_command_string(paths['board_host'], refresh_board_script, accept_new_host_key=True)}\n"
        )
        return [
            transport.ssh_command(paths["build_host"], "bash -lc " + shlex.quote(build_script)),
        ]

    def deploy_network_domd_rootfs_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        builder = ctx.command_builder
        paths = self.network_paths(ctx)
        nfs_project = paths["nfs_project"]
        helper = self.nfs_deploy_helper_path()
        remote_tarball = f"{nfs_project.rstrip('/')}/.moulin-domd-rootfs.tar.bz2"
        rsync_target = f"{paths['board_host']}:{remote_tarball}"
        prepare_board_script = (
            "set -euo pipefail\n"
            f"sudo -n {shlex.quote(helper)} --check || {{ echo 'Install NFS deploy helper first.' >&2; exit 2; }}\n"
            f"sudo -n {shlex.quote(helper)} --prepare {builder.quote_remote_shell_path(nfs_project)} {shlex.quote(paths['board_user'])}\n"
        )
        extract_board_script = (
            "set -euo pipefail\n"
            f"dest={builder.quote_remote_shell_path(nfs_project)}\n"
            f"tarball={builder.quote_remote_shell_path(remote_tarball)}\n"
            "echo 'Installing DomD rootfs on board host...' >&2\n"
            f"sudo -n {shlex.quote(helper)} \"$dest\" \"$tarball\"\n"
            "echo 'Refreshing NFS current symlinks...' >&2\n"
            f"{self.refresh_current_symlinks_script(ctx)}"
        )
        rootfs_lookup_script = (
            "set -euo pipefail\n"
            f"cd {shlex.quote(paths['remote_project'])}\n"
            "search_roots=()\n"
            "[ -d yocto/build-domd/tmp/deploy/images ] && search_roots+=(yocto/build-domd/tmp/deploy/images)\n"
            "[ -d artifacts ] && search_roots+=(artifacts)\n"
            "if [ \"${#search_roots[@]}\" -eq 0 ]; then echo 'DomD rootfs search directories not found' >&2; exit 2; fi\n"
            "rootfs=$(find \"${search_roots[@]}\" -type f "
            "\\( -name 'rcar-image-adas-x5h.tar.bz2' -o -name 'rcar-image-adas-*.tar.bz2' \\) -print -quit 2>/dev/null)\n"
            "if [ -z \"$rootfs\" ]; then echo 'DomD rootfs tarball not found' >&2; exit 2; fi\n"
        )
        validate_script = rootfs_lookup_script + "echo 'found DomD rootfs tarball: '\"$rootfs\" >&2\n"
        build_script = (
            rootfs_lookup_script +
            "echo 'Deploy DomD NFS rootfs' >&2\n"
            f"echo 'from: {paths['build_host']}:{paths['remote_project']}/yocto/build-domd/tmp/deploy/images' >&2\n"
            f"echo 'to:   {paths['board_host']}:{paths['nfs_project']}' >&2\n"
            "echo 'rsync rootfs tarball: '\"$rootfs\" >&2\n"
            "rootfs_bytes=$(stat -c%s \"$rootfs\")\n"
            "printf 'rootfs tarball size: %s bytes\\n' \"$rootfs_bytes\" >&2\n"
            f"{transport.ssh_command_string(paths['board_host'], prepare_board_script, accept_new_host_key=True)}\n"
            f"{self.rsync_progress_shell_prefix(accept_new_host_key=True)} "
            f"\"$rootfs\" {shlex.quote(rsync_target)}\n"
            "echo 'Rootfs tarball uploaded; starting board-host install...' >&2\n"
            f"{transport.ssh_command_string(paths['board_host'], extract_board_script, accept_new_host_key=True)}\n"
        )
        return [
            transport.ssh_command(paths["build_host"], "bash -lc " + shlex.quote(validate_script)),
            transport.ssh_command(paths["build_host"], "bash -lc " + shlex.quote(build_script)),
        ]

    def deploy_network_android_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        builder = ctx.command_builder
        paths = self.network_paths(ctx)
        nfs_project = paths["nfs_project"]
        helper = self.nfs_deploy_helper_path()
        upload_image = f"{nfs_project.rstrip('/')}/.moulin-android_only.img"
        rsync_target = f"{paths['board_host']}:{upload_image}"
        prepare_board_script = (
            "set -euo pipefail\n"
            f"sudo -n {shlex.quote(helper)} --check || {{ echo 'Install NFS deploy helper first.' >&2; exit 2; }}\n"
            f"sudo -n {shlex.quote(helper)} --prepare-android {builder.quote_remote_shell_path(nfs_project)} {shlex.quote(paths['board_user'])}\n"
        )
        install_board_script = (
            "set -euo pipefail\n"
            f"sudo -n {shlex.quote(helper)} --install-android "
            f"{builder.quote_remote_shell_path(nfs_project)} {builder.quote_remote_shell_path(upload_image)}\n"
        )
        refresh_board_script = "set -euo pipefail\n" + self.refresh_current_symlinks_script(ctx)
        build_script = (
            "set -euo pipefail\n"
            "echo 'Deploy Android image to NFS' >&2\n"
            f"echo 'from: {paths['build_host']}:{paths['remote_project']}/android_only.img' >&2\n"
            f"echo 'to:   {paths['board_host']}:{paths['nfs_project']}/android_only.img' >&2\n"
            f"cd {shlex.quote(paths['remote_project'])}\n"
            "image=$(find . -maxdepth 4 -type f -name android_only.img -print -quit)\n"
            "if [ -z \"$image\" ]; then echo 'android_only.img not found under build project' >&2; exit 2; fi\n"
            "echo 'rsync android image: '\"$image\" >&2\n"
            "image_bytes=$(stat -c%s \"$image\")\n"
            "image_disk_bytes=$(du -sb \"$image\" | awk '{print $1}')\n"
            "printf 'android image apparent size: %s bytes\\n' \"$image_bytes\" >&2\n"
            "printf 'android image disk usage: %s bytes\\n' \"$image_disk_bytes\" >&2\n"
            f"{transport.ssh_command_string(paths['board_host'], prepare_board_script, accept_new_host_key=True)}\n"
            f"{self.rsync_progress_shell_prefix(sparse=True, accept_new_host_key=True)} "
            f"\"$image\" {shlex.quote(rsync_target)}\n"
            f"{transport.ssh_command_string(paths['board_host'], install_board_script, accept_new_host_key=True)}\n"
            f"{transport.ssh_command_string(paths['board_host'], refresh_board_script, accept_new_host_key=True)}\n"
        )
        return [
            transport.ssh_command(paths["build_host"], "bash -lc " + shlex.quote(build_script)),
        ]

    def pull_network_workspace_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        builder = ctx.command_builder
        paths = self.network_paths(ctx)
        if ctx.app_dir is None:
            return [builder.local_log_command("Application directory is not configured", exit_code=1)]
        local_tftp = config_accessors.local_board_network_dir(ctx.config, ctx.app_dir, "tftp")
        local_nfs = config_accessors.local_board_network_dir(ctx.config, ctx.app_dir, "nfs")
        return [
            [
                "bash",
                "-lc",
                "set -euo pipefail\n"
                "echo 'Pull TFTP/NFS workspace' >&2\n"
                f"echo 'TFTP: {paths['board_host']}:{paths['tftp_project']} -> {local_tftp}' >&2\n"
                f"echo 'NFS:  {paths['board_host']}:{paths['nfs_project']} -> {local_nfs}' >&2\n"
                f"mkdir -p {shlex.quote(str(local_tftp))} {shlex.quote(str(local_nfs))}",
            ],
            [
                *self.rsync_progress_args(),
                "-e",
                transport.rsync_ssh_command(),
                f"{paths['board_host']}:{paths['tftp_project'].rstrip('/')}/",
                f"{local_tftp}/",
            ],
            [
                *self.rsync_progress_args(),
                "-e",
                transport.rsync_ssh_command(),
                f"{paths['board_host']}:{paths['nfs_project'].rstrip('/')}/",
                f"{local_nfs}/",
            ],
        ]

    def push_network_workspace_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        builder = ctx.command_builder
        paths = self.network_paths(ctx)
        if ctx.app_dir is None:
            return [builder.local_log_command("Application directory is not configured", exit_code=1)]
        local_tftp = config_accessors.local_board_network_dir(ctx.config, ctx.app_dir, "tftp")
        local_nfs = config_accessors.local_board_network_dir(ctx.config, ctx.app_dir, "nfs")
        setup_script = (
            "set -euo pipefail\n"
            "echo 'Push TFTP/NFS workspace' >&2\n"
            f"echo 'TFTP: {local_tftp} -> {paths['board_host']}:{paths['tftp_project']}' >&2\n"
            f"echo 'NFS:  {local_nfs} -> {paths['board_host']}:{paths['nfs_project']}' >&2\n"
            f"mkdir -p {builder.quote_remote_shell_path(paths['tftp_project'])} {builder.quote_remote_shell_path(paths['nfs_project'])}\n"
            f"{self.refresh_current_symlinks_script(ctx)}"
        )
        return [
            builder.board_ssh_command(paths["board_host"], setup_script),
            [
                *self.rsync_progress_args(),
                "--delete",
                "-e",
                transport.rsync_ssh_command(),
                f"{local_tftp}/",
                f"{paths['board_host']}:{paths['tftp_project'].rstrip('/')}/",
            ],
            [
                *self.rsync_progress_args(),
                "--delete",
                "-e",
                transport.rsync_ssh_command(),
                f"{local_nfs}/",
                f"{paths['board_host']}:{paths['nfs_project'].rstrip('/')}/",
            ],
        ]

    def pull_dom0_initramfs_workspace_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        paths = self.network_paths(ctx)
        if ctx.app_dir is None:
            return [ctx.command_builder.local_log_command("Application directory is not configured", exit_code=1)]
        local_dir = config_accessors.local_board_network_dir(ctx.config, ctx.app_dir, "dom0-initramfs")
        image = local_dir / "uInitramfs"
        payload = local_dir / "initramfs.cpio.gz"
        rootfs = local_dir / "rootfs"
        prepare_script = (
            "set -euo pipefail\n"
            "echo 'Pull Dom0 initramfs workspace' >&2\n"
            f"echo 'from: {paths['board_host']}:{paths['tftp_project'].rstrip('/')}/uInitramfs' >&2\n"
            f"echo 'to:   {rootfs}' >&2\n"
            f"mkdir -p {shlex.quote(str(local_dir))}\n"
        )
        unpack_script = (
            "set -euo pipefail\n"
            f"work={shlex.quote(str(local_dir))}\n"
            f"image={shlex.quote(str(image))}\n"
            f"payload={shlex.quote(str(payload))}\n"
            f"rootfs={shlex.quote(str(rootfs))}\n"
            "mkdir -p \"$work\" \"$rootfs\"\n"
            "find \"$rootfs\" -mindepth 1 -maxdepth 1 -exec rm -rf {} +\n"
            "if command -v dumpimage >/dev/null 2>&1; then\n"
            "  dumpimage -T ramdisk -p 0 -o \"$payload\" \"$image\"\n"
            "else\n"
            "  echo 'dumpimage not found; assuming legacy U-Boot image with 64-byte header' >&2\n"
            "  dd if=\"$image\" of=\"$payload\" bs=64 skip=1 status=none\n"
            "fi\n"
            "if gzip -t \"$payload\" >/dev/null 2>&1; then\n"
            "  gzip -dc \"$payload\" | (cd \"$rootfs\" && cpio -idmu --no-absolute-filenames)\n"
            "else\n"
            "  (cd \"$rootfs\" && cpio -idmu --no-absolute-filenames) < \"$payload\"\n"
            "fi\n"
            "printf 'Dom0 initramfs workspace: %s\\n' \"$rootfs\"\n"
        )
        return [
            ["bash", "-lc", prepare_script],
            [
                *self.rsync_progress_args(),
                "-e",
                transport.rsync_ssh_command(),
                f"{paths['board_host']}:{paths['tftp_project'].rstrip('/')}/uInitramfs",
                str(image),
            ],
            ["bash", "-lc", unpack_script],
        ]

    def push_dom0_initramfs_workspace_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        builder = ctx.command_builder
        paths = self.network_paths(ctx)
        if ctx.app_dir is None:
            return [builder.local_log_command("Application directory is not configured", exit_code=1)]
        local_dir = config_accessors.local_board_network_dir(ctx.config, ctx.app_dir, "dom0-initramfs")
        image = local_dir / "uInitramfs"
        payload = local_dir / "initramfs.cpio.gz"
        rootfs = local_dir / "rootfs"
        pack_script = (
            "set -euo pipefail\n"
            "echo 'Push Dom0 initramfs workspace' >&2\n"
            f"echo 'from: {rootfs}' >&2\n"
            f"echo 'to:   {paths['board_host']}:{paths['tftp_project'].rstrip('/')}/uInitramfs' >&2\n"
            "command -v mkimage >/dev/null 2>&1 || { echo 'mkimage not found; install u-boot-tools' >&2; exit 2; }\n"
            "command -v cpio >/dev/null 2>&1 || { echo 'cpio not found' >&2; exit 2; }\n"
            f"rootfs={shlex.quote(str(rootfs))}\n"
            f"payload={shlex.quote(str(payload))}\n"
            f"image={shlex.quote(str(image))}\n"
            "[ -d \"$rootfs\" ] || { echo 'Dom0 initramfs rootfs workspace not found' >&2; exit 2; }\n"
            "(cd \"$rootfs\" && find . -print0 | LC_ALL=C sort -z | cpio --null -o --format=newc) | gzip -n > \"$payload\"\n"
            "mkimage -A arm64 -O linux -T ramdisk -C gzip -n 'Dom0 initramfs' -d \"$payload\" \"$image\"\n"
            "printf 'rebuilt Dom0 initramfs: %s\\n' \"$image\"\n"
        )
        setup_script = (
            "set -euo pipefail\n"
            f"mkdir -p {builder.quote_remote_shell_path(paths['tftp_project'])}\n"
            f"{self.refresh_current_symlinks_script(ctx)}"
        )
        return [
            ["bash", "-lc", pack_script],
            builder.board_ssh_command(paths["board_host"], setup_script),
            [
                *self.rsync_progress_args(),
                "-e",
                transport.rsync_ssh_command(),
                str(image),
                f"{paths['board_host']}:{paths['tftp_project'].rstrip('/')}/uInitramfs",
            ],
        ]

    def uboot_network_env_lines(self, ctx: BoardActionContext) -> list[str]:
        paths = self.network_paths(ctx)
        tftp_root = config_accessors.board_tftp_root_for_config(ctx.config).rstrip("/")
        tftp_current = paths["tftp_current"].rstrip("/")
        if tftp_current.startswith(tftp_root + "/"):
            tftp_prefix = tftp_current[len(tftp_root) + 1 :]
        else:
            tftp_prefix = tftp_current.lstrip("/")
        lines = []
        if paths["board_ip"]:
            lines.append(f"setenv ipaddr {paths['board_ip']}")
        if paths["server_ip"]:
            lines.append(f"setenv serverip {paths['server_ip']}")
            lines.append(f"setenv serveraddr {paths['server_ip']}")
        lines.extend(
            [
                "setenv fdt_high 0xffffffffffffffff",
                "setenv bootm_size 0x10000000",
                "setenv i2c_pci 'i2c dev 0; i2c mw 0x77 0x06 0x00; i2c mw 0x77 0x02 0x14; i2c mw 0x77 0x04 0x00; i2c mw 0x77 0x01 0xff'",
                f"setenv nfs_domd_dir {paths['nfs_current']}",
                f"setenv tftp_dtb_load 'tftp 0x54000000 {tftp_prefix}/r8a78000-ironhide-xen.dtb && fdt addr 0x54000000 && fdt resize && fdt mknode / boot_dev && run tftp_configure_nfs'",
                f"setenv tftp_initramfs_load 'tftp 0x50000000 {tftp_prefix}/uInitramfs'",
                f"setenv tftp_kernel_load 'tftp 0x64000000 {tftp_prefix}/Image'",
                f"setenv tftp_xen_load 'tftp 0x54080000 {tftp_prefix}/xen-ironhide.uImage'",
                f"setenv tftp_xenpolicy_load 'tftp 0x53000000 {tftp_prefix}/xenpolicy-ironhide'",
                "setenv tftp_configure_nfs 'fdt set /boot_dev device nfs; fdt set /boot_dev device_doma domd_rootfs; fdt set /boot_dev my_ip $ipaddr; fdt set /boot_dev nfs_server_ip $serverip; fdt set /boot_dev nfs_dir $nfs_domd_dir'",
                "setenv bootcmd_tftp 'env delete bootargs; run tftp_xen_load && run tftp_dtb_load && run tftp_kernel_load && run tftp_xenpolicy_load && run tftp_initramfs_load && bootm 0x54080000 0x50000000 0x54000000'",
                "setenv bootcmd 'run bootcmd_tftp'",
                "saveenv",
            ]
        )
        return lines

    def apply_uboot_network_env_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        builder = ctx.command_builder
        paths = self.network_paths(ctx)
        env_lines = self.uboot_network_env_lines(ctx)
        serial_script = "\n".join(env_lines) + "\n"
        env_echo_script = "".join(f"echo {shlex.quote(line)}\n" for line in env_lines)
        script = (
            "set -euo pipefail\n"
            "echo 'Apply U-Boot network env'\n"
            f"{env_echo_script}"
            f"console={shlex.quote(paths['console'])}\n"
            "if [ -z \"$console\" ]; then console=$(ls -1 /dev/GEN5_CONSOLE* 2>/dev/null | head -n 1 || true); fi\n"
            "if [ -z \"$console\" ]; then echo 'GEN5 console device not found under /dev/GEN5_CONSOLE*' >&2; exit 2; fi\n"
            "echo 'Apply U-Boot network env over: '\"$console\"\n"
            "echo 'The board must be stopped at the U-Boot prompt before this command writes to serial.'\n"
            "python3 - \"$console\" <<'PY'\n"
            "import serial\n"
            "import sys\n"
            "import time\n"
            "\n"
            f"commands = {serial_script!r}\n"
            "conn = serial.Serial(port=sys.argv[1], baudrate=1843200, timeout=0.2)\n"
            "try:\n"
            "    conn.write(b'\\r')\n"
            "    time.sleep(0.2)\n"
            "    for line in commands.splitlines():\n"
            "        print('uboot:', line, flush=True)\n"
            "        conn.write((line + '\\r').encode('ascii'))\n"
            "        conn.flush()\n"
            "        time.sleep(0.25)\n"
            "finally:\n"
            "    conn.close()\n"
            "PY\n"
        )
        return [
            builder.board_ssh_command(paths["board_host"], script, tty=True),
        ]

    def uboot_ufs_env_lines(self) -> list[str]:
        return [
            "setenv bootcmd 'run bootcmd_ufs'",
            "saveenv",
        ]

    def apply_uboot_ufs_env_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        builder = ctx.command_builder
        paths = self.network_paths(ctx)
        env_lines = self.uboot_ufs_env_lines()
        serial_script = "\n".join(env_lines) + "\n"
        env_echo_script = "".join(f"echo {shlex.quote(line)}\n" for line in env_lines)
        script = (
            "set -euo pipefail\n"
            "echo 'Apply U-Boot UFS env'\n"
            f"{env_echo_script}"
            f"console={shlex.quote(paths['console'])}\n"
            "if [ -z \"$console\" ]; then console=$(ls -1 /dev/GEN5_CONSOLE* 2>/dev/null | head -n 1 || true); fi\n"
            "if [ -z \"$console\" ]; then echo 'GEN5 console device not found under /dev/GEN5_CONSOLE*' >&2; exit 2; fi\n"
            "echo 'Apply U-Boot UFS env over: '\"$console\"\n"
            "echo 'The board must be stopped at the U-Boot prompt before this command writes to serial.'\n"
            "python3 - \"$console\" <<'PY'\n"
            "import serial\n"
            "import sys\n"
            "import time\n"
            "\n"
            f"commands = {serial_script!r}\n"
            "conn = serial.Serial(port=sys.argv[1], baudrate=1843200, timeout=0.2)\n"
            "try:\n"
            "    conn.write(b'\\r')\n"
            "    time.sleep(0.2)\n"
            "    for line in commands.splitlines():\n"
            "        print('uboot:', line, flush=True)\n"
            "        conn.write((line + '\\r').encode('ascii'))\n"
            "        conn.flush()\n"
            "        time.sleep(0.25)\n"
            "finally:\n"
            "    conn.close()\n"
            "PY\n"
        )
        return [
            builder.board_ssh_command(paths["board_host"], script, tty=True),
        ]

    def restart_board_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        builder = ctx.command_builder
        board_host = config_accessors.board_host_spec_for_config(ctx.config)
        script = (
            "set -euo pipefail\n"
            "echo 'board power: x5h_off'\n"
            "x5h_off\n"
            "sleep 1\n"
            "echo 'board boot mode: x5h_boot'\n"
            "x5h_boot\n"
            "sleep 1\n"
            "echo 'board power: x5h_on'\n"
            "x5h_on\n"
        )
        return [
            builder.board_ssh_command(board_host, script, tty=True),
        ]

    def board_picocom_command_plan(
        self,
        ctx: BoardActionContext,
        *,
        title: str,
        restart: bool,
    ) -> list[list[str]]:
        builder = ctx.command_builder
        paths = self.network_paths(ctx)
        board_host = paths["board_host"]
        restart_script = ""
        sequence = "picocom"
        if restart:
            sequence = "x5h_off, x5h_boot, x5h_on, picocom"
            restart_script = (
                "echo 'board power: x5h_off'\n"
                "x5h_off\n"
                "sleep 1\n"
                "echo 'board boot mode: x5h_boot'\n"
                "x5h_boot\n"
                "sleep 1\n"
                "echo 'board power: x5h_on'\n"
                "x5h_on\n"
            )
        script = (
            "set -euo pipefail\n"
            f"echo {shlex.quote(title)}\n"
            f"echo 'board host: {board_host}'\n"
            f"echo 'sequence: {sequence}'\n"
            f"console={shlex.quote(paths['console'])}\n"
            "if [ -z \"$console\" ]; then console=$(ls -1 /dev/GEN5_CONSOLE* 2>/dev/null | head -n 1 || true); fi\n"
            "if [ -z \"$console\" ]; then echo 'GEN5 console device not found under /dev/GEN5_CONSOLE*' >&2; exit 2; fi\n"
            "command -v picocom >/dev/null 2>&1 || { echo 'picocom not found on board host' >&2; exit 2; }\n"
            f"{restart_script}"
            "echo 'opening serial console: '\"$console\"\n"
            "echo 'Press a key in picocom to stop U-Boot autoboot. Exit picocom with Ctrl-A Ctrl-X.'\n"
            "exec picocom -b 1843200 \"$console\"\n"
        )
        return [
            builder.board_ssh_command(board_host, script, tty=True),
        ]

    def open_board_serial_console_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        return self.board_picocom_command_plan(ctx, title="Open board serial console", restart=False)

    def open_uboot_console_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        return self.board_picocom_command_plan(ctx, title="Open U-Boot console", restart=True)

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
