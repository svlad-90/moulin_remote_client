"""Main menu setup and preflight item service."""

from __future__ import annotations

import curses
import shlex
from typing import Any

from components.config.api import accessors as config_accessor_api
from components.config.api import profiles as config_profile_api
from components.remote.api import workflow as remote_workflow_api
from components.ui.api import input as ui_input_api
from components.ui.api import preflight as ui_preflight_api
from components.ui.api import session as ui_session_api
from components.ui.api.menu import MenuItem


class MainMenuSetupItemsService:
    """Build setup, build-host session, and preflight action menu items."""

    def __init__(
        self,
        *,
        remote_command_workflow: remote_workflow_api.RemoteCommandWorkflowService,
    ) -> None:
        self.remote_command_workflow = remote_command_workflow

    def build_items(self, app: Any) -> list[MenuItem]:
        items = self.setup_items()
        items.extend(self.build_host_session_items(app))
        items.extend(self.preflight_action_items(app))
        return items

    def setup_items(self) -> list[MenuItem]:
        return [
            MenuItem(
                "Build host configuration",
                "configuration",
                "Add, delete, and edit build-machine SSH profiles used for Moulin and Ninja.",
                lambda app: "Open build host profile setup.",
                lambda app: app.config_workflow_controller().run_remote_configurations_screen(app),
                allow_during_job=True,
            ),
            MenuItem(
                "Board host configuration",
                "configuration",
                "Add, delete, and edit board-access SSH profiles used for runtime checks.",
                lambda app: "Open board host profile setup.",
                lambda app: app.config_workflow_controller().run_board_host_configurations_screen(app),
                allow_during_job=True,
            ),
            MenuItem(
                "Project configuration",
                "configuration",
                "Add, delete, select, and edit project profiles plus product-specific build settings, artifacts, and mappings.",
                lambda app: f"Active project: {config_profile_api.active_project(app.config).get('label') or config_profile_api.active_project(app.config).get('name')}",
                lambda app: app.config_workflow_controller().run_project_configurations_screen(app),
                allow_during_job=True,
            ),
            MenuItem(
                "Settings",
                "configuration",
                "Open general TUI settings.",
                lambda app: f"Show commands in logs: {setting_enabled_text(app.config, 'show_commands')}",
                lambda app: run_general_settings_screen(app),
                allow_during_job=True,
            ),
        ]

    def build_host_session_items(self, app: Any) -> list[MenuItem]:
        has_build_hosts = bool([remote for remote in app.config.get("remotes", []) if isinstance(remote, dict)])
        has_board_hosts = bool([host for host in app.config.get("board_hosts", []) if isinstance(host, dict)])
        return [
            MenuItem(
                "Select build host" if has_build_hosts else "Add build host",
                "sessions / build host",
                (
                    "Choose the active build host profile used by Moulin, Ninja, and source sync commands."
                    if has_build_hosts
                    else "Open build host profile setup."
                ),
                lambda app: self._host_selection_preview(app.config, "active_remote", "remotes"),
                (
                    lambda app: app.config_workflow_controller().select_active_remote(app)
                    if has_build_hosts
                    else app.config_workflow_controller().run_remote_configurations_screen(app)
                ),
                allow_during_job=True,
            ),
            MenuItem(
                "Connect build host",
                "sessions / build host",
                "Check SSH access and project preflight for the configured build host or mark it disconnected.",
                lambda app: ui_session_api.build_host_connection_preview(
                    app.connection_state,
                    self.remote_command_workflow.connect_command(app.config),
                ),
                lambda app: app.connection_workflow_service().toggle_build_host(app),
                allow_during_job=True,
            ),
            MenuItem(
                "Open build host shell",
                "sessions / build host",
                "Open SSH shell in the remote product directory on the build host; exit returns to this TUI.",
                lambda app: shlex.join(self.remote_command_workflow.interactive_shell_command(app.config)),
                lambda app: app.terminal_session_controller().open_remote_shell(app),
                requires_remote=True,
                requires_project=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Select board host" if has_board_hosts else "Add board host",
                "sessions / board host",
                (
                    "Choose the active board host profile used by flashing, TFTP/NFS deploy, and board shell commands."
                    if has_board_hosts
                    else "Open board host profile setup."
                ),
                lambda app: self._host_selection_preview(app.config, "active_board_host", "board_hosts"),
                (
                    lambda app: app.config_workflow_controller().select_active_board_host(app)
                    if has_board_hosts
                    else app.config_workflow_controller().run_board_host_configurations_screen(app)
                ),
                allow_during_job=True,
            ),
        ]

    def _host_selection_preview(self, config: dict[str, Any], active_key: str, list_key: str) -> str:
        active = str(config.get(active_key, ""))
        names = [str(profile.get("name", "")) for profile in config.get(list_key, []) if isinstance(profile, dict)]
        return f"Active: {active or '<none>'} | Available: {', '.join(names) or '<none>'}"

    def preflight_action_items(self, app: Any) -> list[MenuItem]:
        preflight_actions = ui_preflight_api.project_action_requirements(
            app.preflight_values,
            project_git_url=config_accessor_api.project_git_url_for_config(app.config),
            project_git_ref=config_accessor_api.project_git_ref_for_config(app.config),
        )
        items = []
        if preflight_actions["prepare_remote_project"]:
            items.append(
                MenuItem(
                    "Prepare remote project",
                    "build",
                    "Set up the configured product checkout on the build host: create the project directory, clone the Git repository when missing, and repair an invalid checkout or origin mismatch.",
                    lambda app: shlex.join(self.remote_command_workflow.prepare_project_command(app.config)),
                    lambda app: app.command_workflow_service().run_commands(
                        app,
                        "Prepare remote project",
                        [self.remote_command_workflow.prepare_project_command(app.config)],
                    ),
                    confirm=True,
                    requires_ssh=True,
                    requires_project=True,
                )
            )
        if preflight_actions["checkout_git_ref"] and not preflight_actions["prepare_remote_project"]:
            items.append(
                MenuItem(
                    "Checkout project Git ref",
                    "build",
                    (
                        "Switch the remote checkout to the configured project Git branch/ref. If needed, remove a stale Git index lock "
                        "when no running process owns it, stage and stash local changes, fetch origin, then checkout the ref."
                    ),
                    lambda app: shlex.join(self.remote_command_workflow.repair_and_checkout_git_ref_command(app.config)),
                    lambda app: app.command_workflow_service().run_commands(
                        app,
                        "Checkout project Git ref",
                        [self.remote_command_workflow.repair_and_checkout_git_ref_command(app.config)],
                    ),
                    confirm=True,
                    requires_remote=True,
                    requires_project=True,
                )
            )
        return items


def setting_enabled_text(config: dict[str, Any], name: str) -> str:
    ui = config.get("ui")
    enabled = isinstance(ui, dict) and bool(ui.get(name))
    return "yes" if enabled else "no"


def set_ui_setting(config: dict[str, Any], name: str, enabled: bool) -> None:
    ui = config.setdefault("ui", {})
    if not isinstance(ui, dict):
        ui = {}
        config["ui"] = ui
    ui[name] = bool(enabled)


def toggle_ui_setting(app: Any, name: str, label: str) -> None:
    ui = app.config.get("ui")
    enabled = not (isinstance(ui, dict) and bool(ui.get(name)))
    set_ui_setting(app.config, name, enabled)
    app.dependencies.save_config(app.config)
    app.status = f"{label}: {'yes' if enabled else 'no'}"
    app.menu_dirty = True
    app.main_full_redraw = True


def run_general_settings_screen(app: Any) -> None:
    index = 0
    entries = [
        {
            "label": "Show commands in logs",
            "key": "show_commands",
            "description": "Show the exact command or script before each action runs.",
        }
    ]
    app.screen.timeout(-1)
    while True:
        app.screen.erase()
        height, width = app.screen.getmaxyx()
        if height < 12 or width < 60:
            app.add(0, 0, "Terminal is too small. Need at least 60x12.", app.warn_attr())
            app.screen.refresh()
            ch = app.read_key()
            if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                app.screen.timeout(250)
                return
            continue

        app.add(0, 0, "Settings"[:width], curses.A_BOLD)
        app.add(1, 0, "Up/Down: select | Enter/Space: toggle | q/Esc: back"[:width], app.accent_attr())
        app.draw_box(3, 0, height - 6, width, "General")
        visible_width = max(1, width - 4)
        for row_offset, entry in enumerate(entries):
            row = 4 + row_offset
            checked = setting_enabled_text(app.config, str(entry["key"])) == "yes"
            marker = "[x]" if checked else "[ ]"
            text = f"{marker} {entry['label']}"
            attr = app.selected_attr() if row_offset == index else 0
            app.add(row, 2, text[:visible_width].ljust(visible_width), attr)
        detail_row = 6 + len(entries)
        current = entries[index]
        app.add(detail_row, 2, str(current["description"])[:visible_width])
        app.add(height - 1, 0, app.status[:width].ljust(width), curses.A_REVERSE)
        app.screen.refresh()

        ch = app.read_key()
        if ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
            index = max(0, index - 1)
        elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j") or ch == ord("\t"):
            index = min(len(entries) - 1, index + 1)
        elif ch in (10, 13, ord(" ")):
            current = entries[index]
            toggle_ui_setting(app, str(current["key"]), str(current["label"]))
        elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
            app.screen.timeout(250)
            app.status = "Settings closed"
            return


def main_menu_setup_items_service(
    *,
    remote_command_workflow: remote_workflow_api.RemoteCommandWorkflowService,
) -> MainMenuSetupItemsService:
    return MainMenuSetupItemsService(remote_command_workflow=remote_command_workflow)
