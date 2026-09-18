"""Main TUI panel controllers."""

from __future__ import annotations

import curses
from pathlib import Path
from typing import Any

from components.config.api import accessors as config_accessor_api
from components.jobs.api import jobs as job_api
from components.ui.api import menu as ui_menu_api
from components.ui.api import session as ui_session_api
from components.ui.api import status_segments as ui_status_segments_api
from components.ui.api import text as ui_text_api


def _network_context_lines(config: dict[str, Any]) -> list[str]:
    return [
        f"Network project: {config_accessor_api.network_deploy_project_name_for_config(config)}",
        f"TFTP project:    {config_accessor_api.board_tftp_project_dir_for_config(config)}",
        f"TFTP current:    {config_accessor_api.board_tftp_current_dir_for_config(config)}",
        f"NFS project:     {config_accessor_api.board_nfs_project_dir_for_config(config)}",
        f"NFS current:     {config_accessor_api.board_nfs_current_dir_for_config(config)}",
    ]


def _split_group(group: str) -> tuple[str, str]:
    if " / " not in group:
        return group.strip(), ""
    parent, child = group.split(" / ", 1)
    return parent.strip(), child.strip()


def _details_context_lines(port: Any, item: Any) -> list[str]:
    parent, child = _split_group(str(getattr(item, "group", "")))
    if parent == "tftp/nfs":
        return _network_context_lines(port.config)
    if parent == "build" and child == "files mapping":
        selection = ", ".join(port.mapping_selection_cache) or "none"
        return [f"Selected mappings: {selection}"]
    if parent == "build":
        params = " ".join(f"{key}={value}" for key, value in sorted(getattr(port, "build_params", {}).items()))
        return [
            f"Targets:      {getattr(port, 'build_targets', '') or '<not set>'}",
            f"Docker image: {getattr(port, 'docker_image', '') or '<not set>'}",
            f"Build params: {params or '<none>'}",
            f"Project dir:  {config_accessor_api.remote_project_dir_for_config(port.config)}",
        ]
    if parent == "flashing":
        return [
            f"Board host:   {config_accessor_api.board_host_spec_for_config(port.config)}",
            f"Artifacts:    {config_accessor_api.board_artifacts_dir_for_config(port.config)}",
            f"Console:      {config_accessor_api.board_console_device_for_config(port.config) or '<not set>'}",
            f"UFS loadaddr: {config_accessor_api.board_ufs_loadaddr_for_config(port.config) or '<not set>'}",
        ]
    if parent == "sessions":
        return [
            f"Build host: {config_accessor_api.remote_label_for_config(port.config)}  {config_accessor_api.remote_spec_for_config(port.config)}",
            f"Build connection: {getattr(port, 'connection_state', '') or 'unknown'}",
            f"Board host: {config_accessor_api.board_host_label_for_config(port.config)}  {config_accessor_api.board_host_spec_for_config(port.config)}",
            f"Board connection: {getattr(port, 'board_connection_state', '') or 'unknown'}",
        ]
    if parent == "configuration":
        return [
            f"Project:    {config_accessor_api.network_deploy_project_name_for_config(port.config)}",
            f"Build host: {config_accessor_api.remote_label_for_config(port.config)}",
            f"Board host: {config_accessor_api.board_host_label_for_config(port.config)}",
            f"Board type: {config_accessor_api.board_type_for_config(port.config)}",
        ]
    return []


class MainPanelsController:
    """Render and scroll the details and logs panels."""

    def draw_header(self, port: Any, width: int, *, app_dir: Path) -> None:
        port.draw_box(0, 0, 10, width, config_accessor_api.ui_title(port.config))
        inner_width = max(1, width - 4)
        label_width = 14
        entries = [
            ("Build host", f"{config_accessor_api.remote_label_for_config(port.config)}  {config_accessor_api.remote_spec_for_config(port.config)}:{config_accessor_api.remote_project_dir_for_config(port.config)}"),
            ("Board host", f"{config_accessor_api.board_host_label_for_config(port.config)}  {config_accessor_api.board_host_spec_for_config(port.config)}"),
            ("Local overlay", str(config_accessor_api.local_project_dir_for_config(port.config, app_dir))),
            ("Manifest", config_accessor_api.moulin_manifest_name_for_config(port.config)),
        ]
        for offset, (label, value) in enumerate(entries, start=1):
            port.add(offset, 2, f"{label}:".ljust(label_width), port.accent_attr())
            port.add(offset, 2 + label_width, ui_text_api.fit_text(value, inner_width - label_width))

        row = 5
        x = 2
        port.add(row, x, "Connections:", port.accent_attr())
        x += len("Connections: ")
        port.add(row, x, "build=", 0)
        x += len("build=")
        port.add(row, x, port.connection_state, port.connection_attr_for(port.connection_state))
        x += len(port.connection_state) + 2
        port.add(row, x, "board=", 0)
        x += len("board=")
        port.add(row, x, port.board_connection_state, port.connection_attr_for(port.board_connection_state))
        x += len(port.board_connection_state) + 4
        param_segments = [
            (text, port.role_attr(role))
            for text, role in ui_status_segments_api.build_param_segments(port.build_params)
        ]
        port.add_segments(row, x, width - x - 2, param_segments + [("   Docker image: ", 0), (port.docker_image, port.accent_attr())])
        port.add(6, 2, "Targets:".ljust(label_width), port.accent_attr())
        port.add(6, 2 + label_width, ui_text_api.fit_text(port.build_targets, inner_width - label_width))
        preflight_segments = [
            (text, port.role_attr(role))
            for text, role in ui_status_segments_api.preflight_segments(port.preflight, connected=bool(port.connection_state == "connected"))
        ]
        port.add_segments(7, 2, inner_width, [("Preflight: ", port.accent_attr())] + preflight_segments)
        port.add(8, 2, "Mappings:".ljust(label_width), port.accent_attr())
        mapping_status = port.mapping_status_snapshot()
        port.add(8, 2 + label_width, ui_text_api.fit_text(mapping_status["text"], inner_width - label_width), port.role_attr(mapping_status["role"]))

    def draw_actions_panel(
        self,
        port: Any,
        panel_top: int,
        panel_height: int,
        left_width: int,
        *,
        menu_rows: list[tuple[str, int | None]],
        menu_visible_rows: int,
        running_jobs: list[dict[str, Any]],
        menu_tabs: list[str] | None = None,
        active_menu_tab: str = "",
        menu_focus: str = "items",
    ) -> None:
        actions_attr = port.warn_attr() if port.focus_panel == "actions" else 0
        port.draw_box(panel_top, 0, panel_height, left_width, "Actions", actions_attr)
        row = panel_top + 1
        tabs = menu_tabs or []
        items_active = port.focus_panel == "actions" and menu_focus == "items"
        if tabs:
            labels = {
                tab: f"[{ui_menu_api.tab_label(tab)}]"
                if tab == active_menu_tab
                else f" {ui_menu_api.tab_label(tab)} "
                for tab in tabs
            }
            active_index = tabs.index(active_menu_tab) if active_menu_tab in tabs else 0
            tab_width = max(0, left_width - 6)
            visible_tabs: list[str] = []
            used_width = 0
            for tab in tabs[active_index:]:
                needed = len(labels[tab]) + (1 if visible_tabs else 0)
                if visible_tabs and used_width + needed > tab_width:
                    break
                visible_tabs.append(tab)
                used_width += needed
            for tab in reversed(tabs[:active_index]):
                needed = len(labels[tab]) + (1 if visible_tabs else 0)
                if visible_tabs and used_width + needed > tab_width:
                    break
                visible_tabs.insert(0, tab)
                used_width += needed
            if not visible_tabs and tabs:
                visible_tabs = [tabs[active_index]]
            x = 3
            for tab in visible_tabs:
                label = labels[tab]
                attr = port.group_attr()
                if tab == active_menu_tab:
                    attr = port.warn_attr()
                if x < left_width - 3:
                    port.add(row, x, label[: max(0, left_width - x - 3)], attr)
                x += len(label) + 1
            row += 2
        for label, item_index in menu_rows[port.menu_scroll : port.menu_scroll + menu_visible_rows]:
            if item_index is None:
                attr = port.group_attr() if label else 0
            else:
                menu_item = port.items[item_index]
                if ui_menu_api.job_for_item(menu_item, running_jobs) is not None:
                    attr = port.running_attr()
                    if items_active and item_index == port.selected:
                        attr |= curses.A_REVERSE
                elif items_active and item_index == port.selected:
                    attr = port.selected_attr()
                elif not port.item_enabled(menu_item):
                    attr = port.disabled_attr()
                else:
                    attr = 0
            port.add(row, 2, label[: left_width - 4].ljust(left_width - 4), attr)
            row += 1

    def draw_footer(self, port: Any, height: int, width: int, *, active_job_exists: bool) -> str:
        footer = ui_status_segments_api.main_footer_text(
            active_job=active_job_exists,
            focus_panel=port.focus_panel,
            menu_focus=getattr(port, "menu_focus", "items"),
        )
        port.add(height - 2, 0, footer[:width].ljust(width), port.accent_attr())
        port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
        return footer

    def scroll_logs(self, port: Any, delta: int) -> None:
        item = port.items[port.selected]
        job = self._display_job(port, item)
        height, _ = port.screen.getmaxyx()
        plan = job_api.log_scroll_plan(
            job,
            job_api.log_visible_lines(height, expanded=port.logs_expanded),
            follow=port.log_follow,
            scroll=port.log_scroll,
            delta=delta,
        )
        if "status" in plan:
            port.status = str(plan["status"])
            return
        port.log_scroll = int(plan["log_scroll"])
        port.log_follow = bool(plan["log_follow"])

    def draw_details_panel(self, port: Any, top: int, left: int, height: int, width: int, item: Any) -> None:
        port.draw_box(top, left, height, width, "Details")
        x = left + 2
        inner = width - 4
        row = top + 2
        port.add(
            row,
            x,
            ui_session_api.connection_menu_label(
                item.label,
                build_state=port.connection_state,
                board_state=port.board_connection_state,
            )[:inner],
            curses.A_BOLD,
        )
        row += 2
        row = port.draw_wrapped(row, x, inner, item.description, max_lines=3)
        row += 1

        job = self._display_job(port, item)
        if job is not None and job_api.job_running(job):
            state = "RUNNING"
            port.add(row, x, f"Status: {state}", port.running_attr() if state == "RUNNING" else port.group_attr())
            row += 1
        elif not port.item_enabled(item):
            port.add(row, x, f"Status: {port.disabled_reason(item)}"[:inner], port.disabled_attr())
            row += 1

        for line in _details_context_lines(port, item):
            if row >= top + height - 3:
                break
            available_rows = max(1, top + height - 3 - row)
            row = port.draw_wrapped(row, x, inner, line, max_lines=available_rows)
        if item.label == "Copy mapped files to build host" and row < top + height - 2:
            mapping_status = port.mapping_status_snapshot()
            port.add(row, x, f"Copy status: {mapping_status['text']}"[:inner], port.role_attr(mapping_status["role"]))
            row += 1

    def draw_logs_panel(self, port: Any, top: int, left: int, height: int, width: int, item: Any) -> None:
        border_attr = port.warn_attr() if port.focus_panel == "logs" else 0
        port.draw_box(top, left, height, width, "Logs", border_attr)
        x = left + 2
        inner = width - 4
        row = top + 2
        job = self._display_job(port, item)
        if job is None:
            port.add(row, x, "No command log for this action yet."[:inner], port.disabled_attr())
            return

        state = "RUNNING" if job_api.job_running(job) else "DONE"
        port.add(row, x, f"{job.get('title', 'Command')} [{state}]"[:inner], port.running_attr() if state == "RUNNING" else port.group_attr())
        row += 2
        visible = max(1, top + height - 2 - row)
        output = job_api.job_output_lines(job)
        if not output:
            port.add(row, x, "Waiting for output..."[:inner], port.disabled_attr())
            return
        scroll, port.log_follow = job_api.clamp_log_scroll(
            job,
            visible,
            follow=port.log_follow,
            scroll=port.log_scroll,
        )
        port.log_scroll = scroll
        shown = output[scroll : scroll + visible]
        first = min(len(output), scroll + 1)
        last = min(len(output), scroll + len(shown))
        follow = " follow" if port.log_follow else ""
        counter = f"lines {first}-{last}/{len(output)}{follow}"
        port.add(top, max(left + 2, left + width - len(counter) - 2), counter[: max(0, width - 4)], port.accent_attr())
        for line in shown:
            port.add(row, x, line[:inner])
            row += 1

    def draw_expanded_logs(self, port: Any, height: int, width: int, item: Any) -> None:
        port.screen.erase()
        self.draw_logs_panel(port, 0, 0, max(3, height - 2), width, item)
        footer = "Logs full | Up/Down/PgUp/PgDn scroll | f/Esc shrink"
        port.add(height - 2, 0, footer[:width].ljust(width), port.accent_attr())
        port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)

    def _display_job(self, port: Any, item: Any) -> dict[str, Any] | None:
        return ui_menu_api.display_job_for_item(
            item,
            active_job=port.active_job,
            board_job=port.board_job,
            last_board_job=port.last_board_job,
            last_job=port.last_job,
            last_board_jobs_by_label=getattr(port, "last_board_jobs_by_label", {}),
            last_jobs_by_label=getattr(port, "last_jobs_by_label", {}),
        )


def main_panels_controller() -> MainPanelsController:
    return MainPanelsController()
