"""Configuration workflow controller."""

from __future__ import annotations

import curses
from pathlib import Path
from typing import Any, Callable

from components.config.api import accessors as config_accessor_api
from components.config.api import profiles as config_profile_api
from components.host_config_ui.api import board_screen as config_board_screen_api
from components.config_workflow.api import field_actions as config_field_actions_api
from components.config_workflow.api import profile_actions as config_profile_actions_api
from components.project_config_ui.api import project_git_ref as config_project_git_ref_api
from components.project_config_ui.api import project_picker as config_project_picker_api
from components.project_config_ui.api import project_screen as config_project_screen_api
from components.project_config.api import project_settings_actions as config_project_settings_actions_api
from components.host_config_ui.api import remote_file_screen as config_remote_file_screen_api
from components.host_config_ui.api import remote_location as config_remote_location_api
from components.host_config_ui.api import remote_screen as config_remote_screen_api
from components.project_config_ui.api import target_selection as config_target_selection_api
from components.remote.api import discovery as remote_discovery_api
from components.ui.api import input as ui_input_api
from components.ui.api import menu as ui_menu_api
from components.ui.api import text as ui_text_api


class ConfigWorkflowController:
    """Run configuration use-cases and own config controller wiring."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        app_dir: Path,
        default_config_path: Path,
        default_build_targets: str,
        default_moulin_manifest: str,
        default_dockerfile: str,
        save_config: Callable[[dict[str, Any]], Any],
        capture_command: Callable[..., Any],
        remote_read_project_file: Callable[[dict[str, Any], str], str],
        manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
        confirm_action: Callable[[str, str], bool],
        reload_runtime: Callable[[], Any],
        restore_project_menu_input: Callable[[], Any],
        reset_preflight: Callable[[], Any],
    ) -> None:
        self.config = config
        self.app_dir = app_dir
        self.default_config_path = default_config_path
        self.default_build_targets = default_build_targets
        self.default_moulin_manifest = default_moulin_manifest
        self.default_dockerfile = default_dockerfile
        self.save_config = save_config
        self.capture_command = capture_command
        self.remote_read_project_file = remote_read_project_file
        self.manifest_cache = manifest_cache
        self.confirm_action = confirm_action
        self.reload_runtime = reload_runtime
        self.restore_project_menu_input = restore_project_menu_input
        self.reset_preflight = reset_preflight

    def run_board_host_configurations_screen(self, port: Any) -> None:
        config_board_screen_api.run_board_host_configurations_screen(
            port,
            self.config,
            save_config=self.save_config,
            profile_action_controller=self._profile_action_controller(),
            field_action_controller=self._field_action_controller(),
        )

    def select_active_board_host(self, port: Any) -> None:
        hosts = [host for host in self.config.get("board_hosts", []) if isinstance(host, dict)]
        current = str(config_profile_api.active_board_host(self.config).get("name", ""))
        host = self._select_profile_from_list(port, "Select board host", hosts, current)
        if host is None:
            return
        self._profile_action_controller().set_active_board_host(port, host)

    def run_remote_configurations_screen(self, port: Any) -> None:
        config_remote_screen_api.run_remote_configurations_screen(
            port,
            self.config,
            save_config=self.save_config,
            remote_file_selection_controller=self._remote_file_selection_controller(),
            profile_action_controller=self._profile_action_controller(),
            field_action_controller=self._field_action_controller(),
        )

    def select_active_remote(self, port: Any) -> None:
        remotes = [remote for remote in self.config.get("remotes", []) if isinstance(remote, dict)]
        current = str(config_profile_api.active_remote(self.config).get("name", ""))
        remote = self._select_profile_from_list(port, "Select build host", remotes, current)
        if remote is None:
            return
        self._profile_action_controller().set_active_remote(port, remote)

    def _select_profile_from_list(
        self,
        port: Any,
        title: str,
        profiles: list[dict[str, Any]],
        current: str,
    ) -> dict[str, Any] | None:
        if not profiles:
            port.status = f"{title}: no profiles configured"
            return None
        names = [str(profile.get("name", "")) for profile in profiles]
        index = names.index(current) if current in names else 0
        port.screen.timeout(-1)
        while True:
            port.screen.erase()
            height, width = port.screen.getmaxyx()
            if height < 12 or width < 60:
                port.add(0, 0, "Terminal is too small. Need at least 60x12.", port.warn_attr())
                port.screen.refresh()
                ch = port.read_key()
                if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                    port.status = f"{title} cancelled"
                    return None
                continue
            port.add(0, 0, title[:width], curses.A_BOLD)
            port.add(1, 0, "Up/Down: select | Enter: choose | q/Esc: cancel"[:width], port.accent_attr())
            port.draw_box(3, 0, height - 6, width, "Profiles")
            visible = max(1, height - 8)
            index = ui_menu_api.clamp_index(index, len(profiles))
            scroll = ui_menu_api.list_scroll(index, len(profiles), visible)
            for offset, profile in enumerate(profiles[scroll : scroll + visible]):
                item_index = scroll + offset
                marker = "*" if names[item_index] == current else " "
                label = self._profile_picker_label(profile, marker)
                attr = port.selected_attr() if item_index == index else 0
                port.add(4 + offset, 2, ui_text_api.fit_text(label, width - 4).ljust(width - 4), attr)
            port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
            port.screen.refresh()
            ch = port.read_key()
            if ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
                index = ui_menu_api.move_index(index, len(profiles), -1)
            elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j") or ch == ord("\t"):
                index = ui_menu_api.move_index(index, len(profiles), 1)
            elif ch in (10, 13):
                return profiles[index]
            elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
                port.status = f"{title} cancelled"
                return None

    @staticmethod
    def _profile_picker_label(profile: dict[str, Any], marker: str) -> str:
        name = str(profile.get("name", ""))
        label = str(profile.get("label", ""))
        user = str(profile.get("user", ""))
        host = str(profile.get("host", ""))
        endpoint = f"{user}@{host}" if user and host else host or user
        parts = [f"{marker} {name}"]
        if label and label != name:
            parts.append(label)
        if endpoint:
            parts.append(endpoint)
        return "  ".join(parts)

    def run_edit_remote_screen(self, port: Any, remote: dict[str, Any]) -> None:
        config_remote_screen_api.run_edit_remote_screen(
            port,
            self.config,
            remote,
            save_config=self.save_config,
            profile_action_controller=self._profile_action_controller(),
            field_action_controller=self._field_action_controller(),
            browse_project_directory=lambda start_path: self.browse_remote_directory_screen(port, start_path),
        )

    def run_add_remote_screen(self, port: Any) -> None:
        config_remote_screen_api.run_add_remote_screen(
            port,
            self.config,
            save_config=self.save_config,
            reset_preflight=self.reset_preflight,
        )

    def browse_remote_directory_screen(self, port: Any, start_path: str) -> str | None:
        return self._project_remote_dir_editor().browse_project_directory(port, start_path)

    def remote_project_config_ready(self, port: Any) -> bool:
        plan = config_accessor_api.remote_project_config_ready_plan(
            self.config,
            connected=port.connection_state == "connected",
        )
        if not plan["ready"]:
            port.status = str(plan["status"])
            return False
        return True

    def run_project_configurations_screen(self, port: Any) -> None:
        config_project_screen_api.run_project_configurations_screen(
            port,
            self.config,
            self.app_dir,
            remote_read_project_file=self.remote_read_project_file,
            manifest_cache=self.manifest_cache,
            default_moulin_manifest=self.default_moulin_manifest,
            default_config_path=self.default_config_path,
            save_config=self.save_config,
            target_selection_controller_factory=self._target_selection_controller,
            remote_file_selection_controller=self._remote_file_selection_controller(),
            project_remote_dir_editor=self._project_remote_dir_editor(),
            project_git_ref_selector=self._project_git_ref_selector(),
            profile_action_controller=self._profile_action_controller(),
            field_action_controller=self._field_action_controller(),
            project_settings_controller=self._project_settings_action_controller(),
            reload_runtime=self.reload_runtime,
        )

    def run_settings_action(self, port: Any, action: dict[str, Any]) -> bool:
        return self._project_settings_action_controller().run_action(port, action)

    def _profile_action_controller(self) -> Any:
        return config_profile_actions_api.profile_action_controller(
            self.config,
            save_config=self.save_config,
            confirm_action=self.confirm_action,
            reload_runtime=self.reload_runtime,
            restore_project_menu_input=self.restore_project_menu_input,
        )

    def _field_action_controller(self) -> Any:
        return config_field_actions_api.field_action_controller(
            self.config,
            save_config=self.save_config,
            reload_runtime=self.reload_runtime,
        )

    def _remote_file_selection_controller(self) -> Any:
        remote_discovery = remote_discovery_api.remote_project_discovery_service()
        return config_remote_file_screen_api.remote_file_selection_controller(
            self.config,
            self.app_dir,
            fetch_git_tracked_files=lambda: remote_discovery.fetch_git_tracked_files_for_config(
                self.config,
                lambda argv: self.capture_command(argv, echo=False, timeout=20),
            ),
            read_project_file=self.remote_read_project_file,
            manifest_cache=self.manifest_cache,
            default_moulin_manifest=self.default_moulin_manifest,
            save_config=self.save_config,
            reset_preflight=self.reset_preflight,
        )

    def _target_selection_controller(self) -> Any:
        return config_target_selection_api.target_selection_controller_for_config(
            self.config,
            app_dir=self.app_dir,
            remote_read_project_file=self.remote_read_project_file,
            manifest_cache=self.manifest_cache,
            default_moulin_manifest=self.default_moulin_manifest,
            default_config_path=self.default_config_path,
            save_config=self.save_config,
        )

    def _project_remote_dir_editor(self) -> Any:
        return config_remote_location_api.project_remote_dir_editor_for_config(
            self.config,
            lambda argv: self.capture_command(argv, echo=False),
        )

    def _project_git_ref_selector(self) -> Any:
        return config_project_git_ref_api.project_git_ref_selector_for_config(
            self.config,
            lambda argv: self.capture_command(argv, echo=False, timeout=20),
        )

    def _project_settings_action_controller(self) -> Any:
        return config_project_settings_actions_api.project_settings_action_controller(
            self.config,
            app_dir=self.app_dir,
            default_config_path=self.default_config_path,
            save_config=self.save_config,
            target_selection_controller_factory=self._target_selection_controller,
            remote_file_selection_controller=self._remote_file_selection_controller(),
            profile_action_controller=self._profile_action_controller(),
            project_picker_controller=self._project_picker_controller(),
            reload_runtime=self.reload_runtime,
        )

    def _project_picker_controller(self) -> Any:
        return config_project_picker_api.project_picker_controller(
            self.config,
            app_dir=self.app_dir,
            default_build_targets=self.default_build_targets,
            default_moulin_manifest=self.default_moulin_manifest,
            default_dockerfile=self.default_dockerfile,
            save_config=self.save_config,
        )


def config_workflow_controller(
    config: dict[str, Any],
    *,
    app_dir: Path,
    default_config_path: Path,
    default_build_targets: str,
    default_moulin_manifest: str,
    default_dockerfile: str,
    save_config: Callable[[dict[str, Any]], Any],
    capture_command: Callable[..., Any],
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    confirm_action: Callable[[str, str], bool],
    reload_runtime: Callable[[], Any],
    restore_project_menu_input: Callable[[], Any],
    reset_preflight: Callable[[], Any],
) -> ConfigWorkflowController:
    return ConfigWorkflowController(
        config,
        app_dir=app_dir,
        default_config_path=default_config_path,
        default_build_targets=default_build_targets,
        default_moulin_manifest=default_moulin_manifest,
        default_dockerfile=default_dockerfile,
        save_config=save_config,
        capture_command=capture_command,
        remote_read_project_file=remote_read_project_file,
        manifest_cache=manifest_cache,
        confirm_action=confirm_action,
        reload_runtime=reload_runtime,
        restore_project_menu_input=restore_project_menu_input,
        reset_preflight=reset_preflight,
    )
