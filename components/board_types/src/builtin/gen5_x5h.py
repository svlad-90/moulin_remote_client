"""GEN5 X5H board type adapter."""

from __future__ import annotations

import shlex
import re
import ipaddress
import json
import tarfile
import threading
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable

import yaml

from components.board_types.src.base import (
    BoardAction,
    BoardActionContext,
    BoardArtifactPart,
    BoardCapability,
    BoardCommandDefault,
    BoardLocalArtifactSpec,
    BoardOperationPlan,
    BoardTypeAdapter,
)
from components.config.api import accessors as config_accessors
from components.config.api import profiles as config_profiles
from components.moulin.api import manifest as moulin_manifest_api
from components.remote.api import transport


class _ProgressReader:
    """File wrapper reporting compressed bytes consumed by tarfile."""

    def __init__(
        self,
        stream: BinaryIO,
        total: int,
        progress: Callable[[int, int], None] | None,
    ) -> None:
        self.stream = stream
        self.total = total
        self.progress = progress

    def read(self, size: int = -1) -> bytes:
        data = self.stream.read(size)
        self._report()
        return data

    def seek(self, offset: int, whence: int = 0) -> int:
        position = self.stream.seek(offset, whence)
        self._report()
        return position

    def tell(self) -> int:
        return self.stream.tell()

    def readable(self) -> bool:
        return self.stream.readable()

    def seekable(self) -> bool:
        return self.stream.seekable()

    def writable(self) -> bool:
        return self.stream.writable()

    @property
    def closed(self) -> bool:
        return self.stream.closed

    def flush(self) -> None:
        self.stream.flush()

    def fileno(self) -> int:
        return self.stream.fileno()

    def _report(self) -> None:
        if self.progress is not None:
            self.progress(self.stream.tell(), self.total)


_BOOTLOADER_PARTS_CACHE: dict[tuple[str, int, int], tuple[BoardArtifactPart, ...]] = {}
_BOOTLOADER_PARTS_CACHE_LOCK = threading.Lock()


def _bootloader_parts_from_archive(
    path: str,
    size: int,
    mtime_ns: int,
    progress: Callable[[int, int], None] | None,
) -> tuple[BoardArtifactPart, ...]:
    """Read and cache selectable IPL metadata from one immutable archive version."""
    key = (path, size, mtime_ns)
    with _BOOTLOADER_PARTS_CACHE_LOCK:
        cached = _BOOTLOADER_PARTS_CACHE.get(key)
    if cached is not None:
        if progress is not None:
            progress(size, size)
        return cached
    with open(path, "rb") as stream, tarfile.open(
        fileobj=_ProgressReader(stream, size, progress), mode="r|*"
    ) as archive:
        config_name = ""
        document: Any = None
        file_names: set[str] = set()
        config_count = 0
        for member in archive:
            if not member.isfile():
                continue
            file_names.add(member.name)
            if not member.name.endswith("/build-domd/ipls/x5h_bootloaders.yaml"):
                continue
            config_count += 1
            config_name = member.name
            config_stream = archive.extractfile(member)
            if config_stream is None:
                raise ValueError("Cannot read x5h_bootloaders.yaml from boot artifacts")
            document = yaml.safe_load(config_stream)
        if config_count != 1:
            raise ValueError("Expected one build-domd/ipls/x5h_bootloaders.yaml in boot artifacts")
        entries = document.get("images", []) if isinstance(document, dict) else []
        if not isinstance(entries, list):
            raise ValueError("x5h_bootloaders.yaml images must be a list")
        prefix = str(PurePosixPath(config_name).parent) + "/"
        parts: list[BoardArtifactPart] = []
        for entry in entries:
            if not isinstance(entry, dict) or str(entry.get("target", "")).upper() != "UFS":
                continue
            name = str(entry.get("name", ""))
            if PurePosixPath(name).name != name or name in {"", ".", ".."}:
                raise ValueError(f"Invalid IPL filename: {name}")
            if prefix + name not in file_names:
                continue
            address = hex(int(str(entry["flash_addr"]), 16))
            parts.append(BoardArtifactPart(name, name, f"UFS {address}"))
        if not parts:
            raise ValueError("Boot artifacts do not contain flashable UFS IPL images")
        result = tuple(parts)
    if progress is not None:
        progress(size, size)
    with _BOOTLOADER_PARTS_CACHE_LOCK:
        if len(_BOOTLOADER_PARTS_CACHE) >= 8:
            _BOOTLOADER_PARTS_CACHE.pop(next(iter(_BOOTLOADER_PARTS_CACHE)))
        _BOOTLOADER_PARTS_CACHE[key] = result
    return result


class Gen5X5hBoardAdapter(BoardTypeAdapter):
    """Current built-in board workflow for GEN5 X5H over a board host."""

    type_id = "gen5_x5h"
    label = "GEN5 X5H"
    description = "GEN5 X5H board connected through a board host."

    def command_defaults(self) -> list[BoardCommandDefault]:
        return [
            BoardCommandDefault(
                "power_off",
                "Power off command",
                "x5h_off",
                "Board-host command that powers the board off.",
            ),
            BoardCommandDefault(
                "power_on",
                "Power on command",
                "x5h_on",
                "Board-host command that powers the board on.",
            ),
            BoardCommandDefault(
                "boot_mode",
                "Boot mode command",
                "x5h_boot",
                "Board-host command that switches the board to normal boot mode.",
            ),
            BoardCommandDefault(
                "flash_mode",
                "Flash mode command",
                "x5h_flash",
                "Board-host command that switches the board to bootloader flash mode.",
            ),
        ]

    def board_command(self, ctx: BoardActionContext, command_id: str) -> str:
        return self.command_value_for_host(config_profiles.board_target(ctx.config), command_id)

    def board_command_script(self, ctx: BoardActionContext, command_id: str, label: str) -> str:
        command = self.board_command(ctx, command_id)
        return f"echo {shlex.quote(label + ': ' + command)}\n{command}\n"

    def rsync_progress_args(self, *, sparse: bool = False, inplace: bool = False) -> list[str]:
        argv = ["rsync", "-az"]
        if sparse:
            argv[-1] += "S"
            inplace = True
        if inplace:
            argv.extend(["--inplace"])
        argv.extend([*transport.rsync_options(), "--info=progress2", "--stats", "--human-readable"])
        return argv

    def rsync_progress_shell_prefix(
        self,
        *,
        sparse: bool = False,
        inplace: bool = False,
        accept_new_host_key: bool = False,
    ) -> str:
        return transport.shell_command(
            [
                *self.rsync_progress_args(sparse=sparse, inplace=inplace),
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
                "Flash bootloaders (flash mode) from build host",
                "Use boot artifacts copied from the build host, enter flash mode, flash x5h_bootloaders.yaml, then switch the board to boot mode.",
                local_artifact=BoardLocalArtifactSpec(
                    "Select boot-artifacts archive",
                    "Expected: .tar, .tar.gz, or .tar.bz2",
                    (".tar.bz2", ".tar.gz", ".tar"),
                ),
            ),
            BoardAction(
                "flash_single_ipl",
                "Flash bootloaders from build host",
                "Select all or a subset of YAML UFS images copied from the build host. Enter U-Boot once and flash in YAML order; stop on the first error.",
                confirm=False,
                local_artifact=BoardLocalArtifactSpec(
                    "Select boot-artifacts archive",
                    "Expected: .tar, .tar.gz, or .tar.bz2",
                    (".tar.bz2", ".tar.gz", ".tar"),
                    selection_title="Flash Bootloaders",
                ),
            ),
            BoardAction(
                "flash_ufs_image",
                "Flash UFS image from build host",
                "Flash artifacts/full_ufs.img.gz copied from the build host to UFS over /dev/GEN5_CONSOLE.",
                target_patterns=("full_ufs.img.gz",),
                local_artifact=BoardLocalArtifactSpec(
                    "Select full UFS image",
                    "Expected: compressed .img.gz image",
                    (".img.gz",),
                ),
            ),
            BoardAction(
                "restart_board",
                "Restart board",
                "Power-cycle the GEN5 X5H board on the board host and leave it in boot mode.",
                confirm=True,
                required_commands=("power_off", "boot_mode", "power_on"),
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
                "turn_off_board",
                "Turn off board",
                "Run the configured board power-off command on the board host.",
                confirm=True,
                required_commands=("power_off",),
            ),
            BoardAction(
                "deploy_network_boot",
                "Deploy TFTP boot artifacts",
                "Initial or refreshed network-boot deploy: copy GEN5 boot artifacts from the build host into the board-host TFTP project directory and update the current symlink.",
                requires_remote=True,
                requires_project=True,
                domains=("dom0",),
                target_patterns=("boot_artifacts",),
            ),
            BoardAction(
                "deploy_network_domd_rootfs",
                "Deploy DomD NFS rootfs",
                "Initial or refreshed network-boot deploy: copy the DomD rootfs artifact to the board host, extract it into the NFS project directory, and update the current symlink.",
                requires_remote=True,
                requires_project=True,
                domains=("domd",),
                target_patterns=("domd",),
            ),
            BoardAction(
                "deploy_network_domu_rootfs",
                "Deploy DomU NFS rootfs",
                "Initial or refreshed network-boot deploy: copy the DomU rootfs artifact to the board host, extract it into the NFS project directory, and update the current symlink.",
                requires_remote=True,
                requires_project=True,
                domains=("domu",),
                target_patterns=("domu",),
            ),
            BoardAction(
                "deploy_network_android",
                "Deploy Android image to NFS",
                "Initial or refreshed network-boot deploy: copy android_only.img.gz from the build host, expand it into the board-host NFS project directory, and update the current symlink.",
                requires_remote=True,
                requires_project=True,
                domains=("doma",),
                target_patterns=("android_only.img.gz", "android_only", "doma"),
            ),
            BoardAction(
                "unpack_network_android",
                "Unpack Android image on NFS",
                "Expand the Android archive already on the board host, publish the image in the DomD rootfs, and update the NFS current symlink.",
                requires_project=True,
                domains=("doma",),
                target_patterns=("android_only.img.gz", "android_only", "doma"),
            ),
            BoardAction(
                "deploy_network_full",
                "Deploy full TFTP/NFS set",
                "First step for a full network-boot setup: deploy the network artifacts that match the active build targets.",
                requires_remote=True,
                requires_project=True,
                domains=("dom0", "domd", "domu", "doma"),
                target_patterns=("boot_artifacts", "domd", "domu", "android_only.img.gz", "android_only", "doma"),
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
            BoardAction(
                "inject_invasive_uboot_parameters",
                "Inject invasive U-Boot parameters",
                "One-time board setup: write non-empty invasive board IP, TFTP server IP, and MAC address values into persistent U-Boot env.",
                requires_project=True,
            ),
        ]

    def local_artifact_parts(
        self,
        action_id: str,
        source: Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[BoardArtifactPart]:
        if action_id != "flash_single_ipl":
            return []
        stat = source.stat()
        return list(
            _bootloader_parts_from_archive(
                str(source), stat.st_size, stat.st_mtime_ns, progress
            )
        )

    def local_artifact_destination(self, action_id: str, source: Path) -> tuple[str, tuple[str, ...]]:
        if action_id in {"flash_bootloaders", "flash_single_ipl"}:
            suffix = next(
                (candidate for candidate in (".tar.bz2", ".tar.gz", ".tar") if source.name.endswith(candidate)),
                None,
            )
            if suffix is None:
                raise ValueError("boot artifacts must be a .tar, .tar.gz, or .tar.bz2 archive")
            return "manual-boot-artifacts" + suffix, (
                "*boot-artifacts*.tar.bz2",
                "*boot_artifacts*.tar.bz2",
                "*boot-artifacts*.tar.gz",
                "*boot_artifacts*.tar.gz",
                "*boot-artifacts*.tar",
                "*boot_artifacts*.tar",
            )
        if action_id == "flash_ufs_image":
            return "full_ufs.img.gz", ("full_ufs.img.gz",)
        return super().local_artifact_destination(action_id, source)

    def local_artifact_build_params(
        self,
        action_id: str,
        selected_parts: tuple[BoardArtifactPart, ...],
    ) -> dict[str, str]:
        if action_id == "flash_single_ipl":
            return {
                "_ipl_names": json.dumps([part.part_id for part in selected_parts]),
                "_ipl_prepare": "true",
            }
        return {}

    def local_artifact_warning(self, action_id: str) -> str:
        warnings = {
            "flash_bootloaders": "This enters flash mode and overwrites all bootloaders described by the selected archive.",
            "flash_single_ipl": "This overwrites the selected UFS IPLs through U-Boot.",
            "flash_ufs_image": "This overwrites the board UFS image.",
        }
        if action_id not in warnings:
            return super().local_artifact_warning(action_id)
        return warnings[action_id]

    def action_commands(self, ctx: BoardActionContext, action_id: str) -> list[list[str]]:
        if action_id == "flash_single_ipl":
            return self.flash_single_ipl_command_plan(ctx)
        if action_id == "copy_build_artifacts":
            commands = ctx.transfer_service.copy_build_artifacts_commands(
                ctx.config,
                artifact_targets=ctx.artifact_targets,
                build_params=ctx.build_params or {},
            )
            if any("boot" in target and "artifact" in target for target in shlex.split(ctx.artifact_targets)):
                commands.append(ctx.command_builder.board_ssh_command(
                    config_accessors.board_host_spec_for_config(ctx.config),
                    self.ipl_helper_script(ctx, prepare=True),
                ))
            return commands
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
                console=config_accessors.board_console_device_for_config(ctx.config),
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
        if action_id == "turn_off_board":
            return self.board_power_command_plan(ctx, command_id="power_off", title="Turn off board")
        if action_id == "open_board_serial_console":
            return self.open_board_serial_console_command_plan(ctx)
        if action_id == "open_uboot_console":
            return self.open_uboot_console_command_plan(ctx)
        if action_id == "deploy_network_boot":
            return self.deploy_network_boot_command_plan(ctx)
        if action_id == "deploy_network_domd_rootfs":
            return self.deploy_network_domd_rootfs_command_plan(ctx)
        if action_id == "deploy_network_domu_rootfs":
            return self.deploy_network_domu_rootfs_command_plan(ctx)
        if action_id == "deploy_network_android":
            return self.deploy_network_android_command_plan(ctx)
        if action_id == "unpack_network_android":
            return self.unpack_network_android_command_plan(ctx)
        if action_id == "deploy_network_full":
            return self.deploy_network_full_command_plan(ctx)
        if action_id == "install_nfs_deploy_helper":
            return self.install_nfs_deploy_helper_command_plan(ctx)
        if action_id == "inject_invasive_uboot_parameters":
            return self.inject_invasive_uboot_parameters_command_plan(ctx)
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

    def capabilities(self, board_host: dict[str, Any] | None = None) -> frozenset[BoardCapability]:
        return super().capabilities(board_host) | {
            BoardCapability.REFLASH,
            BoardCapability.REFLASH_BOOTLOADERS,
        }

    def operation_plan(
        self,
        ctx: BoardActionContext,
        capability: BoardCapability,
    ) -> BoardOperationPlan | None:
        if capability == BoardCapability.REFLASH:
            return self.ufs_reflash_operation_plan(ctx)
        if capability == BoardCapability.REFLASH_BOOTLOADERS:
            return self.bootloader_reflash_operation_plan(ctx)
        return super().operation_plan(ctx, capability)

    def ufs_reflash_operation_plan(self, ctx: BoardActionContext) -> BoardOperationPlan:
        build_targets = ("full_ufs.img.gz",)
        reflash_ctx = replace(ctx, artifact_targets=" ".join(build_targets))
        provision_commands = self.action_commands(reflash_ctx, "copy_build_artifacts")
        flash_commands = self.action_commands(reflash_ctx, "flash_ufs_image")
        if not flash_commands:
            raise ValueError("GEN5 X5H reflash flow produced no execute command")
        provision_commands.extend(flash_commands[:-1])
        return BoardOperationPlan(
            capability=BoardCapability.REFLASH,
            operation_id="gen5-x5h-ufs-reflash",
            build_targets=build_targets,
            provision_commands=tuple(tuple(command) for command in provision_commands),
            execute_commands=(tuple(flash_commands[-1]),),
            execute_timeout_seconds=1800,
            post_execute_delay_seconds=10,
        )

    def bootloader_reflash_operation_plan(self, ctx: BoardActionContext) -> BoardOperationPlan:
        build_targets = ("boot_artifacts",)
        reflash_ctx = replace(ctx, artifact_targets=" ".join(build_targets))
        provision_commands = self.action_commands(reflash_ctx, "copy_build_artifacts")
        flash_commands = self.action_commands(reflash_ctx, "flash_bootloaders")
        if len(flash_commands) != 6:
            raise ValueError("GEN5 X5H bootloader reflash flow has an unexpected command plan")
        provision_commands.extend(flash_commands[:2])
        provision_commands.extend(flash_commands[3:5])
        return BoardOperationPlan(
            capability=BoardCapability.REFLASH_BOOTLOADERS,
            operation_id="gen5-x5h-bootloader-reflash",
            build_targets=build_targets,
            provision_commands=tuple(tuple(command) for command in provision_commands),
            execute_commands=(tuple(flash_commands[2]), tuple(flash_commands[5])),
            execute_timeout_seconds=1800,
            post_execute_delay_seconds=10,
        )

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
  : > "$dest/.moulin-android_only.img.gz"
  chown "$user:" "$dest/.moulin-android_only.img.gz"
  chmod 0644 "$dest/.moulin-android_only.img.gz"
  exit 0
fi

if [ "$dest" = "--refresh-current" ]; then
  base=${2:?base is required}
  current=${3:?current is required}
  project=${4:?project is required}
  case "$base" in
    /srv/nfs/*) ;;
    *) echo "refuse base outside /srv/nfs: $base" >&2; exit 2 ;;
  esac
  case "$current" in
    "$base"/current) ;;
    *) echo "refuse unexpected current symlink path: $current" >&2; exit 2 ;;
  esac
  case "$project" in
    */*|.*|"") echo "refuse unexpected project symlink target: $project" >&2; exit 2 ;;
  esac
  mkdir -p "$base"
  ln -sfn "$project" "$current"
  echo "NFS current -> $project"
  exit 0
fi

if [ "$dest" = "--install-android" ]; then
  dest=${2:?dest is required}
  image=${3:?image is required}
  unpacked="$dest/.moulin-android_only.img"
  case "$dest" in
    /srv/nfs/*) ;;
    *) echo "refuse dest outside /srv/nfs: $dest" >&2; exit 2 ;;
  esac
  case "$image" in
    "$dest"/.moulin-android_only.img.gz) ;;
    *) echo "refuse unexpected android image path: $image" >&2; exit 2 ;;
  esac
  [ -f "$image" ] || { echo "android image not found: $image" >&2; exit 2; }
  rm -f "$unpacked"
  echo "android image deploy: expanding compressed image on board host..." >&2
  gzip -dc "$image" > "$unpacked" &
  gzip_pid=$!
  while kill -0 "$gzip_pid" 2>/dev/null; do
    bytes=$(wc -c < "$unpacked" 2>/dev/null || echo 0)
    printf 'android image deploy: expanded %s bytes\n' "$bytes" >&2
    sleep 5
  done
  set +e
  wait "$gzip_pid"
  gzip_rc=$?
  set -e
  if [ "$gzip_rc" -ne 0 ]; then
    rm -f "$unpacked"
    exit "$gzip_rc"
  fi
  bytes=$(wc -c < "$unpacked" 2>/dev/null || echo 0)
  printf 'android image deploy: expanded %s bytes\n' "$bytes" >&2
  mv -f "$unpacked" "$dest/android_only.img"
  chown root:root "$dest/android_only.img"
  chmod 0644 "$dest/android_only.img"
  domd_image="$dest/rootfs/domd/android_only.img"
  if [ -d "$dest/rootfs/domd" ]; then
    rm -f "$domd_image"
    if ln "$dest/android_only.img" "$domd_image" 2>/dev/null; then
      echo "android image deploy: linked DomD /android_only.img" >&2
    else
      echo "android image deploy: hardlink failed; copying DomD /android_only.img" >&2
      cp -f "$dest/android_only.img" "$domd_image"
    fi
    chown root:root "$domd_image"
    chmod 0644 "$domd_image"
  else
    echo "android image deploy: DomD rootfs is missing, cannot publish /android_only.img" >&2
    exit 2
  fi
  exit 0
fi

tarball=${2:?tarball is required}

case "$dest" in
  /srv/nfs/*) ;;
  *) echo "refuse dest outside /srv/nfs: $dest" >&2; exit 2 ;;
esac

case "$tarball" in
  "$dest"/.moulin-domd-rootfs.tar.bz2) ;;
  "$dest"/.moulin-domu-rootfs.tar.bz2) ;;
  *) echo "refuse unexpected tarball path: $tarball" >&2; exit 2 ;;
esac

[ -f "$tarball" ] || { echo "rootfs tarball not found: $tarball" >&2; exit 2; }

echo "rootfs deploy: cleaning old NFS rootfs under $dest" >&2
find "$dest" -mindepth 1 -maxdepth 1 ! -name '.moulin-*-rootfs.tar.bz2' ! -name 'android_only.img' -exec rm -rf {} +
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
        return self.refresh_tftp_current_symlink_script(ctx) + self.refresh_nfs_current_symlink_script(ctx)

    def refresh_tftp_current_symlink_script(self, ctx: BoardActionContext) -> str:
        builder = ctx.command_builder
        paths = self.network_paths(ctx)
        tftp_base = config_accessors.board_network_base_dir(
            config_accessors.board_tftp_root_for_config(ctx.config),
            config_accessors.board_deploy_subdir_for_config(ctx.config),
        )
        return (
            f"mkdir -p {builder.quote_remote_shell_path(tftp_base)}\n"
            f"ln -sfn {shlex.quote(paths['project'])} {builder.quote_remote_shell_path(paths['tftp_current'])}\n"
            f"echo 'TFTP current -> {paths['project']}'\n"
        )

    def refresh_nfs_current_symlink_script(self, ctx: BoardActionContext) -> str:
        builder = ctx.command_builder
        paths = self.network_paths(ctx)
        nfs_base = config_accessors.board_network_base_dir(
            config_accessors.board_nfs_root_for_config(ctx.config),
            config_accessors.board_deploy_subdir_for_config(ctx.config),
        )
        helper = self.nfs_deploy_helper_path()
        return (
            f"sudo -n {shlex.quote(helper)} --refresh-current "
            f"{builder.quote_remote_shell_path(nfs_base)} "
            f"{builder.quote_remote_shell_path(paths['nfs_current'])} "
            f"{shlex.quote(paths['project'])}\n"
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
        refresh_board_script = "set -euo pipefail\n" + self.refresh_tftp_current_symlink_script(ctx)
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
        return self.deploy_network_rootfs_command_plan(
            ctx,
            domain="domd",
            label="DomD",
            build_dir="build-domd",
        )

    def deploy_network_domu_rootfs_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        return self.deploy_network_rootfs_command_plan(
            ctx,
            domain="domu",
            label="DomU",
            build_dir="build-domu",
        )

    def yocto_guest_domains(self, ctx: BoardActionContext) -> list[str]:
        if ctx.app_dir is None or ctx.remote_read_project_file is None:
            return ["domd"]
        try:
            components = moulin_manifest_api.component_builders_for_config(
                ctx.config,
                app_dir=ctx.app_dir,
                remote_read_project_file=ctx.remote_read_project_file,
                cache=ctx.manifest_cache or {},
                default_moulin_manifest=ctx.default_moulin_manifest,
                build_params=ctx.build_params or {},
            )
        except Exception:
            return ["domd"]
        domains = [
            str(component.get("name", "")).strip()
            for component in components
            if component.get("builder_type") == "yocto" and str(component.get("name", "")).strip() != "dom0"
        ]
        return domains or ["domd"]

    @staticmethod
    def shell_identifier(name: str) -> str:
        clean = re.sub(r"[^A-Za-z0-9_]", "_", name.strip())
        return clean or "guest"

    def guest_rootfs_project_dir(self, nfs_project: str, domain: str) -> str:
        return f"{nfs_project.rstrip('/')}/rootfs/{self.shell_identifier(domain)}"

    def guest_rootfs_current_dir(self, nfs_current: str, domain: str) -> str:
        return f"{nfs_current.rstrip('/')}/rootfs/{self.shell_identifier(domain)}"

    def deploy_network_rootfs_command_plan(
        self,
        ctx: BoardActionContext,
        *,
        domain: str,
        label: str,
        build_dir: str,
    ) -> list[list[str]]:
        builder = ctx.command_builder
        paths = self.network_paths(ctx)
        nfs_project = paths["nfs_project"]
        domain_nfs_project = self.guest_rootfs_project_dir(nfs_project, domain)
        helper = self.nfs_deploy_helper_path()
        remote_tarball = f"{domain_nfs_project.rstrip('/')}/.moulin-{domain}-rootfs.tar.bz2"
        rsync_target = f"{paths['board_host']}:{remote_tarball}"
        prepare_board_script = (
            "set -euo pipefail\n"
            f"sudo -n {shlex.quote(helper)} --check || {{ echo 'Install NFS deploy helper first.' >&2; exit 2; }}\n"
            f"sudo -n {shlex.quote(helper)} --prepare {builder.quote_remote_shell_path(domain_nfs_project)} {shlex.quote(paths['board_user'])}\n"
        )
        extract_board_script = (
            "set -euo pipefail\n"
            f"dest={builder.quote_remote_shell_path(domain_nfs_project)}\n"
            f"tarball={builder.quote_remote_shell_path(remote_tarball)}\n"
            f"echo 'Installing {label} rootfs on board host...' >&2\n"
            f"sudo -n {shlex.quote(helper)} \"$dest\" \"$tarball\"\n"
            "echo 'Refreshing NFS current symlinks...' >&2\n"
            f"{self.refresh_nfs_current_symlink_script(ctx)}"
        )
        rootfs_lookup_script = (
            "set -euo pipefail\n"
            f"cd {shlex.quote(paths['remote_project'])}\n"
            "search_roots=()\n"
            f"[ -d yocto/{build_dir}/tmp/deploy/images ] && search_roots+=(yocto/{build_dir}/tmp/deploy/images)\n"
            "[ -d artifacts ] && search_roots+=(artifacts)\n"
            f"if [ \"${{#search_roots[@]}}\" -eq 0 ]; then echo '{label} rootfs search directories not found' >&2; exit 2; fi\n"
            "rootfs=$(find \"${search_roots[@]}\" -type f "
            "\\( -name 'rcar-image-adas-x5h.tar.bz2' -o -name 'rcar-image-adas-*.tar.bz2' \\) -print -quit 2>/dev/null)\n"
            f"if [ -z \"$rootfs\" ]; then echo '{label} rootfs tarball not found' >&2; exit 2; fi\n"
        )
        validate_script = rootfs_lookup_script + f"echo 'found {label} rootfs tarball: '\"$rootfs\" >&2\n"
        build_script = (
            rootfs_lookup_script +
            f"echo 'Deploy {label} NFS rootfs' >&2\n"
            f"echo 'from: {paths['build_host']}:{paths['remote_project']}/yocto/{build_dir}/tmp/deploy/images' >&2\n"
            f"echo 'to:   {paths['board_host']}:{domain_nfs_project}' >&2\n"
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
        upload_image = f"{nfs_project.rstrip('/')}/.moulin-android_only.img.gz"
        rsync_target = f"{paths['board_host']}:{upload_image}"
        prepare_board_script = (
            "set -euo pipefail\n"
            f"sudo -n {shlex.quote(helper)} --check || {{ echo 'Install NFS deploy helper first.' >&2; exit 2; }}\n"
            f"sudo -n {shlex.quote(helper)} --prepare-android {builder.quote_remote_shell_path(nfs_project)} {shlex.quote(paths['board_user'])}\n"
        )
        install_board_script = self.android_image_install_script(ctx)
        build_script = (
            "set -euo pipefail\n"
            "echo 'Deploy Android image to NFS' >&2\n"
            f"echo 'from: {paths['build_host']}:{paths['remote_project']}/android_only.img.gz' >&2\n"
            f"echo 'to:   {paths['board_host']}:{paths['nfs_project']}/android_only.img' >&2\n"
            f"cd {shlex.quote(paths['remote_project'])}\n"
            "image=$(find . -maxdepth 4 -type f -name android_only.img.gz -print -quit)\n"
            "if [ -z \"$image\" ]; then echo 'android_only.img.gz not found under build project' >&2; exit 2; fi\n"
            "echo 'rsync compressed android image: '\"$image\" >&2\n"
            "image_bytes=$(stat -c%s \"$image\")\n"
            "image_disk_bytes=$(du -sb \"$image\" | awk '{print $1}')\n"
            "printf 'compressed android image apparent size: %s bytes\\n' \"$image_bytes\" >&2\n"
            "printf 'compressed android image disk usage: %s bytes\\n' \"$image_disk_bytes\" >&2\n"
            f"{transport.ssh_command_string(paths['board_host'], prepare_board_script, accept_new_host_key=True)}\n"
            f"{self.rsync_progress_shell_prefix(inplace=True, accept_new_host_key=True)} "
            f"\"$image\" {shlex.quote(rsync_target)}\n"
            f"{transport.ssh_command_string(paths['board_host'], install_board_script, accept_new_host_key=True)}\n"
        )
        return [
            transport.ssh_command(paths["build_host"], "bash -lc " + shlex.quote(build_script)),
        ]

    def android_image_install_script(self, ctx: BoardActionContext) -> str:
        builder = ctx.command_builder
        nfs_project = config_accessors.board_nfs_project_dir_for_config(ctx.config)
        archive = f"{nfs_project.rstrip('/')}/.moulin-android_only.img.gz"
        helper = self.nfs_deploy_helper_path()
        return (
            "set -euo pipefail\n"
            f"sudo -n {shlex.quote(helper)} --check || {{ echo 'Install NFS deploy helper first.' >&2; exit 2; }}\n"
            f"sudo -n {shlex.quote(helper)} --install-android "
            f"{builder.quote_remote_shell_path(nfs_project)} {builder.quote_remote_shell_path(archive)}\n"
            + self.refresh_nfs_current_symlink_script(ctx)
        )

    def unpack_network_android_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        return [
            ctx.command_builder.board_ssh_command(
                config_accessors.board_host_spec_for_config(ctx.config),
                self.android_image_install_script(ctx),
            )
        ]

    def deploy_network_full_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        targets = set(shlex.split(ctx.artifact_targets or ""))
        if not targets:
            targets = {"boot_artifacts", "domd", "domu", "android_only.img.gz", "doma"}
        domains = ctx.active_domains or frozenset({"dom0", "domd", "domu", "doma"})
        commands: list[list[str]] = []
        if "dom0" in domains and "boot_artifacts" in targets:
            commands += self.deploy_network_boot_command_plan(ctx)
        if "domd" in domains and "domd" in targets:
            commands += self.deploy_network_domd_rootfs_command_plan(ctx)
        if "domu" in domains and "domu" in targets:
            commands += self.deploy_network_domu_rootfs_command_plan(ctx)
        if "doma" in domains and targets.intersection({"android_only.img.gz", "android_only", "doma"}):
            commands += self.deploy_network_android_command_plan(ctx)
        if not commands:
            return [
                ctx.command_builder.local_log_command(
                    "No network deploy artifacts match the active build targets",
                    exit_code=1,
                )
            ]
        return commands

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
            f"mkdir -p {builder.quote_remote_shell_path(paths['tftp_project'])}\n"
            f"sudo -n {shlex.quote(self.nfs_deploy_helper_path())} --prepare "
            f"{builder.quote_remote_shell_path(paths['nfs_project'])} {shlex.quote(paths['board_user'])}\n"
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
            f"{self.refresh_tftp_current_symlink_script(ctx)}"
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
        guest_domains = self.yocto_guest_domains(ctx)
        tftp_root = config_accessors.board_tftp_root_for_config(ctx.config).rstrip("/")
        tftp_current = paths["tftp_current"].rstrip("/")
        if tftp_current.startswith(tftp_root + "/"):
            tftp_prefix = tftp_current[len(tftp_root) + 1 :]
        else:
            tftp_prefix = tftp_current.lstrip("/")
        lines = []
        configure_parts = [
            "fdt set /boot_dev device nfs",
            "fdt set /boot_dev my_ip $ipaddr",
            "fdt set /boot_dev nfs_server_ip $serverip",
        ]
        if "domd" in guest_domains:
            lines.append(f"nfs_domd_dir={self.guest_rootfs_current_dir(paths['nfs_current'], 'domd')}")
            configure_parts.append("fdt set /boot_dev device_doma domd_rootfs")
            configure_parts.append("fdt set /boot_dev nfs_dir $nfs_domd_dir")
        if "domu" in guest_domains:
            lines.append(f"nfs_domu_dir={self.guest_rootfs_current_dir(paths['nfs_current'], 'domu')}")
            configure_parts.append("fdt set /boot_dev device_domu nfs")
            configure_parts.append("fdt set /boot_dev nfs_dir_domu $nfs_domu_dir")
        lines.extend(
            [
                "fdt_high=0xffffffffffffffff",
                "bootm_size=0x10000000",
                "i2c_pci=i2c dev 0; i2c mw 0x77 0x06 0x00; i2c mw 0x77 0x02 0x14; i2c mw 0x77 0x04 0x00; i2c mw 0x77 0x01 0xff",
                f"tftp_dtb_load=tftp 0x54000000 {tftp_prefix}/r8a78000-ironhide-xen.dtb && fdt addr 0x54000000 && fdt resize && fdt mknode / boot_dev && run tftp_configure_nfs",
                f"tftp_initramfs_load=tftp 0x50000000 {tftp_prefix}/uInitramfs",
                f"tftp_kernel_load=tftp 0x64000000 {tftp_prefix}/Image",
                f"tftp_xen_load=tftp 0x54080000 {tftp_prefix}/xen-ironhide.uImage",
                f"tftp_xenpolicy_load=tftp 0x53000000 {tftp_prefix}/xenpolicy-ironhide",
                "tftp_configure_nfs=" + "; ".join(configure_parts),
                "bootcmd_moulin=env delete bootargs; run tftp_xen_load && run tftp_dtb_load && run tftp_kernel_load && run tftp_xenpolicy_load && run tftp_initramfs_load && bootm 0x54080000 0x50000000 0x54000000",
            ]
        )
        return lines

    def uboot_user_command_name(self, ctx: BoardActionContext) -> str:
        deploy_subdir = config_accessors.board_deploy_subdir_for_config(ctx.config)
        seed = deploy_subdir.split("/", 1)[0] if deploy_subdir else config_accessors.network_deploy_project_name_for_config(ctx.config)
        return f"user_{self.shell_identifier(seed or 'moulin')}"

    def uboot_env_tftp_path(self, ctx: BoardActionContext) -> str:
        paths = self.network_paths(ctx)
        tftp_root = config_accessors.board_tftp_root_for_config(ctx.config).rstrip("/")
        env_file = f"{paths['tftp_current'].rstrip('/')}/env/uboot.env"
        if env_file.startswith(tftp_root + "/"):
            return env_file[len(tftp_root) + 1 :]
        return env_file.lstrip("/")

    def uboot_env_file_install_command_plan(self, ctx: BoardActionContext, env_lines: list[str]) -> list[list[str]]:
        builder = ctx.command_builder
        paths = self.network_paths(ctx)
        env_text = "\n".join(env_lines) + "\n"
        env_file = f"{paths['tftp_project'].rstrip('/')}/env/uboot.env"
        script = (
            "set -euo pipefail\n"
            f"mkdir -p {builder.quote_remote_shell_path(paths['tftp_project'].rstrip('/') + '/env')}\n"
            f"{self.refresh_tftp_current_symlink_script(ctx)}"
            f"cat > {builder.quote_remote_shell_path(env_file)} <<'EOF'\n"
            f"{env_text}"
            "EOF\n"
            f"echo 'Wrote U-Boot env file: {env_file}'\n"
        )
        return [builder.board_ssh_command(paths["board_host"], script)]

    def uboot_loader_env_lines(self, ctx: BoardActionContext) -> list[str]:
        user_command = self.uboot_user_command_name(ctx)
        env_path = self.uboot_env_tftp_path(ctx)
        return [
            f"setenv {user_command} 'tftp ${{loadaddr}} {env_path}; env import -t ${{loadaddr}} ${{filesize}}; run bootcmd_moulin'",
            "saveenv",
        ]

    def invasive_uboot_parameter_lines(self, ctx: BoardActionContext) -> list[str]:
        paths = self.network_paths(ctx)
        lines = []
        if paths["board_ip"]:
            lines.append(f"setenv ipaddr {paths['board_ip']}")
        if paths["server_ip"]:
            lines.append(f"setenv serverip {paths['server_ip']}")
            lines.append(f"setenv serveraddr {paths['server_ip']}")
        mac_address = config_accessors.board_mac_address_for_config(ctx.config)
        if mac_address:
            lines.append(f"setenv ethaddr {mac_address}")
        if lines:
            lines.append("saveenv")
        return lines

    def uboot_action_script(
        self, ctx: BoardActionContext, *, title: str,
        commands: list[str] | None = None, require_variable: str = "",
        verify_variable: str = "", verify_command: str = "", boot_command: str = "",
        network: bool = False,
    ) -> str:
        source = (Path(__file__).resolve().parents[4] / "board_tools/gen5_x5h_uboot.py").read_text()
        args = ["python3", "-u", "-c", source,
                "--port", config_accessors.board_console_device_for_config(ctx.config),
                "--power-off-command", self.board_command(ctx, "power_off"),
                "--boot-mode-command", self.board_command(ctx, "boot_mode"),
                "--power-on-command", self.board_command(ctx, "power_on")]
        for command in commands or []:
            args += ["--command", command]
        for flag, value in (("--require-variable", require_variable),
                            ("--verify-variable", verify_variable),
                            ("--verify-command", verify_command), ("--boot-command", boot_command)):
            if value:
                args += [flag, value]
        if network:
            for flag, value in (("--ipaddr", config_accessors.board_ipaddr_for_config(ctx.config)),
                                ("--serverip", config_accessors.board_server_ip_for_config(ctx.config))):
                if value:
                    try:
                        args += [flag, str(ipaddress.IPv4Address(value))]
                    except ValueError as exc:
                        raise ValueError(f"{flag[2:]} override must be a valid IPv4 address in the active board-host profile.") from exc
        return "set -euo pipefail\n" + "echo " + shlex.quote(title) + "\n" + shlex.join(args) + "\n"

    def inject_invasive_uboot_parameters_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        lines = self.invasive_uboot_parameter_lines(ctx)
        if not lines:
            return [ctx.command_builder.board_ssh_command(
                config_accessors.board_host_spec_for_config(ctx.config),
                "echo 'No invasive U-Boot parameters are configured; nothing to write.'",
            )]
        script = self.uboot_action_script(
            ctx, title="Inject invasive U-Boot parameters", commands=lines,
            require_variable="bootcmd", verify_command="printenv ipaddr serverip serveraddr ethaddr",
        )
        return [ctx.command_builder.board_ssh_command(
            config_accessors.board_host_spec_for_config(ctx.config), script, tty=True,
        )]

    def apply_uboot_network_env_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        script = self.uboot_action_script(
            ctx, title="Apply U-Boot network env", commands=self.uboot_loader_env_lines(ctx),
            require_variable="bootcmd", verify_variable=self.uboot_user_command_name(ctx),
        )
        return [
            *self.uboot_env_file_install_command_plan(ctx, self.uboot_network_env_lines(ctx)),
            ctx.command_builder.board_ssh_command(
                config_accessors.board_host_spec_for_config(ctx.config), script, tty=True,
            ),
        ]

    def uboot_ufs_env_lines(self) -> list[str]:
        return [
            "fdt_high=0xffffffffffffffff",
            "bootm_size=0x10000000",
            "ufs_dtb_load=ext2load scsi 1:1 0x54000000 xen.dtb && fdt addr 0x54000000 && fdt resize && fdt mknode / boot_dev && fdt set /boot_dev device sda",
            "ufs_initramfs_load=ext2load scsi 1:1 0x50000000 uInitramfs",
            "ufs_kernel_load=ext2load scsi 1:1 0x64000000 Image",
            "ufs_xen_load=ext2load scsi 1:1 0x54080000 xen",
            "ufs_xenpolicy_load=ext2load scsi 1:1 0x53000000 xenpolicy",
            "bootcmd_moulin=env delete bootargs; scsi scan; run ufs_xen_load && run ufs_dtb_load && run ufs_kernel_load && run ufs_xenpolicy_load && run ufs_initramfs_load && bootm 0x54080000 0x50000000 0x54000000",
        ]

    def apply_uboot_ufs_env_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        script = self.uboot_action_script(
            ctx, title="Apply U-Boot UFS env", commands=self.uboot_loader_env_lines(ctx),
            require_variable="bootcmd", verify_variable=self.uboot_user_command_name(ctx),
        )
        return [
            *self.uboot_env_file_install_command_plan(ctx, self.uboot_ufs_env_lines()),
            ctx.command_builder.board_ssh_command(
                config_accessors.board_host_spec_for_config(ctx.config), script, tty=True,
            ),
        ]

    def restart_board_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        user_command = self.uboot_user_command_name(ctx)
        script = self.uboot_action_script(
            ctx, title="Restart board and run Moulin U-Boot action",
            require_variable=user_command, boot_command=f"run {user_command}",
        )
        return [ctx.command_builder.board_ssh_command(
            config_accessors.board_host_spec_for_config(ctx.config), script, tty=True,
        )]

    def board_power_command_plan(
        self,
        ctx: BoardActionContext,
        *,
        command_id: str,
        title: str,
    ) -> list[list[str]]:
        command = self.board_command(ctx, command_id)
        script = (
            "set -euo pipefail\n"
            f"echo {shlex.quote(title)}\n"
            f"echo {shlex.quote('run: ' + command)}\n"
            f"{command}\n"
            f"echo {shlex.quote('done: ' + command)}\n"
        )
        return [ctx.command_builder.board_ssh_command(
            config_accessors.board_host_spec_for_config(ctx.config), script,
        )]

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
            power_off = self.board_command(ctx, "power_off")
            boot_mode = self.board_command(ctx, "boot_mode")
            power_on = self.board_command(ctx, "power_on")
            sequence = f"{power_off}, {boot_mode}, {power_on}, picocom"
            restart_script = self.uboot_action_script(ctx, title="Open U-Boot console")
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
            "echo 'Exit picocom with Ctrl-A Ctrl-X.'\n"
            "exec picocom -b 1843200 \"$console\"\n"
        )
        return [
            builder.board_ssh_command(board_host, script, tty=True),
        ]

    def open_board_serial_console_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        return self.board_picocom_command_plan(ctx, title="Open board serial console", restart=False)

    def open_uboot_console_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        return self.board_picocom_command_plan(ctx, title="Open U-Boot console", restart=True)

    def ipl_helper_script(self, ctx: BoardActionContext, *, prepare: bool = False) -> str:
        source = (Path(__file__).resolve().parents[4] / "board_tools/gen5_x5h_flash_ipl.py").read_text()
        args = ["python3", "-u", "-c", source, "--artifacts",
                config_accessors.board_artifacts_dir_for_config(ctx.config)]
        if prepare:
            args.append("--prepare")
        return "set -euo pipefail\n" + shlex.join(args)

    def flash_single_ipl_command_plan(self, ctx: BoardActionContext) -> list[list[str]]:
        if ctx.flash_bootloaders_tool is None:
            raise ValueError("flash bootloader helper tool is not configured")
        builder = ctx.command_builder
        host = config_accessors.board_host_spec_for_config(ctx.config)
        params = ctx.build_params or {}
        flash_all = params.get("_ipl_all") == "true"
        prepare_ipls = params.get("_ipl_prepare") == "true"
        if not flash_all and not params.get("_ipl_names") and not params.get("_ipl_name"):
            return [builder.board_ssh_command(host, self.ipl_helper_script(ctx))]
        names = [] if flash_all else (
            json.loads(params["_ipl_names"]) if params.get("_ipl_names") else [params["_ipl_name"]]
        )
        if not flash_all and (
            not isinstance(names, list)
            or not names
            or any(not isinstance(name, str) or not name for name in names)
        ):
            raise ValueError("selected IPL names must be a nonempty list")
        work_dir = config_accessors.board_work_dir_for_config(ctx.config)
        tools = [ctx.flash_bootloaders_tool.parent / name for name in
                 ("ipl_ufs_flash.py", "gen5_x5h_flash_ipl.py")]
        remote_tool = builder.board_tool_remote_path(work_dir, tools[-1])
        args = ["python3", "-u", str(remote_tool)]
        if flash_all:
            args += ["--artifacts", config_accessors.board_artifacts_dir_for_config(ctx.config), "--all",
                     "--port", config_accessors.board_console_device_for_config(ctx.config),
                     "--tftp-root", config_accessors.board_tftp_root_for_config(ctx.config),
                     "--tftp-dir", work_dir]
        elif names:
            snapshot = params.get("_ipl_snapshot", "")
            if snapshot:
                args += ["--ipls-dir", snapshot]
            elif prepare_ipls:
                args += ["--artifacts", config_accessors.board_artifacts_dir_for_config(ctx.config)]
            else:
                raise ValueError("selected IPL snapshot is required")
            args += ["--port", config_accessors.board_console_device_for_config(ctx.config),
                     "--tftp-root", config_accessors.board_tftp_root_for_config(ctx.config),
                     "--tftp-dir", work_dir]
            for name in names:
                args += ["--name", name]
        prepare_script = (
            "set -euo pipefail\n" + shlex.join(args + ["--check"]) + "\n"
            + self.uboot_action_script(ctx, title="Prepare board for IPL reflash", network=True)
        )
        commands = [
            builder.board_prepare_work_dir_command(host, work_dir),
            *(builder.board_deploy_tool_command(host, work_dir, tool) for tool in tools),
        ]
        if flash_all or prepare_ipls:
            commands.append(builder.board_ssh_command(host, self.ipl_helper_script(ctx, prepare=True)))
        commands.extend([
            builder.board_ssh_command(host, prepare_script, tty=True),
            builder.board_ssh_command(host, "set -euo pipefail\n" + shlex.join(args)),
        ])
        return commands

    def flash_bootloaders_command_plan(
        self,
        ctx: BoardActionContext,
        *,
        board_host: str,
        work_dir: str,
        artifacts_dir: str,
        console: str,
        tool: object,
    ) -> list[list[str]]:
        builder = ctx.command_builder
        remote_tool = builder.board_tool_remote_path(work_dir, tool)
        flash_mode = self.board_command(ctx, "flash_mode")
        boot_mode = self.board_command(ctx, "boot_mode")
        enter_flash_script = (
            "set -euo pipefail\n"
            f"cd {builder.quote_remote_shell_path(work_dir)}\n"
            f"echo {shlex.quote('run: ' + flash_mode)}\n"
            f"{flash_mode}\n"
            f"echo {shlex.quote('done: ' + flash_mode)}\n"
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
            f"console={shlex.quote(console)}\n"
            "if [ -z \"$console\" ]; then console=$(ls -1 /dev/GEN5_CONSOLE* 2>/dev/null | head -n 1 || true); fi\n"
            "if [ -z \"$console\" ]; then echo 'GEN5 console device not found under /dev/GEN5_CONSOLE*' >&2; exit 2; fi\n"
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
            "echo 'GEN5 console: '\"$console\"\n"
            "PYTHONUNBUFFERED=1 python3 -u ./flash_bootloaders.py --port \"$console\" --config x5h_bootloaders.yaml --mode all\n"
            "echo 'bootloader flasher done'\n"
            f"echo {shlex.quote('run: ' + boot_mode)}\n"
            f"{boot_mode}\n"
            f"echo {shlex.quote('done: ' + boot_mode)}\n"
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
        power_off_script = self.board_command_script(ctx, "power_off", "board power")
        power_on_script = self.board_command_script(ctx, "power_on", "board power")
        boot_mode_script = self.board_command_script(ctx, "boot_mode", "board boot mode")
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
            f"{power_off_script}"
            "sleep 1\n"
            f"{power_on_script}"
            "sleep 1\n"
            f"{boot_mode_script}"
            f"{self.board_command_script(ctx, 'power_off', 'board power after boot mode')}"
            "sleep 1\n"
            f"{self.board_command_script(ctx, 'power_on', 'board power after boot mode')}"
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
