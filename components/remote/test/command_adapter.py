from __future__ import annotations

import shlex
from typing import Any, Callable

from components.board.api.session import board_session_command_service
from components.config.api import accessors as config_accessors
from components.remote.api import build as remote_build_api
from components.remote.api import discovery as remote_discovery_api
from components.remote.api import project as remote_project_api
from components.remote.api import workflow as remote_workflow_api
from components.remote.src.session import RemoteSessionCommandService, remote_session_command_service
from components.remote.api import transport


class commands:
    RemoteBuildCommandService = remote_build_api.RemoteBuildCommandService
    RemoteProjectDiscoveryService = remote_discovery_api.RemoteProjectDiscoveryService
    RemoteProjectMaintenanceService = remote_project_api.RemoteProjectMaintenanceService
    RemoteSessionCommandService = RemoteSessionCommandService

    @staticmethod
    def _session() -> RemoteSessionCommandService:
        return remote_session_command_service()

    @staticmethod
    def _discovery() -> remote_discovery_api.RemoteProjectDiscoveryService:
        return remote_discovery_api.remote_project_discovery_service()

    @staticmethod
    def _project() -> remote_project_api.RemoteProjectMaintenanceService:
        return remote_project_api.remote_project_maintenance_service()

    @staticmethod
    def _build() -> remote_build_api.RemoteBuildCommandService:
        return remote_build_api.remote_build_command_service()

    @staticmethod
    def _workflow(
        *,
        default_dockerfile: str = "",
        default_moulin_manifest: str = "",
    ) -> remote_workflow_api.RemoteCommandWorkflowService:
        return remote_workflow_api.remote_command_workflow_service(
            default_dockerfile=default_dockerfile,
            default_moulin_manifest=default_moulin_manifest,
        )

    @staticmethod
    def build_remote_connect_command(remote: str, project_dir: str = "") -> list[str]:
        return commands._session().connect_command(remote, project_dir)

    @staticmethod
    def build_remote_connect_command_for_config(config: dict[str, Any]) -> list[str]:
        return commands._session().connect_command_for_config(config)

    @staticmethod
    def build_board_host_connect_command(board_host: str) -> list[str]:
        return board_session_command_service().connect_command(board_host)

    @staticmethod
    def build_interactive_remote_shell_command(remote: str, project_dir: str) -> list[str]:
        return commands._session().interactive_shell_command(remote, project_dir)

    @staticmethod
    def build_interactive_remote_shell_command_for_config(config: dict[str, Any]) -> list[str]:
        return commands._session().interactive_shell_command_for_config(config)

    @staticmethod
    def run_interactive_remote_shell_for_config(
        config: dict[str, Any],
        runner: Callable[[list[str]], Any],
    ) -> Any:
        return commands._session().run_interactive_shell(config, runner)

    @staticmethod
    def build_remote_project_file_read_command_for_config(config: dict[str, Any], path: str) -> list[str]:
        return commands._discovery().build_project_file_read_command_for_config(config, path)

    @staticmethod
    def read_project_file_for_config(
        config: dict[str, Any],
        path: str,
        runner: Callable[[list[str]], str],
    ) -> str:
        return commands._discovery().read_project_file_for_config(config, path, runner)

    @staticmethod
    def project_file_reader(runner: Callable[[list[str]], str]) -> Callable[[dict[str, Any], str], str]:
        return commands._discovery().project_file_reader(runner)

    @staticmethod
    def build_remote_status_probe_command_for_config(config: dict[str, Any]) -> list[str]:
        remote = config_accessors.remote_spec_for_config(config)
        project_dir = config_accessors.remote_project_dir_for_config(config)
        remote_cmd = f"cd {shlex.quote(project_dir)} && pwd && df -h . && git status --short --branch || true"
        return transport.ssh_command(remote, remote_cmd)

    @staticmethod
    def build_inventory_command(project_dir: str, excludes: list[str], max_depth: int) -> str:
        return commands._discovery().build_inventory_command(project_dir, excludes, max_depth)

    @staticmethod
    def build_inventory_command_for_config(config: dict[str, Any]) -> str:
        return commands._discovery().build_inventory_command_for_config(config)

    @staticmethod
    def build_inventory_fetch_command_for_config(config: dict[str, Any]) -> list[str]:
        return commands._discovery().build_inventory_fetch_command_for_config(config)

    @staticmethod
    def build_project_tree_command(project_dir: str, excludes: list[str], depth: int) -> str:
        return commands._discovery().build_project_tree_command(project_dir, excludes, depth)

    @staticmethod
    def build_project_tree_command_for_config(config: dict[str, Any], depth: int) -> str:
        return commands._discovery().build_project_tree_command_for_config(config, depth)

    @staticmethod
    def build_project_tree_fetch_command_for_config(config: dict[str, Any], depth: int) -> list[str]:
        return commands._discovery().build_project_tree_fetch_command_for_config(config, depth)

    @staticmethod
    def fetch_project_tree_for_config(
        config: dict[str, Any],
        depth: int,
        runner: Callable[[list[str]], str],
    ) -> list[dict[str, str]]:
        return commands._discovery().fetch_project_tree_for_config(config, depth, runner)

    @staticmethod
    def build_project_listing_command(project_dir: str, excludes: list[str], directory: str) -> str:
        return commands._discovery().build_project_listing_command(project_dir, excludes, directory)

    @staticmethod
    def build_project_listing_command_for_config(config: dict[str, Any], directory: str) -> str:
        return commands._discovery().build_project_listing_command_for_config(config, directory)

    @staticmethod
    def build_project_listing_fetch_command_for_config(config: dict[str, Any], directory: str) -> list[str]:
        return commands._discovery().build_project_listing_fetch_command_for_config(config, directory)

    @staticmethod
    def fetch_project_listing_for_config(
        config: dict[str, Any],
        directory: str,
        runner: Callable[[list[str]], str],
    ) -> list[dict[str, str]]:
        return commands._discovery().fetch_project_listing_for_config(config, directory, runner)

    @staticmethod
    def build_remote_child_dirs_fetch_command_for_config(config: dict[str, Any], path: str) -> list[str]:
        return commands._discovery().build_remote_child_dirs_fetch_command_for_config(config, path)

    @staticmethod
    def parse_remote_child_dirs_output(path: str, output: str) -> list[str]:
        return commands._discovery().parse_remote_child_dirs_output(path, output)

    @staticmethod
    def fetch_remote_child_dirs_for_config(
        config: dict[str, Any],
        path: str,
        runner: Callable[[list[str]], str],
    ) -> list[str]:
        return commands._discovery().fetch_remote_child_dirs_for_config(config, path, runner)

    @staticmethod
    def build_remote_home_fetch_command_for_config(config: dict[str, Any]) -> list[str]:
        return commands._discovery().build_remote_home_fetch_command_for_config(config)

    @staticmethod
    def remote_home_from_output(output: str) -> str:
        return commands._discovery().remote_home_from_output(output)

    @staticmethod
    def fetch_remote_home_for_config(config: dict[str, Any], runner: Callable[[list[str]], str]) -> str:
        return commands._discovery().fetch_remote_home_for_config(config, runner)

    @staticmethod
    def remote_parent_dir(path: str, home: str = "~") -> str:
        return commands._discovery().remote_parent_dir(path, home)

    @staticmethod
    def parse_project_tree_output(output: str) -> list[dict[str, str]]:
        return commands._discovery().parse_project_tree_output(output)

    @staticmethod
    def parse_project_listing_output(output: str) -> list[dict[str, str]]:
        return commands._discovery().parse_project_listing_output(output)

    @staticmethod
    def build_git_tracked_files_fetch_command_for_config(config: dict[str, Any]) -> list[str]:
        return commands._discovery().build_git_tracked_files_fetch_command_for_config(config)

    @staticmethod
    def parse_git_tracked_files(output: str) -> list[str]:
        return commands._discovery().parse_git_tracked_files(output)

    @staticmethod
    def fetch_git_tracked_files_for_config(
        config: dict[str, Any],
        runner: Callable[[list[str]], str],
    ) -> list[str]:
        return commands._discovery().fetch_git_tracked_files_for_config(config, runner)

    @staticmethod
    def root_yaml_candidates(paths: list[str]) -> list[str]:
        return commands._discovery().root_yaml_candidates(paths)

    @staticmethod
    def dockerfile_candidates(paths: list[str]) -> list[str]:
        return commands._discovery().dockerfile_candidates(paths)

    @staticmethod
    def validate_dockerfile_text(text: str) -> tuple[bool, str]:
        return commands._discovery().validate_dockerfile_text(text)

    @staticmethod
    def build_git_branch_list_fetch_command_for_config(config: dict[str, Any], git_url: str) -> list[str]:
        return commands._discovery().build_git_branch_list_fetch_command_for_config(config, git_url)

    @staticmethod
    def parse_git_branch_list_output(output: str) -> list[str]:
        return commands._discovery().parse_git_branch_list_output(output)

    @staticmethod
    def fetch_git_branches_for_config(
        config: dict[str, Any],
        git_url: str,
        runner: Callable[[list[str]], str],
    ) -> list[str]:
        return commands._discovery().fetch_git_branches_for_config(config, git_url, runner)

    @staticmethod
    def build_remote_prepare_project_command(remote: str, project_dir: str, git_url: str, git_ref: str) -> list[str]:
        return commands._project().prepare_project_command(remote, project_dir, git_url, git_ref)

    @staticmethod
    def build_remote_prepare_project_command_for_config(config: dict[str, Any]) -> list[str]:
        return commands._project().prepare_project_command_for_config(config)

    @staticmethod
    def build_remote_checkout_git_ref_command_for_config(config: dict[str, Any]) -> list[str]:
        return commands._project().checkout_git_ref_command_for_config(config)

    @staticmethod
    def build_remote_preflight_command_for_config(config: dict[str, Any], docker_image: str) -> list[str]:
        return commands._project().preflight_command_for_config(config, docker_image)

    @staticmethod
    def build_remote_docker_command_for_config(
        config: dict[str, Any],
        *,
        docker_image: str,
        default_dockerfile: str,
    ) -> list[str]:
        return commands._build().docker_command_for_config(
            config,
            docker_image=docker_image,
            default_dockerfile=default_dockerfile,
        )

    @staticmethod
    def build_remote_docker_command(remote: str, project_dir: str, docker_image: str, dockerfile: str) -> list[str]:
        return commands._build().docker_command(remote, project_dir, docker_image, dockerfile)

    @staticmethod
    def run_remote_docker_for_config(
        config: dict[str, Any],
        *,
        docker_image: str,
        default_dockerfile: str,
        runner: Callable[[list[str]], Any],
    ) -> Any:
        return commands._build().run_docker_for_config(
            config,
            docker_image=docker_image,
            default_dockerfile=default_dockerfile,
            runner=runner,
        )

    @staticmethod
    def build_product_docker_command(project_dir: str, docker_image: str, inner_command: str) -> str:
        return commands._build().product_docker_command(project_dir, docker_image, inner_command)

    @staticmethod
    def build_remote_moulin_command_for_config(
        config: dict[str, Any],
        *,
        docker_image: str,
        default_moulin_manifest: str,
        build_params: dict[str, str],
    ) -> list[str]:
        return commands._build().moulin_command_for_config(
            config,
            docker_image=docker_image,
            default_moulin_manifest=default_moulin_manifest,
            build_params=build_params,
        )

    @staticmethod
    def build_remote_moulin_command(
        remote: str,
        project_dir: str,
        docker_image: str,
        manifest_name: str,
        build_params: dict[str, str],
    ) -> list[str]:
        return commands._build().moulin_command(remote, project_dir, docker_image, manifest_name, build_params)

    @staticmethod
    def run_remote_moulin_for_config(
        config: dict[str, Any],
        *,
        docker_image: str,
        default_moulin_manifest: str,
        build_params: dict[str, str],
        runner: Callable[[list[str]], Any],
    ) -> Any:
        return commands._build().run_moulin_for_config(
            config,
            docker_image=docker_image,
            default_moulin_manifest=default_moulin_manifest,
            build_params=build_params,
            runner=runner,
        )

    @staticmethod
    def build_remote_build_command_for_config(
        config: dict[str, Any],
        *,
        docker_image: str,
        targets: str,
    ) -> list[str]:
        return commands._build().build_command_for_config(config, docker_image=docker_image, targets=targets)

    @staticmethod
    def build_remote_build_command(remote: str, project_dir: str, docker_image: str, targets: str) -> list[str]:
        return commands._build().build_command(remote, project_dir, docker_image, targets)

    @staticmethod
    def build_remote_bazel_config_command_for_config(
        config: dict[str, Any],
        *,
        docker_image: str,
        targets: str,
    ) -> list[str]:
        return commands._build().bazel_config_command_for_config(config, docker_image=docker_image, targets=targets)

    @staticmethod
    def build_remote_bazel_component_command_for_config(
        config: dict[str, Any],
        *,
        docker_image: str,
        component: dict[str, Any],
    ) -> list[str]:
        return commands._build().bazel_component_command_for_config(
            config,
            docker_image=docker_image,
            component=component,
        )

    @staticmethod
    def run_remote_build_for_config(
        config: dict[str, Any],
        *,
        docker_image: str,
        targets: str,
        runner: Callable[[list[str]], Any],
    ) -> Any:
        return commands._build().run_build_for_config(
            config,
            docker_image=docker_image,
            targets=targets,
            runner=runner,
        )

    @staticmethod
    def build_structured_script(steps: list[tuple[str, str]], *, fail_fast: bool = False) -> str:
        return commands._workflow().structured_script(steps, fail_fast=fail_fast)

    @staticmethod
    def build_remote_status_command_for_config(
        config: dict[str, Any],
        *,
        docker_image: str,
        structured_script: Callable[[list[tuple[str, str]]], str],
    ) -> list[str]:
        return commands._build().status_command_for_config(
            config,
            docker_image=docker_image,
            structured_script=structured_script,
        )

    @staticmethod
    def run_remote_status_for_config(
        config: dict[str, Any],
        *,
        docker_image: str,
        structured_script: Callable[[list[tuple[str, str]]], str],
        runner: Callable[[list[str]], Any],
    ) -> Any:
        return commands._build().run_status_for_config(
            config,
            docker_image=docker_image,
            structured_script=structured_script,
            runner=runner,
        )

    @staticmethod
    def run_cli_remote_command_for_config(
        config: dict[str, Any],
        command: str,
        *,
        runtime_context: Callable[[], dict[str, Any]],
        default_dockerfile: str,
        default_moulin_manifest: str,
        structured_script: Callable[[list[tuple[str, str]]], str],
        runner: Callable[[list[str]], Any],
        status_runner: Callable[[list[str]], Any] | None = None,
    ) -> None:
        commands._workflow(
            default_dockerfile=default_dockerfile,
            default_moulin_manifest=default_moulin_manifest,
        ).run_cli_command(
            config,
            command,
            runtime_context=runtime_context,
            structured_script=structured_script,
            runner=runner,
            status_runner=status_runner,
        )
