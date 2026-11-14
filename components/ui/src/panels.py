"""Main TUI panel controllers."""

from __future__ import annotations

import curses
import shlex
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


def _wrapped_segment_rows(
    segments: list[tuple[str, int]],
    width: int,
    *,
    max_rows: int = 2,
) -> list[list[tuple[str, int]]]:
    """Wrap complete styled segments without splitting normal-sized values."""
    rows: list[list[tuple[str, int]]] = [[]]
    used = 0
    for index, segment in enumerate(segments):
        text, _attr = segment
        if text == " | ":
            group_width = 0
            for next_text, _next_attr in segments[index + 1:]:
                if next_text == " | ":
                    break
                group_width += len(next_text)
            if used and used + len(text) + group_width > width and len(rows) < max_rows:
                rows.append([("  ", 0)])
                used = 2
                continue
        next_text = segments[index + 1][0] if index + 1 < len(segments) else ""
        if (
            text.endswith("=")
            and next_text
            and next_text != " | "
            and used + len(text) + len(next_text) > width
            and len(rows) < max_rows
        ):
            rows.append([("  ", 0)])
            used = 2
        if used and used + len(text) > width and len(rows) < max_rows:
            rows.append([("  ", 0)])
            used = 2
        rows[-1].append(segment)
        used += len(text)
    return rows


def _ownership_status_role(state: str) -> str:
    if state in {"free", "owned"}:
        return "ok"
    if state in {"busy", "checking"}:
        return "warn"
    if state == "error":
        return "error"
    return "disabled"


def _details_context_lines(port: Any, item: Any) -> list[str]:
    parent, child = _split_group(str(getattr(item, "group", "")))
    if parent == "tftp/nfs":
        return _network_context_lines(port.config)
    if parent == "build" and child == "files mapping":
        selection = ", ".join(port.mapping_selection_cache) or "none"
        return [f"Selected mappings: {selection}"]
    if parent == "build":
        if item.label in {"Prepare remote project", "Checkout project Git ref"}:
            return [
                f"Build host:  {config_accessor_api.remote_spec_for_config(port.config)}",
                f"Project dir: {config_accessor_api.remote_project_dir_for_config(port.config)}",
                f"Git URL:     {config_accessor_api.project_git_url_for_config(port.config) or '<not set>'}",
                f"Git ref:     {config_accessor_api.project_git_ref_for_config(port.config) or '<not set>'}",
                f"Preflight:   {getattr(port, 'preflight', '') or '<not run>'}",
            ]
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

    def draw_header(self, port: Any, width: int) -> None:
        port.draw_box(
            0,
            0,
            15 if width < 110 else 12,
            width,
            config_accessor_api.ui_title(port.config),
            title_attr=port.warn_attr(),
        )
        inner_width = max(1, width - 4)
        narrow = width < 110
        ownership = getattr(port, "board_ownership_status", {})

        port.add_segments(
            1,
            2,
            inner_width,
            [
                ("--- ", port.section_attr()),
                ("Build host ", port.section_attr()),
                (
                    f"{config_accessor_api.remote_label_for_config(port.config)} "
                    f"({config_accessor_api.remote_spec_for_config(port.config)}) ",
                    port.section_attr(),
                ),
                ("-" * inner_width, port.section_attr()),
            ],
        )
        build_host_segments = [
            ("Connection: ", port.accent_attr()),
            (port.connection_state, port.connection_attr_for(port.connection_state)),
        ]
        if not narrow:
            build_host_segments.extend([
                (" | ", port.section_attr()),
                ("Projects: ", port.accent_attr()),
                (config_accessor_api.build_host_projects_dir_for_config(port.config), 0),
            ])
        disk_status = getattr(port, "preflight_values", {}).get("disk", "")
        if disk_status:
            build_host_segments.extend([
                (" | ", port.section_attr()),
                ("Disk: ", port.accent_attr()),
                (disk_status, 0),
            ])
        build_host_segments.extend([
            (" | ", port.section_attr()),
            ("Docker: ", port.accent_attr()),
            (port.docker_image, 0),
        ])
        port.add_segments(2, 2, inner_width, build_host_segments)
        board_section_row = 3
        if narrow:
            projects_label = "Projects: "
            port.add_segments(
                3,
                2,
                inner_width,
                [
                    (projects_label, port.accent_attr()),
                    (
                        ui_text_api.fit_text(
                            config_accessor_api.build_host_projects_dir_for_config(port.config),
                            inner_width - len(projects_label),
                        ),
                        0,
                    ),
                ],
            )
            board_section_row = 4

        port.add_segments(
            board_section_row,
            2,
            inner_width,
            [
                ("--- ", port.section_attr()),
                ("Board host ", port.section_attr()),
                (
                    f"{config_accessor_api.board_access_host_label_for_config(port.config)} "
                    f"({config_accessor_api.board_host_spec_for_config(port.config)}) ",
                    port.section_attr(),
                ),
                ("-" * inner_width, port.section_attr()),
            ],
        )
        board_segments = [
            ("Connection: ", port.accent_attr()),
            (port.board_connection_state, port.connection_attr_for(port.board_connection_state)),
            (" | ", port.section_attr()),
            ("Board: ", port.accent_attr()),
            (config_accessor_api.board_label_for_config(port.config), 0),
        ]
        if ownership.get("state") != "disabled":
            board_segments.extend([
                (" | ", port.section_attr()),
                ("Ownership: ", port.accent_attr()),
                (
                    str(ownership.get("text") or "unknown"),
                    port.role_attr(_ownership_status_role(str(ownership.get("state") or "unknown"))),
                ),
            ])
        port.add_segments(board_section_row + 1, 2, inner_width, board_segments)

        project_section_row = board_section_row + 2
        port.add_segments(
            project_section_row,
            2,
            inner_width,
            [
                ("--- ", port.section_attr()),
                ("Project ", port.section_attr()),
                (
                    config_accessor_api.moulin_manifest_name_for_config(port.config) + " ",
                    port.section_attr(),
                ),
                ("-" * inner_width, port.section_attr()),
            ],
        )

        build_param_segments = [
            (text, port.role_attr(role))
            for text, role in ui_status_segments_api.build_param_segments(port.build_params)
        ]
        row = project_section_row + 1
        param_rows = _wrapped_segment_rows(build_param_segments, inner_width) if narrow else [build_param_segments]
        for segments in param_rows:
            port.add_segments(row, 2, inner_width, segments)
            row += 1
        target_segments: list[tuple[str, int]] = [("Targets: ", port.accent_attr())]
        selected_targets = shlex.split(port.build_targets)
        selected_target_set = set(selected_targets)
        candidate_targets = list(dict.fromkeys(getattr(port, "build_target_candidates", []) or selected_targets))
        candidate_target_set = set(candidate_targets)
        unknown_targets = [target for target in selected_targets if target not in candidate_target_set]
        available_targets = candidate_targets + unknown_targets
        for index, target in enumerate(available_targets):
            if index:
                target_segments.append((" | ", port.section_attr()))
            if target in unknown_targets:
                attr = port.warn_attr()
            elif target in selected_target_set:
                attr = 0
            else:
                attr = port.disabled_attr()
            target_segments.append((target, attr))
        target_rows = _wrapped_segment_rows(target_segments, inner_width) if narrow else [target_segments]
        for segments in target_rows:
            port.add_segments(row, 2, inner_width, segments)
            row += 1

        product_ref_segments = [
            (text, port.role_attr(role))
            for text, role in ui_status_segments_api.product_ref_segments(
                config_accessor_api.project_git_ref_for_config(port.config),
                getattr(port, "preflight_values", {}),
                narrow=narrow,
            )
        ]
        port.add_segments(
            row,
            2,
            inner_width,
            product_ref_segments,
        )
        row += 1
        port.add_segments(
            row,
            2,
            inner_width,
            [
                ("--- ", port.section_attr()),
                ("Readiness ", port.section_attr()),
                ("-" * inner_width, port.section_attr()),
            ],
        )
        row += 1
        preflight_segments = [
            (text, port.role_attr(role))
            for text, role in ui_status_segments_api.preflight_segments(
                ui_status_segments_api.compact_header_preflight(port.preflight, narrow=narrow),
                connected=bool(port.connection_state == "connected"),
            )
        ]
        port.add_segments(row, 2, inner_width, [("Preflight: ", port.accent_attr())] + preflight_segments)

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
        menu_tab_labels: dict[str, str] | None = None,
        active_menu_tab: str = "",
        menu_focus: str = "items",
    ) -> None:
        actions_attr = port.warn_attr() if port.focus_panel == "actions" else 0
        port.draw_box(panel_top, 0, panel_height, left_width, "Actions", actions_attr)
        row = panel_top + 1
        tabs = menu_tabs or []
        tab_names = menu_tab_labels or {}
        items_active = port.focus_panel == "actions" and menu_focus == "items"
        if tabs:
            labels = {
                tab: f"[{tab_names.get(tab, ui_menu_api.tab_label(tab))}]"
                if tab == active_menu_tab
                else f" {tab_names.get(tab, ui_menu_api.tab_label(tab))} "
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

    def draw_footer(
        self,
        port: Any,
        height: int,
        width: int,
        *,
        active_job_exists: bool,
        selected_action_running: bool = False,
    ) -> str:
        footer = ui_status_segments_api.main_footer_text(
            active_job=active_job_exists,
            focus_panel=port.focus_panel,
            menu_focus=getattr(port, "menu_focus", "items"),
            selected_action_running=selected_action_running,
        )
        port.add(height - 2, 0, footer[:width].ljust(width), port.accent_attr())
        port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
        return footer

    def scroll_logs(self, port: Any, delta: int) -> None:
        item = port.items[port.selected]
        job = self._display_job(port, item)
        height, width = port.screen.getmaxyx()
        inner_width = max(1, (width - 4) if port.logs_expanded else ((width - 1) // 2 - 5))
        plan = job_api.log_scroll_plan(
            job,
            job_api.log_visible_lines(height, expanded=port.logs_expanded),
            follow=port.log_follow,
            scroll=port.log_scroll,
            delta=delta,
            width=inner_width,
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

        running = job_api.job_running(job)
        stopped = not running and bool(job.get("stopping"))
        failed = not running and int(job.get("rc", 0) or 0) != 0
        if running:
            state, state_attr = "RUNNING", port.running_attr()
        elif stopped:
            state, state_attr = "STOPPED", port.group_attr()
        elif failed:
            state, state_attr = "FAILED", port.warn_attr()
        else:
            state, state_attr = "DONE", port.group_attr()
        port.add(row, x, f"{job.get('title', 'Command')} [{state}]"[:inner], state_attr)
        row += 2
        visible = max(1, top + height - 2 - row)
        output, source_indices = job_api.wrapped_job_output_snapshot(job, inner)
        if not output:
            port.add(row, x, "Waiting for output..."[:inner], port.disabled_attr())
            return
        scroll, port.log_follow = job_api.clamp_log_scroll(
            job,
            visible,
            follow=port.log_follow,
            scroll=port.log_scroll,
            width=inner,
        )
        cursor = getattr(port, "log_selection_cursor", None)
        if port.logs_expanded and cursor is not None and source_indices:
            latest_source_index = max(source_indices)
            if port.log_follow and getattr(port, "log_selection_anchor", None) is None:
                cursor = latest_source_index
            else:
                cursor = min(max(0, int(cursor)), latest_source_index)
            port.log_selection_cursor = cursor
            if not port.log_follow:
                cursor_row = next(
                    index
                    for index, source_index in enumerate(source_indices)
                    if source_index == cursor
                )
                if cursor_row < scroll:
                    scroll = cursor_row
                elif cursor_row >= scroll + visible:
                    scroll = max(0, cursor_row - visible + 1)
        port.log_scroll = scroll
        shown = output[scroll : scroll + visible]
        first = min(len(output), scroll + 1)
        last = min(len(output), scroll + len(shown))
        follow = " follow" if port.log_follow else ""
        counter = f"lines {first}-{last}/{len(output)}{follow}"
        port.add(top, max(left + 2, left + width - len(counter) - 2), counter[: max(0, width - 4)], port.accent_attr())
        anchor = getattr(port, "log_selection_anchor", None)
        cursor = getattr(port, "log_selection_cursor", None)
        selection = sorted((int(anchor), int(cursor))) if anchor is not None and cursor is not None else None
        for offset, line in enumerate(shown):
            visual_index = scroll + offset
            source_index = source_indices[visual_index]
            selected = selection is not None and selection[0] <= source_index <= selection[1]
            current = cursor is not None and source_index == int(cursor)
            if current:
                attr = port.selected_active_attr()
            elif selected:
                attr = port.selected_attr()
            else:
                attr = 0
            rendered = line[:inner]
            if not rendered and (current or selected):
                rendered = " "
            port.add(row, x, rendered, attr)
            row += 1

    def draw_expanded_logs(self, port: Any, height: int, width: int, item: Any) -> None:
        port.screen.erase()
        self.draw_logs_panel(port, 0, 0, max(3, height - 2), width, item)
        if getattr(port, "log_selection_anchor", None) is not None:
            footer = "Logs range | Shift+Up/Down extend | c copy and clear | Esc clear"
        else:
            footer = "Logs full | Up/Down cursor | Shift+Up/Down select | c copy | f/Esc shrink"
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
