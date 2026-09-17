"""Build-host command workflow service."""

from __future__ import annotations

import shlex
from typing import Any, Callable

from components.remote.src import build as remote_build
from components.remote.src import project as remote_project
from components.remote.src import session as remote_session


REMOTE_CLI_COMMANDS = {
    "connect",
    "server-tui",
    "remote-status",
    "build-docker",
    "regen-moulin",
    "build",
    "yocto-impact",
    "yocto-impact-clean",
    "yocto-impact-rebuild",
    "yocto-impact-clean-rebuild",
}

YOCTO_IMPACT_ACTIONS = {
    "yocto-impact": "analyze",
    "yocto-impact-clean": "clean",
    "yocto-impact-rebuild": "rebuild",
    "yocto-impact-clean-rebuild": "clean-rebuild",
}


class RemoteCommandWorkflowService:
    """Provide build-host command use cases to other components."""

    def __init__(
        self,
        *,
        default_dockerfile: str,
        default_moulin_manifest: str,
    ) -> None:
        self.default_dockerfile = default_dockerfile
        self.default_moulin_manifest = default_moulin_manifest
        self.session_service = remote_session.remote_session_command_service()
        self.project_service = remote_project.remote_project_maintenance_service()
        self.build_service = remote_build.remote_build_command_service()

    def supports_cli_command(self, command: str) -> bool:
        return command in REMOTE_CLI_COMMANDS

    def structured_script(self, steps: list[tuple[str, str]], *, fail_fast: bool = False) -> str:
        parts = ["overall_rc=0"]
        for title, command in steps:
            quoted_title = shlex.quote(title)
            parts.extend(
                [
                    f"printf '\\n== %s ==\\n' {quoted_title}",
                    f"printf 'cmd: %s\\n' {shlex.quote(command)}",
                    command,
                    "step_rc=$?",
                    "printf 'exit: %s\\n' \"$step_rc\"",
                    "if [ \"$step_rc\" -ne 0 ]; then overall_rc=\"$step_rc\"; fi",
                ]
            )
            if fail_fast:
                parts.append("if [ \"$step_rc\" -ne 0 ]; then exit \"$step_rc\"; fi")
        parts.append("exit \"$overall_rc\"")
        return "; ".join(parts)

    def connect_command(self, config: dict[str, Any]) -> list[str]:
        return self.session_service.connect_command_for_config(config)

    def interactive_shell_command(self, config: dict[str, Any]) -> list[str]:
        return self.session_service.interactive_shell_command_for_config(config)

    def run_interactive_shell(
        self,
        config: dict[str, Any],
        runner: Callable[[list[str]], Any],
    ) -> Any:
        return self.session_service.run_interactive_shell(config, runner)

    def prepare_project_command(self, config: dict[str, Any]) -> list[str]:
        return self.project_service.prepare_project_command_for_config(config)

    def checkout_git_ref_command(self, config: dict[str, Any]) -> list[str]:
        return self.project_service.checkout_git_ref_command_for_config(config)

    def docker_image_command(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
    ) -> list[str]:
        return self.build_service.docker_command_for_config(
            config,
            docker_image=docker_image,
            default_dockerfile=self.default_dockerfile,
        )

    def moulin_regen_command(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        build_params: dict[str, str],
    ) -> list[str]:
        return self.build_service.moulin_command_for_config(
            config,
            docker_image=docker_image,
            default_moulin_manifest=self.default_moulin_manifest,
            build_params=build_params,
        )

    def product_build_command(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        targets: str,
    ) -> list[str]:
        return self.build_service.build_command_for_config(
            config,
            docker_image=docker_image,
            targets=targets,
        )

    def ninja_tool_command(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        args: str,
    ) -> list[str]:
        return self.build_service.ninja_tool_command_for_config(
            config,
            docker_image=docker_image,
            args=args,
        )

    def yocto_impact_command(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        targets: str,
        action: str = "analyze",
        image_recipes: list[str] | None = None,
        allow_empty: bool = False,
    ) -> list[str]:
        return self.build_service.yocto_impact_command_for_config(
            config,
            docker_image=docker_image,
            targets=targets,
            action=action,
            image_recipes=image_recipes,
            allow_empty=allow_empty,
        )

    def run_docker_image(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        runner: Callable[[list[str]], Any],
    ) -> None:
        runner(self.docker_image_command(config, docker_image=docker_image))

    def run_moulin_regen(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        build_params: dict[str, str],
        runner: Callable[[list[str]], Any],
    ) -> None:
        runner(
            self.moulin_regen_command(
                config,
                docker_image=docker_image,
                build_params=build_params,
            )
        )

    def run_product_build(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        targets: str,
        runner: Callable[[list[str]], Any],
    ) -> None:
        runner(
            self.product_build_command(
                config,
                docker_image=docker_image,
                targets=targets,
            )
        )

    def status_command(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        structured_script: Callable[[list[tuple[str, str]]], str],
    ) -> list[str]:
        return self.build_service.status_command_for_config(
            config,
            docker_image=docker_image,
            structured_script=structured_script,
        )

    def run_status(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        structured_script: Callable[[list[tuple[str, str]]], str],
        runner: Callable[[list[str]], Any],
    ) -> None:
        runner(
            self.status_command(
                config,
                docker_image=docker_image,
                structured_script=structured_script,
            )
        )

    def run_cli_command(
        self,
        config: dict[str, Any],
        command: str,
        *,
        runtime_context: Callable[[], dict[str, Any]],
        structured_script: Callable[[list[tuple[str, str]]], str],
        runner: Callable[[list[str]], Any],
        status_runner: Callable[[list[str]], Any] | None = None,
    ) -> None:
        if command in {"connect", "server-tui"}:
            self.run_interactive_shell(config, runner)
            return
        context = runtime_context()
        docker_image = str(context["docker_image"])
        if command == "remote-status":
            self.run_status(
                config,
                docker_image=docker_image,
                structured_script=structured_script,
                runner=status_runner or runner,
            )
            return
        if command == "build-docker":
            self.run_docker_image(config, docker_image=docker_image, runner=runner)
            return
        if command == "regen-moulin":
            self.run_moulin_regen(
                config,
                docker_image=docker_image,
                build_params=dict(context["build_params"]),
                runner=runner,
            )
            return
        if command == "build":
            self.run_product_build(
                config,
                docker_image=docker_image,
                targets=str(context["build_targets"]),
                runner=runner,
            )
            return
        if command in YOCTO_IMPACT_ACTIONS:
            runner(
                self.yocto_impact_command(
                    config,
                    docker_image=docker_image,
                    targets=str(context["build_targets"]),
                    action=YOCTO_IMPACT_ACTIONS[command],
                )
            )
            return
        raise ValueError(f"unsupported remote command: {command}")


def remote_command_workflow_service(
    *,
    default_dockerfile: str,
    default_moulin_manifest: str,
) -> RemoteCommandWorkflowService:
    return RemoteCommandWorkflowService(
        default_dockerfile=default_dockerfile,
        default_moulin_manifest=default_moulin_manifest,
    )
