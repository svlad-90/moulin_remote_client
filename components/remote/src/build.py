"""Remote build command service."""

from __future__ import annotations

import shlex
from pathlib import PurePosixPath
from typing import Any, Callable

from components.config.api import accessors as config_accessors
from components.remote.src import session as remote_session


class RemoteBuildCommandService:
    """Own build-host Docker, Moulin, Ninja, and status command use cases."""

    def __init__(self) -> None:
        self.session_service = remote_session.remote_session_command_service()

    def docker_command(self, remote: str, project_dir: str, docker_image: str, dockerfile: str) -> list[str]:
        if not docker_image:
            raise SystemExit("Docker image name is not configured")
        if not dockerfile:
            raise SystemExit("Dockerfile is not configured")
        dockerfile_path = PurePosixPath(dockerfile)
        context = "." if str(dockerfile_path.parent) == "." else str(dockerfile_path.parent)
        command = (
            f"docker build {shlex.quote(context)} -f {shlex.quote(dockerfile)} "
            '--build-arg "USER_ID=$(id -u)" '
            '--build-arg "USER_GID=$(id -g)" '
            f"-t {shlex.quote(docker_image + ':latest')}"
        )
        return self.session_service.remote_shell_command(remote, project_dir, command)

    def docker_command_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        default_dockerfile: str,
    ) -> list[str]:
        return self.docker_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            docker_image,
            config_accessors.configured_dockerfile_for_config(config, default_dockerfile),
        )

    def run_docker_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        default_dockerfile: str,
        runner: Callable[[list[str]], Any],
    ) -> None:
        runner(
            self.docker_command_for_config(
                config,
                docker_image=docker_image,
                default_dockerfile=default_dockerfile,
            )
        )

    def product_docker_command(self, project_dir: str, docker_image: str, inner_command: str) -> str:
        workspace = shlex.quote(project_dir)
        image = shlex.quote(docker_image)
        inner = shlex.quote(f"cd /home/builder/workspace && {inner_command}")
        return (
            "docker run --network=host --privileged --security-opt apparmor=unconfined "
            '-v "$HOME"/.ssh:/home/builder/.ssh '
            '--mount type=bind,source="$HOME"/.gitconfig,target=/home/builder/.gitconfig '
            '--mount type=bind,source="$HOME"/.git-credentials,target=/home/builder/.git-credentials '
            f"-v {workspace}:/home/builder/workspace "
            f"-i --rm {image} /bin/bash -lc {inner}"
        )

    def product_docker_command_for_config(self, config: dict[str, Any], docker_image: str, inner_command: str) -> str:
        return self.product_docker_command(
            config_accessors.remote_project_dir_for_config(config),
            docker_image,
            inner_command,
        )

    def moulin_command(
        self,
        remote: str,
        project_dir: str,
        docker_image: str,
        manifest_name: str,
        build_params: dict[str, str],
    ) -> list[str]:
        params = " ".join(
            f"--{shlex.quote(name)} {shlex.quote(value)}"
            for name, value in sorted(build_params.items())
        )
        inner = f"moulin {shlex.quote(manifest_name)}" + (f" {params}" if params else "")
        return self.session_service.remote_shell_command(
            remote,
            project_dir,
            self.product_docker_command(project_dir, docker_image, inner),
        )

    def moulin_command_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        default_moulin_manifest: str,
        build_params: dict[str, str],
    ) -> list[str]:
        return self.moulin_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            docker_image,
            config_accessors.moulin_manifest_name_for_config(config, default_moulin_manifest),
            build_params=build_params,
        )

    def run_moulin_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        default_moulin_manifest: str,
        build_params: dict[str, str],
        runner: Callable[[list[str]], Any],
    ) -> None:
        runner(
            self.moulin_command_for_config(
                config,
                docker_image=docker_image,
                default_moulin_manifest=default_moulin_manifest,
                build_params=build_params,
            )
        )

    def build_command(self, remote: str, project_dir: str, docker_image: str, targets: str) -> list[str]:
        quoted_targets = " ".join(shlex.quote(target) for target in shlex.split(targets))
        return self.session_service.remote_shell_command(
            remote,
            project_dir,
            self.product_docker_command(project_dir, docker_image, f"ninja {quoted_targets}"),
        )

    def build_command_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        targets: str,
    ) -> list[str]:
        return self.build_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            docker_image,
            targets,
        )

    def run_build_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        targets: str,
        runner: Callable[[list[str]], Any],
    ) -> None:
        runner(self.build_command_for_config(config, docker_image=docker_image, targets=targets))

    def status_command_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        structured_script: Callable[[list[tuple[str, str]]], str],
    ) -> list[str]:
        docker_cmd = (
            "docker image ls " + shlex.quote(f"{docker_image}:latest")
            if docker_image
            else "printf 'Docker image is not configured\\n'"
        )
        command = structured_script(
            [
                ("Project directory", "pwd"),
                ("Disk usage", "df -h ."),
                ("Git status", "git status --short --branch"),
                ("Docker image", docker_cmd),
            ]
        )
        return self.session_service.remote_shell_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            command,
        )

    def run_status_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        structured_script: Callable[[list[tuple[str, str]]], str],
        runner: Callable[[list[str]], Any],
    ) -> None:
        runner(
            self.status_command_for_config(
                config,
                docker_image=docker_image,
                structured_script=structured_script,
            )
        )

def remote_build_command_service() -> RemoteBuildCommandService:
    return RemoteBuildCommandService()
