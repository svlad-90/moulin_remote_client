"""Application client facade."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from components.app.api import services as app_services_api
from components.app.api import state as app_state_api
from components.app.api import terminal as app_terminal_api
from components.config_workflow.api import workflow as config_workflow_api
from components.jobs.api import connection_workflow as job_connection_workflow_api
from components.jobs.api import session as job_session_api
from components.jobs.api import workflow as job_workflow_api
from components.main_menu.api import state as main_menu_state_api
from components.sync.api import workflow as sync_workflow_api
from components.ui.api import dialog_workflow as ui_dialog_workflow_api
from components.ui.api import panels as ui_panels_api
from components.ui.api import session as ui_session_api
from components.ui.api import terminal_port as ui_terminal_port_api
from components.ui.api.menu import MenuItem


@dataclass(frozen=True)
class ClientAppDependencies:
    app_dir: Path
    default_config_path: Path
    default_docker_image: str
    default_dockerfile: str
    default_build_targets: str
    default_moulin_manifest: str
    flash_bootloaders_tool: Path
    xt_imager_tool: Path
    remote_read_project_file: Callable[..., Any]
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]]
    load_config: Callable[[Path], dict[str, Any]]
    save_config: Callable[[dict[str, Any]], Any]
    env: dict[str, str]
    read_input: Callable[[str], str]
    write_line: Callable[..., Any]
    monotonic: Callable[[], float]
    profile_slow_ms: float


class ClientApp:
    """TUI session facade kept for compatibility with existing UI components."""

    dependencies: ClientAppDependencies

    def __init__(self, screen: Any, config: dict[str, Any]) -> None:
        deps = self.dependencies
        self.screen = screen
        self.config = config
        self.app_state = self.app_state_controller()
        self.main_menu_state = self.main_menu_state_controller()
        self.terminal_port = self.terminal_port_controller()
        self.terminal = self.terminal_port_adapter()
        self.services = self.app_services_controller()
        self.app_state.initialize_session(
            self,
            build_items=self.services.build_items,
            reset_preflight=ui_session_api.reset_preflight,
        )

    def app_state_controller(self) -> app_state_api.AppStateController:
        deps = self.dependencies
        return app_state_api.app_state_controller(
            app_dir=deps.app_dir,
            env=deps.env,
            default_docker_image=deps.default_docker_image,
            default_build_targets=deps.default_build_targets,
            default_moulin_manifest=deps.default_moulin_manifest,
            remote_read_project_file=deps.remote_read_project_file,
            manifest_cache=deps.manifest_cache,
            profile_slow_ms=deps.profile_slow_ms,
            monotonic=deps.monotonic,
        )

    def app_services_controller(self) -> app_services_api.AppServicesController:
        deps = self.dependencies
        return app_services_api.app_services_controller(
            app_dir=deps.app_dir,
            default_config_path=deps.default_config_path,
            default_dockerfile=deps.default_dockerfile,
            default_moulin_manifest=deps.default_moulin_manifest,
            default_build_targets=deps.default_build_targets,
            flash_bootloaders_tool=deps.flash_bootloaders_tool,
            xt_imager_tool=deps.xt_imager_tool,
            remote_read_project_file=deps.remote_read_project_file,
            manifest_cache=deps.manifest_cache,
            save_config=deps.save_config,
            env=deps.env,
            read_input=deps.read_input,
            write_line=deps.write_line,
        )

    def load_active_project_runtime(self) -> None:
        self.app_state.load_active_project_runtime(self)

    def refresh_mapping_selection_cache(self) -> None:
        self.app_state.refresh_mapping_selection_cache(self)

    def reload_config_from_disk(self) -> None:
        self.config = self.dependencies.load_config(self.dependencies.default_config_path)
        self.load_active_project_runtime()
        self.refresh_mapping_selection_cache()
        self.items = self.build_items()
        self.menu_dirty = True
        self.main_full_redraw = True
        self.logs_dirty = True

    def ui_profile(self, event: str, **fields: Any) -> None:
        self.app_state.profile(self, event, **fields)

    def ui_profile_slow(self, event: str, started: float, threshold_ms: float | None = None, **fields: Any) -> float:
        return self.app_state.profile_slow(self, event, started, threshold_ms, **fields)

    def flush_ui_profile(self) -> None:
        self.app_state.flush_profile(self)

    def main_menu_state_controller(self) -> main_menu_state_api.MainMenuStateController:
        return main_menu_state_api.main_menu_state_controller(app_dir=self.dependencies.app_dir)

    def terminal_port_controller(self) -> ui_terminal_port_api.TerminalPortController:
        return ui_terminal_port_api.terminal_port_controller()

    def terminal_port_adapter(self) -> app_terminal_api.AppTerminalPortAdapter:
        return app_terminal_api.app_terminal_port_adapter(
            app_dir=self.dependencies.app_dir,
            terminal_port=self.terminal_port,
            main_menu_state=self.main_menu_state,
        )

    def build_items(self) -> list[MenuItem]:
        return self.services.build_items(self)

    def run(self) -> None:
        self.services.run(self)

    def handle_main_key(self, ch: int) -> None:
        self.services.handle_main_key(self, ch)

    def setup_colors(self) -> None:
        self.terminal.setup_colors()

    def configure_escape_delay(self) -> None:
        self.terminal.configure_escape_delay()

    def configure_mouse(self) -> None:
        self.terminal.configure_mouse()

    def set_cursor(self, visible: bool) -> None:
        self.terminal.set_cursor(visible)

    def read_key(self) -> int:
        return self.terminal.read_key(self)

    def unread_key(self, ch: int) -> None:
        self.terminal.unread_key(ch)

    def read_queued_text(self, first_ch: int) -> str:
        return self.terminal.read_queued_text(self, first_ch)

    def selected_attr(self) -> int:
        return self.terminal.selected_attr()

    def selected_disabled_attr(self) -> int:
        return self.terminal.selected_disabled_attr()

    def active_row_attr(self) -> int:
        return self.terminal.active_row_attr()

    def selected_active_attr(self) -> int:
        return self.terminal.selected_active_attr()

    def editing_attr(self) -> int:
        return self.terminal.editing_attr()

    def accent_attr(self) -> int:
        return self.terminal.accent_attr()

    def warn_attr(self) -> int:
        return self.terminal.warn_attr()

    def running_attr(self) -> int:
        return self.terminal.running_attr()

    def group_attr(self) -> int:
        return self.terminal.group_attr()

    def disabled_attr(self) -> int:
        return self.terminal.disabled_attr()

    def ok_attr(self) -> int:
        return self.terminal.ok_attr()

    def error_attr(self) -> int:
        return self.terminal.error_attr()

    def role_attr(self, role: str) -> int:
        return self.terminal.role_attr(role)

    def item_enabled(self, item: MenuItem) -> bool:
        return self.terminal.item_enabled(self, item)

    def disabled_reason(self, item: MenuItem) -> str:
        return self.terminal.disabled_reason(self, item)

    def add(self, y: int, x: int, text: str, attr: int = 0) -> None:
        self.terminal.add(self, y, x, text, attr)

    def add_segments(self, y: int, x: int, max_width: int, segments: list[tuple[str, int]]) -> None:
        self.terminal.add_segments(self, y, x, max_width, segments)

    def draw_box(self, top: int, left: int, height: int, width: int, title: str = "", attr: int = 0) -> None:
        self.terminal.draw_box(self, top, left, height, width, title, attr)

    def connection_attr_for(self, state: str) -> int:
        return self.terminal.connection_attr_for(state)

    def connection_attr(self) -> int:
        return self.connection_attr_for(self.connection_state)

    def mapping_status_snapshot(self) -> dict[str, str]:
        return self.terminal.mapping_status_snapshot(self)

    def draw_wrapped(self, y: int, x: int, width: int, text: str, attr: int = 0, max_lines: int = 4) -> int:
        return self.terminal.draw_wrapped(self, y, x, width, text, attr, max_lines)

    def draw_scrollbar(self, top: int, left: int, height: int, total: int, visible: int, scroll: int) -> None:
        self.terminal.draw_scrollbar(self, top, left, height, total, visible, scroll)

    def draw_label_value_wrapped(self, row: int, x: int, width: int, label: str, value: str, *, max_lines: int = 3) -> int:
        return self.terminal.draw_label_value_wrapped(self, row, x, width, label, value, max_lines=max_lines)

    def draw(self) -> None:
        self.services.draw(self)

    def run_selected(self) -> None:
        self.services.run_selected(self)

    def stop_running_preview(self, slot: str | None = None) -> str:
        return self.services.stop_running_preview(self, slot)

    def stop_running_command(self, slot: str | None = None) -> None:
        self.services.stop_running_command(self, slot)

    def finish_active_job(self, job: dict[str, Any] | None = None) -> None:
        self.services.finish_active_job(self, job)

    def start_next_active_job_command(self, job: dict[str, Any] | None = None) -> None:
        self.services.start_next_active_job_command(self, job)

    def poll_active_jobs(self) -> None:
        self.services.poll_active_jobs(self)

    def poll_active_job(self, job: dict[str, Any] | None = None) -> None:
        self.services.poll_active_job(self, job)

    def command_workflow_service(self) -> job_workflow_api.CommandWorkflowService:
        return self.services.command_workflow_service(self)

    def connection_workflow_service(self) -> job_connection_workflow_api.ConnectionWorkflowService:
        return self.services.connection_workflow_service(self)

    def job_session_controller(self) -> job_session_api.JobSessionController:
        return self.services.job_session_controller(self)

    def dialog_workflow_controller(self) -> ui_dialog_workflow_api.DialogWorkflowController:
        return self.services.dialog_workflow_controller()

    def config_workflow_controller(self) -> config_workflow_api.ConfigWorkflowController:
        return self.services.config_workflow_controller(self)

    def sync_workflow_controller(self) -> sync_workflow_api.SyncWorkflowController:
        return self.services.sync_workflow_controller(self)

    def sync_screen(self) -> None:
        self.reload_config_from_disk()
        self.services.run_sync_screen(self)

    def confirm_sync_action(self, label: str, description: str) -> bool:
        return self.services.confirm_sync_action(self, label, description)

    def terminal_session_controller(self) -> Any:
        return self.services.terminal_session_controller(self)

    def suspend_tui(self) -> None:
        self.terminal.suspend_tui()

    def restore_tui(self) -> None:
        self.terminal.restore_tui(self)

    def wait_message(self, message: str) -> None:
        self.services.wait_message(self, message)

    def show_message(self, title: str, lines: list[str]) -> None:
        self.services.show_message(self, title, lines)

    def remote_project_config_ready(self) -> bool:
        return self.services.remote_project_config_ready(self)

    def prompt(self, label: str, current: str) -> str:
        return self.services.prompt(self, label, current)

    def quit(self) -> None:
        self.app_state.quit(self)


def client_app_class(dependencies: ClientAppDependencies) -> type[ClientApp]:
    class BoundClientApp(ClientApp):
        pass

    BoundClientApp.dependencies = dependencies
    BoundClientApp.__name__ = "ClientApp"
    return BoundClientApp
