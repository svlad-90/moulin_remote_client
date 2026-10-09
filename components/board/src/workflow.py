"""Board-host command workflow service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.board.src.builder import board_command_builder
from components.board.src.flash import board_flash_command_service
from components.board.src.session import board_session_command_service
from components.board.src.transfer import board_artifact_transfer_service
from components.board_types.api import base as board_type_base_api
from components.board_types.api import registry as board_type_registry_api
from components.config.api import profiles as config_profiles
from components.moulin.api import manifest as moulin_manifest_api


class BoardCommandWorkflowService:
    """Provide board-host command use cases to other components."""

    def __init__(
        self,
        *,
        app_dir: Path,
        default_moulin_manifest: str,
        flash_bootloaders_tool: Path,
        xt_imager_tool: Path,
        remote_read_project_file: Callable[[dict[str, Any], str], str],
        manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    ) -> None:
        self.app_dir = app_dir
        self.default_moulin_manifest = default_moulin_manifest
        self.flash_bootloaders_tool = flash_bootloaders_tool
        self.xt_imager_tool = xt_imager_tool
        self.remote_read_project_file = remote_read_project_file
        self.manifest_cache = manifest_cache
        self.command_builder = board_command_builder()
        self.session_service = board_session_command_service()
        self.transfer_service = board_artifact_transfer_service(
            command_builder=self.command_builder,
            app_dir=app_dir,
            default_moulin_manifest=default_moulin_manifest,
            remote_read_project_file=remote_read_project_file,
            manifest_cache=manifest_cache,
        )
        self.flash_service = board_flash_command_service(command_builder=self.command_builder)
        self.board_type_registry = board_type_registry_api.board_type_registry()

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

    def copy_build_artifacts_commands(
        self,
        config: dict[str, Any],
        *,
        artifact_targets: str,
        build_params: dict[str, str],
    ) -> list[list[str]]:
        return self.board_action_commands(
            config,
            "copy_build_artifacts",
            artifact_targets=artifact_targets,
            build_params=build_params,
        )

    def run_copy_build_artifacts(
        self,
        config: dict[str, Any],
        *,
        artifact_targets: str,
        build_params: dict[str, str],
        runner: Callable[[str, list[list[str]]], Any],
    ) -> Any:
        return self.run_board_action(
            config,
            "copy_build_artifacts",
            artifact_targets=artifact_targets,
            build_params=build_params,
            runner=runner,
        )

    def board_actions(
        self,
        config: dict[str, Any],
        *,
        build_params: dict[str, str] | None = None,
        allow_remote_manifest: bool = True,
    ) -> list[board_type_base_api.BoardAction]:
        actions = self._adapter_for_config(config).actions(config)
        domains = self.active_domains_for_config(
            config,
            build_params=build_params,
            allow_remote_manifest=allow_remote_manifest,
        )
        if not domains:
            return actions
        return [action for action in actions if self.action_matches_active_domains(action, domains)]

    def board_action_commands(
        self,
        config: dict[str, Any],
        action_id: str,
        *,
        artifact_targets: str = "",
        build_params: dict[str, str] | None = None,
    ) -> list[list[str]]:
        return self._adapter_for_config(config).action_commands(
            self._action_context(
                config,
                artifact_targets=artifact_targets,
                build_params=build_params,
            ),
            action_id,
        )

    def run_board_action(
        self,
        config: dict[str, Any],
        action_id: str,
        *,
        artifact_targets: str = "",
        build_params: dict[str, str] | None = None,
        runner: Callable[[str, list[list[str]]], Any],
    ) -> Any:
        action = self._action_by_id(config, action_id, build_params=build_params)
        return runner(
            action.label,
            self.board_action_commands(
                config,
                action_id,
                artifact_targets=artifact_targets,
                build_params=build_params,
            ),
        )

    def flash_bootloaders_commands(self, config: dict[str, Any]) -> list[list[str]]:
        return self.board_action_commands(config, "flash_bootloaders")

    def run_flash_bootloaders(
        self,
        config: dict[str, Any],
        *,
        runner: Callable[[str, list[list[str]]], Any],
    ) -> Any:
        return self.run_board_action(config, "flash_bootloaders", runner=runner)

    def flash_ufs_image_commands(self, config: dict[str, Any]) -> list[list[str]]:
        return self.board_action_commands(config, "flash_ufs_image")

    def run_flash_ufs_image(
        self,
        config: dict[str, Any],
        *,
        runner: Callable[[str, list[list[str]]], Any],
    ) -> Any:
        return self.run_board_action(config, "flash_ufs_image", runner=runner)

    def _adapter_for_config(self, config: dict[str, Any]) -> board_type_base_api.BoardTypeAdapter:
        return self.board_type_registry.adapter_for_host(config_profiles.active_board_host(config))

    def _action_by_id(
        self,
        config: dict[str, Any],
        action_id: str,
        *,
        build_params: dict[str, str] | None = None,
    ) -> board_type_base_api.BoardAction:
        for action in self.board_actions(config, build_params=build_params):
            if action.action_id == action_id:
                return action
        raise ValueError(f"unsupported board action: {action_id}")

    def action_matches_active_domains(self, action: board_type_base_api.BoardAction, domains: frozenset[str]) -> bool:
        required = frozenset(action.domains)
        return not required or bool(required & domains)

    def active_domains_for_config(
        self,
        config: dict[str, Any],
        *,
        build_params: dict[str, str] | None = None,
        allow_remote_manifest: bool = True,
    ) -> frozenset[str]:
        remote_read_project_file = self.remote_read_project_file
        if not allow_remote_manifest:
            def remote_read_project_file(_config: dict[str, Any], _path: str) -> str:
                raise RuntimeError("remote manifest reads are disabled for this menu refresh")

        try:
            components = moulin_manifest_api.component_builders_for_config(
                config,
                app_dir=self.app_dir,
                remote_read_project_file=remote_read_project_file,
                cache=self.manifest_cache,
                default_moulin_manifest=self.default_moulin_manifest,
                build_params=build_params,
            )
        except Exception:
            return frozenset()
        domains: set[str] = set()
        for component in components:
            domain = self.domain_for_component_name(str(component.get("name", "")))
            if domain:
                domains.add(domain)
        return frozenset(domains)

    def domain_for_component_name(self, name: str) -> str:
        if name in {"boot_artifacts", "dom0"}:
            return "dom0"
        if name.startswith("domd"):
            return "domd"
        if name.startswith("domu"):
            return "domu"
        if name.startswith("doma") or name.startswith("android"):
            return "doma"
        return ""

    def _action_context(
        self,
        config: dict[str, Any],
        *,
        artifact_targets: str = "",
        build_params: dict[str, str] | None = None,
    ) -> board_type_base_api.BoardActionContext:
        return board_type_base_api.BoardActionContext(
            config=config,
            artifact_targets=artifact_targets,
            active_domains=self.active_domains_for_config(config, build_params=build_params),
            build_params=build_params or {},
            app_dir=self.app_dir,
            default_moulin_manifest=self.default_moulin_manifest,
            remote_read_project_file=self.remote_read_project_file,
            manifest_cache=self.manifest_cache,
            flash_bootloaders_tool=self.flash_bootloaders_tool,
            xt_imager_tool=self.xt_imager_tool,
            command_builder=self.command_builder,
            transfer_service=self.transfer_service,
            flash_service=self.flash_service,
        )


def board_command_workflow_service(
    *,
    app_dir: Path,
    default_moulin_manifest: str,
    flash_bootloaders_tool: Path,
    xt_imager_tool: Path,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
) -> BoardCommandWorkflowService:
    return BoardCommandWorkflowService(
        app_dir=app_dir,
        default_moulin_manifest=default_moulin_manifest,
        flash_bootloaders_tool=flash_bootloaders_tool,
        xt_imager_tool=xt_imager_tool,
        remote_read_project_file=remote_read_project_file,
        manifest_cache=manifest_cache,
    )
