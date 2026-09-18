"""Main screen draw orchestration."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from components.config.api import accessors as config_accessor_api
from components.jobs.api import jobs as job_api
from components.ui.api import layout as ui_layout_api
from components.ui.api import menu as ui_menu_api
from components.ui.api.menu import MenuItem
from components.ui.api import panels as ui_panels_api
from components.ui.api import session as ui_session_api
from components.ui.api import status_segments as ui_status_segments_api


class MainDrawController:
    """Orchestrate cached drawing of the main TUI screen."""

    def __init__(self, *, app_dir: Path) -> None:
        self.app_dir = app_dir

    def draw(self, port: Any) -> None:
        draw_started = time.monotonic()
        rendered: list[str] = []
        port.setup_colors()
        height, width = port.screen.getmaxyx()
        if height < 20 or width < 80:
            port.screen.erase()
            port.add(0, 0, "Terminal is too small. Need at least 80x20.", port.warn_attr())
            port.screen.refresh()
            port.main_full_redraw = True
            port.ui_profile_slow("draw-small-terminal", draw_started)
            return

        metrics = ui_layout_api.main_layout(height, width)
        left_width = metrics.left_width
        right_left = metrics.right_left
        right_width = metrics.right_width
        panel_top = metrics.panel_top
        panel_height = metrics.panel_height
        menu_visible_rows = max(1, panel_height - 4)
        details_height = metrics.details_height
        logs_height = metrics.logs_height
        logs_top = metrics.logs_top
        if port.main_full_redraw or port.render_cache.get("layout") != metrics.signature():
            port.screen.erase()
            port.render_cache.clear()
            port.render_cache["layout"] = metrics.signature()
            port.main_full_redraw = True
        for row in range(panel_top, panel_top + panel_height):
            port.add(row, left_width, " ")

        if port.menu_dirty:
            previous_items = port.items
            port.items = port.build_items()
            port.selected = ui_menu_api.sync_menu_selection(
                previous_items,
                port.selected,
                port.items,
                [port.item_enabled(item) for item in port.items],
            )
            port.menu_dirty = False
            port.render_cache.pop("actions", None)
            port.render_cache.pop("details", None)
            port.render_cache.pop("logs", None)

        if not hasattr(port, "menu_focus"):
            port.menu_focus = "items"
        if not hasattr(port, "active_menu_tab"):
            port.active_menu_tab = ""
        item_enabled_values = [port.item_enabled(item) for item in port.items]
        port.active_menu_tab = ui_menu_api.normalize_active_tab(port.active_menu_tab, port.items, port.selected)
        visible_indices = ui_menu_api.visible_item_indices(port.items, port.active_menu_tab)
        if visible_indices and not ui_menu_api.selected_in_indices(port.selected, visible_indices):
            port.selected = ui_menu_api.nearest_visible_selection(port.selected, visible_indices, item_enabled_values)

        menu_rows = ui_menu_api.wrapped_menu_rows(
            ui_menu_api.menu_rows_for_indices(
                port.items,
                [
                    ui_session_api.connection_menu_label(
                        item.label,
                        build_state=port.connection_state,
                        board_state=port.board_connection_state,
                    )
                    for item in port.items
                ],
                visible_indices,
            ),
            max(1, left_width - 4),
        )
        port.menu_scroll = ui_menu_api.clamp_menu_scroll(
            menu_rows,
            port.selected,
            port.menu_scroll,
            menu_visible_rows,
        )

        item = port.items[port.selected] if port.items else MenuItem("", "", "", lambda app: "", lambda app: None)
        running_jobs = job_api.running_job_list(port.active_job, port.board_job)
        active_job_exists = job_api.has_active_job(port.active_job, port.board_job)
        active_labels = tuple(str(job.get("item_label", "")) for job in running_jobs)
        item_labels = tuple(item.label for item in port.items)
        item_enabled = tuple(item_enabled_values)
        menu_tabs = tuple(ui_menu_api.menu_tabs(port.items))
        selection = tuple(port.mapping_selection_cache)
        mapping_status = port.mapping_status_snapshot()

        if port.logs_expanded:
            self._draw_expanded_logs(
                port,
                height,
                width,
                item,
                active_job_exists=active_job_exists,
                draw_started=draw_started,
            )
            return

        self._draw_header(port, width, mapping_status, rendered)
        self._draw_actions(
            port,
            panel_top,
            panel_height,
            left_width,
            menu_rows,
            menu_visible_rows,
            running_jobs,
            active_labels,
            item_labels,
            item_enabled,
            menu_tabs,
            rendered,
        )
        self._draw_details(
            port,
            panel_top,
            right_left,
            details_height,
            right_width,
            item,
            running_jobs,
            active_labels,
            selection,
            mapping_status,
            rendered,
        )
        self._draw_logs(
            port,
            logs_top,
            right_left,
            logs_height,
            right_width,
            item,
            active_job_exists,
            active_labels,
            rendered,
        )
        self._draw_footer(port, height, width, active_job_exists, rendered)
        port.main_full_redraw = False
        refresh_started = time.monotonic()
        port.screen.refresh()
        port.ui_profile_slow("refresh-slow", refresh_started, threshold_ms=5.0)
        port.ui_profile_slow(
            "draw-slow",
            draw_started,
            rendered=",".join(rendered) or "none",
            active=active_job_exists,
            selected=port.selected,
        )

    def _draw_expanded_logs(
        self,
        port: Any,
        height: int,
        width: int,
        item: MenuItem,
        *,
        active_job_exists: bool,
        draw_started: float,
    ) -> None:
        expanded_sig = (
            height,
            width,
            port.selected,
            item.label,
            port.focus_panel,
            port.log_scroll,
            port.log_follow,
            port.status,
        )
        job = ui_menu_api.display_job_for_item(
            item,
            active_job=port.active_job,
            board_job=port.board_job,
            last_board_job=port.last_board_job,
            last_job=port.last_job,
            last_board_jobs_by_label=getattr(port, "last_board_jobs_by_label", {}),
            last_jobs_by_label=getattr(port, "last_jobs_by_label", {}),
        )
        job_output = tuple(job_api.job_output_lines(job)[-20:]) if job is not None else ()
        expanded_sig += (
            job.get("title", "") if job is not None else "",
            job_api.job_running(job),
            len(job_api.job_output_lines(job)) if job is not None else 0,
            job_output,
        )
        started = time.monotonic()
        ui_panels_api.main_panels_controller().draw_expanded_logs(port, height, width, item)
        port.render_cache["expanded_logs"] = expanded_sig
        port.last_log_render_at = time.monotonic()
        port.logs_dirty = False
        port.ui_profile_slow("panel-expanded-logs-slow", started, threshold_ms=5.0, item=item.label)
        port.main_full_redraw = False
        refresh_started = time.monotonic()
        port.screen.refresh()
        port.ui_profile_slow("refresh-slow", refresh_started, threshold_ms=5.0)
        port.ui_profile_slow("draw-slow", draw_started, rendered="expanded-logs", active=active_job_exists, selected=port.selected)

    def _draw_header(self, port: Any, width: int, mapping_status: dict[str, str], rendered: list[str]) -> None:
        header_sig = (
            width,
            config_accessor_api.remote_label_for_config(port.config),
            config_accessor_api.remote_spec_for_config(port.config),
            config_accessor_api.remote_project_dir_for_config(port.config),
            config_accessor_api.board_host_label_for_config(port.config),
            config_accessor_api.board_host_spec_for_config(port.config),
            str(config_accessor_api.local_project_dir_for_config(port.config, self.app_dir)),
            config_accessor_api.moulin_manifest_name_for_config(port.config),
            port.connection_state,
            port.board_connection_state,
            tuple(sorted(port.build_params.items())),
            port.docker_image,
            port.build_targets,
            port.preflight,
            mapping_status["text"],
            mapping_status["role"],
        )
        if port.main_full_redraw or port.render_cache.get("header") != header_sig:
            started = time.monotonic()
            ui_panels_api.main_panels_controller().draw_header(port, width, app_dir=self.app_dir)
            port.ui_profile_slow("panel-header-slow", started, threshold_ms=5.0)
            port.render_cache["header"] = header_sig
            rendered.append("header")

    def _draw_actions(
        self,
        port: Any,
        panel_top: int,
        panel_height: int,
        left_width: int,
        menu_rows: list[dict[str, Any]],
        menu_visible_rows: int,
        running_jobs: list[dict[str, Any]],
        active_labels: tuple[str, ...],
        item_labels: tuple[str, ...],
        item_enabled: tuple[bool, ...],
        menu_tabs: tuple[str, ...],
        rendered: list[str],
    ) -> None:
        actions_sig = (
            left_width,
            panel_height,
            port.selected,
            port.menu_scroll,
            port.focus_panel,
            getattr(port, "menu_focus", "items"),
            getattr(port, "active_menu_tab", ""),
            menu_tabs,
            active_labels,
            item_labels,
            item_enabled,
        )
        if port.main_full_redraw or port.render_cache.get("actions") != actions_sig:
            started = time.monotonic()
            ui_panels_api.main_panels_controller().draw_actions_panel(
                port,
                panel_top,
                panel_height,
                left_width,
                menu_rows=menu_rows,
                menu_visible_rows=menu_visible_rows,
                running_jobs=running_jobs,
                menu_tabs=list(menu_tabs),
                active_menu_tab=getattr(port, "active_menu_tab", ""),
                menu_focus=getattr(port, "menu_focus", "items"),
            )
            port.render_cache["actions"] = actions_sig
            port.ui_profile_slow("panel-actions-slow", started, threshold_ms=5.0, rows=len(menu_rows))
            rendered.append("actions")

    def _draw_details(
        self,
        port: Any,
        panel_top: int,
        right_left: int,
        details_height: int,
        right_width: int,
        item: MenuItem,
        running_jobs: list[dict[str, Any]],
        active_labels: tuple[str, ...],
        selection: tuple[str, ...],
        mapping_status: dict[str, str],
        rendered: list[str],
    ) -> None:
        details_sig = (
            right_width,
            details_height,
            port.selected,
            item.label,
            item.group,
            item.description,
            active_labels,
            job_api.any_job_running(running_jobs),
            selection,
            tuple(sorted(getattr(port, "build_params", {}).items())),
            getattr(port, "build_targets", ""),
            getattr(port, "docker_image", ""),
            getattr(port, "connection_state", ""),
            getattr(port, "board_connection_state", ""),
            config_accessor_api.network_deploy_project_name_for_config(port.config),
            config_accessor_api.board_tftp_project_dir_for_config(port.config),
            config_accessor_api.board_tftp_current_dir_for_config(port.config),
            config_accessor_api.board_nfs_project_dir_for_config(port.config),
            config_accessor_api.board_nfs_current_dir_for_config(port.config),
            config_accessor_api.remote_project_dir_for_config(port.config),
            config_accessor_api.board_artifacts_dir_for_config(port.config),
            config_accessor_api.board_console_device_for_config(port.config),
            config_accessor_api.board_ufs_loadaddr_for_config(port.config),
            mapping_status["text"],
            mapping_status["role"],
            port.item_enabled(item),
            port.disabled_reason(item) if not port.item_enabled(item) else "",
        )
        if port.main_full_redraw or port.render_cache.get("details") != details_sig:
            started = time.monotonic()
            ui_panels_api.main_panels_controller().draw_details_panel(port, panel_top, right_left, details_height, right_width, item)
            port.render_cache["details"] = details_sig
            port.ui_profile_slow("panel-details-slow", started, threshold_ms=5.0, item=item.label)
            rendered.append("details")

    def _draw_logs(
        self,
        port: Any,
        logs_top: int,
        right_left: int,
        logs_height: int,
        right_width: int,
        item: MenuItem,
        active_job_exists: bool,
        active_labels: tuple[str, ...],
        rendered: list[str],
    ) -> None:
        now = time.monotonic()
        job = ui_menu_api.display_job_for_item(
            item,
            active_job=port.active_job,
            board_job=port.board_job,
            last_board_job=port.last_board_job,
            last_job=port.last_job,
            last_board_jobs_by_label=getattr(port, "last_board_jobs_by_label", {}),
            last_jobs_by_label=getattr(port, "last_jobs_by_label", {}),
        )
        job_output = tuple(job_api.job_output_lines(job)[-5:]) if job is not None else ()
        logs_sig = (
            right_width,
            logs_height,
            port.focus_panel,
            item.label,
            active_labels,
            job.get("title", "") if job is not None else "",
            job_api.job_running(job),
            len(job_api.job_output_lines(job)) if job is not None else 0,
            job_output,
            port.log_scroll,
            port.log_follow,
        )
        should_draw_logs = port.main_full_redraw or port.render_cache.get("logs") != logs_sig
        if active_job_exists and port.logs_dirty and now - port.last_log_render_at < 0.15 and port.render_cache.get("logs") is not None:
            should_draw_logs = False
        if should_draw_logs:
            started = time.monotonic()
            ui_panels_api.main_panels_controller().draw_logs_panel(port, logs_top, right_left, logs_height, right_width, item)
            port.render_cache["logs"] = logs_sig
            port.last_log_render_at = now
            port.logs_dirty = False
            port.ui_profile_slow(
                "panel-logs-slow",
                started,
                threshold_ms=5.0,
                item=item.label,
                lines=len(job_api.job_output_lines(job)) if job is not None else 0,
            )
            rendered.append("logs")

    def _draw_footer(
        self,
        port: Any,
        height: int,
        width: int,
        active_job_exists: bool,
        rendered: list[str],
    ) -> None:
        footer = ui_status_segments_api.main_footer_text(active_job=active_job_exists, focus_panel=port.focus_panel)
        footer_sig = (width, footer, port.status)
        if port.main_full_redraw or port.render_cache.get("footer") != footer_sig:
            started = time.monotonic()
            ui_panels_api.main_panels_controller().draw_footer(port, height, width, active_job_exists=active_job_exists)
            port.render_cache["footer"] = footer_sig
            port.ui_profile_slow("panel-footer-slow", started, threshold_ms=5.0)
            rendered.append("footer")


def main_draw_controller(*, app_dir: Path) -> MainDrawController:
    return MainDrawController(app_dir=app_dir)
