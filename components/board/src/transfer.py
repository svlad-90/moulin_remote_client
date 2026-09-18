"""Board artifact transfer command service."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Callable

from components.config.api import accessors as config_accessors
from components.moulin.api import manifest as moulin_manifest


class BoardArtifactTransferService:
    """Own the copy-build-artifacts use case for board hosts."""

    def __init__(
        self,
        *,
        command_builder: Any,
        app_dir: Path,
        default_moulin_manifest: str,
        remote_read_project_file: Callable[[dict[str, Any], str], str],
        manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    ) -> None:
        self.command_builder = command_builder
        self.app_dir = app_dir
        self.default_moulin_manifest = default_moulin_manifest
        self.remote_read_project_file = remote_read_project_file
        self.manifest_cache = manifest_cache

    def shell_array_assignment(self, name: str, values: list[str]) -> str:
        return f"{name}=(" + " ".join(shlex.quote(value) for value in values) + ")"

    def artifact_resolver_script(self, source_dir: str, specs: list[dict[str, str]]) -> str:
        label_array = self.shell_array_assignment("requested_labels", [spec["label"] for spec in specs])
        path_array = self.shell_array_assignment("requested_paths", [spec["path"] for spec in specs])
        return (
            "set -euo pipefail\n"
            f"cd {shlex.quote(source_dir)}\n"
            "source_root=$PWD\n"
            f"{label_array}\n"
            f"{path_array}\n"
            "resolved_artifacts=()\n"
            "resolved_tar_args=()\n"
            "total_bytes=0\n"
            "echo 'resolved artifacts:' >&2\n"
            "for index in \"${!requested_paths[@]}\"; do\n"
            "  label=${requested_labels[$index]}\n"
            "  artifact=${requested_paths[$index]}\n"
            "  found=''\n"
            "  if [ -e \"$artifact\" ]; then\n"
            "    found=\"$artifact\"\n"
            "  else\n"
            "    found=$(find . -path \"*/$artifact\" -print -quit)\n"
            "    found=${found#./}\n"
            "  fi\n"
            "  if [ -z \"$found\" ] || [ ! -e \"$found\" ]; then\n"
            "    printf 'missing artifact: %s under %s\\n' \"$artifact\" \"$PWD\" >&2\n"
            "    exit 2\n"
            "  fi\n"
            "  size=$(du -sb -- \"$found\" | awk '{print $1}')\n"
            "  total_bytes=$((total_bytes + size))\n"
            "  printf '  %s: %s -> %s (%s bytes)\\n' \"$label\" \"$artifact\" \"$found\" \"$size\" >&2\n"
            "  resolved_artifacts+=(\"$found\")\n"
            "  found_dir=$(dirname \"$found\")\n"
            "  case \"$found_dir\" in\n"
            "    /*) tar_dir=$found_dir ;;\n"
            "    *) tar_dir=$source_root/$found_dir ;;\n"
            "  esac\n"
            "  resolved_tar_args+=(-C \"$tar_dir\" \"$(basename \"$found\")\")\n"
            "done\n"
            "printf 'total input size: %s bytes\\n' \"$total_bytes\" >&2\n"
        )

    def tar_progress_command(self, destination: str, destination_script: str) -> str:
        python_script = r"""
import os
import signal
import subprocess
import sys
import time

destination = os.environ["BOARD_COPY_DESTINATION"]
destination_script = os.environ["BOARD_COPY_DESTINATION_SCRIPT"]
total = max(1, int(os.environ.get("BOARD_COPY_TOTAL_BYTES", "1")))
tar_args = sys.argv[1:]
ssh = subprocess.Popen(
    ["ssh", "-o", "StrictHostKeyChecking=accept-new", destination, destination_script],
    stdin=subprocess.PIPE,
    start_new_session=True,
)
tar = subprocess.Popen(["tar", "-cf", "-", *tar_args], stdout=subprocess.PIPE, start_new_session=True)
copied = 0
last_reported = -1
last_time = 0.0
try:
    assert tar.stdout is not None
    assert ssh.stdin is not None
    while True:
        chunk = tar.stdout.read(1024 * 1024)
        if not chunk:
            break
        ssh.stdin.write(chunk)
        copied += len(chunk)
        now = time.monotonic()
        pct = min(100, int(copied * 100 / total))
        if pct != last_reported and (pct == 100 or now - last_time >= 1.0):
            print(f"progress: {pct}% ({copied}/{total} bytes)", flush=True)
            last_reported = pct
            last_time = now
    ssh.stdin.close()
finally:
    if tar.stdout is not None:
        tar.stdout.close()
tar_rc = tar.wait()
ssh_rc = ssh.wait()
if tar_rc != 0:
    sys.exit(tar_rc)
sys.exit(ssh_rc)
"""
        env_prefix = (
            f"BOARD_COPY_DESTINATION={shlex.quote(destination)} "
            f"BOARD_COPY_DESTINATION_SCRIPT={shlex.quote(destination_script)} "
            'BOARD_COPY_TOTAL_BYTES="$total_bytes" '
        )
        return env_prefix + f"python3 -c {shlex.quote(python_script)} " + '"${resolved_tar_args[@]}"'

    def copy_build_artifacts_command_plan(
        self,
        *,
        artifact_targets: list[str],
        artifact_specs: list[dict[str, str]],
        build_host: str,
        board_host: str,
        source_dir: str,
        destination_dir: str,
        direct_copy: bool,
    ) -> list[list[str]]:
        builder = self.command_builder
        clean_targets = [target.strip().strip("/") for target in artifact_targets if target.strip().strip("/")]
        if not clean_targets:
            return [builder.local_log_command("No board artifacts configured", exit_code=1)]
        route = "direct build-host -> board-host" if direct_copy else "via client machine"
        describe_script = (
            "echo 'Copy build artifacts' >&2\n"
            f"echo 'route: {route}' >&2\n"
            f"echo 'from: {build_host}:{source_dir}' >&2\n"
            f"echo 'to:   {board_host}:{destination_dir}' >&2\n"
            "echo 'artifacts:' >&2\n"
            + "".join(f"echo '  {spec['label']}: {spec['path']} ({spec['source']})' >&2\n" for spec in artifact_specs)
        )
        destination_script = (
            f"mkdir -p {builder.quote_remote_shell_path(destination_dir)} && "
            f"cd {builder.quote_remote_shell_path(destination_dir)} && tar -xf -"
        )
        resolver_script = self.artifact_resolver_script(source_dir, artifact_specs)
        if direct_copy:
            board_destination_command = shlex.quote(destination_script)
            python_progress_command = self.tar_progress_command(board_host, destination_script)
            direct_script = (
                describe_script
                + resolver_script
                + "echo 'transfer: tar stream build-host -> board-host' >&2\n"
                + "if command -v pv >/dev/null 2>&1; then\n"
                + f"  tar -cf - \"${{resolved_tar_args[@]}}\" | pv -n -s \"$total_bytes\" 2> >(while read -r pct; do printf 'progress: %s%%\\n' \"$pct\" >&2; done) | ssh -o StrictHostKeyChecking=accept-new {shlex.quote(board_host)} {board_destination_command}\n"
                + "else\n"
                + "  echo 'progress: pv not found on build host; using python byte progress' >&2\n"
                + f"  {python_progress_command}\n"
                + "fi\n"
                + "echo 'transfer: done' >&2\n"
            )
            return [
                [
                    "ssh",
                    build_host,
                    f"bash -lc {shlex.quote(direct_script)}",
                ],
            ]
        source_script = (
            describe_script
            + resolver_script
            + "echo 'transfer: tar stream build-host -> client -> board-host' >&2\n"
            + "if command -v pv >/dev/null 2>&1; then\n"
            + "  tar -cf - \"${resolved_tar_args[@]}\" | pv -n -s \"$total_bytes\" 2> >(while read -r pct; do printf 'progress: %s%%\\n' \"$pct\" >&2; done)\n"
            + "else\n"
            + "  echo 'progress: pv not found on build host; streaming without byte progress' >&2\n"
            + "  tar -cf - \"${resolved_tar_args[@]}\"\n"
            + "fi\n"
        )
        remote_source_command = f"bash -lc {shlex.quote(source_script)}"
        copy_script = (
            "set -o pipefail; "
            f"ssh {shlex.quote(build_host)} {shlex.quote(remote_source_command)} | "
            f"ssh {shlex.quote(board_host)} {shlex.quote(destination_script)}"
        )
        return [
            builder.board_prepare_work_dir_command(board_host, destination_dir),
            ["bash", "-lc", copy_script],
        ]

    def copy_build_artifacts_commands(
        self,
        config: dict[str, Any],
        *,
        artifact_targets: str,
        build_params: dict[str, str],
    ) -> list[list[str]]:
        builder = self.command_builder
        targets = shlex.split(artifact_targets)
        clean_targets = [target.strip().strip("/") for target in targets if target.strip().strip("/")]
        if not clean_targets:
            return [builder.local_log_command("No board artifacts configured", exit_code=1)]
        specs = moulin_manifest.artifact_copy_specs_for_config(
            config,
            clean_targets,
            app_dir=self.app_dir,
            remote_read_project_file=self.remote_read_project_file,
            cache=self.manifest_cache,
            default_moulin_manifest=self.default_moulin_manifest,
            build_params=build_params,
        )
        return self.copy_build_artifacts_command_plan(
            artifact_targets=clean_targets,
            artifact_specs=specs,
            build_host=config_accessors.remote_spec_for_config(config),
            board_host=config_accessors.board_host_spec_for_config(config),
            source_dir=config_accessors.remote_project_dir_for_config(config),
            destination_dir=config_accessors.board_artifacts_dir_for_config(config),
            direct_copy=config_accessors.board_direct_copy_enabled_for_config(config),
        )


def board_artifact_transfer_service(
    *,
    command_builder: Any,
    app_dir: Path,
    default_moulin_manifest: str,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
) -> BoardArtifactTransferService:
    return BoardArtifactTransferService(
        command_builder=command_builder,
        app_dir=app_dir,
        default_moulin_manifest=default_moulin_manifest,
        remote_read_project_file=remote_read_project_file,
        manifest_cache=manifest_cache,
    )
