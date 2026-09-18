"""Project configuration screen renderer."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from components.config.api import accessors as config_accessor_api
from components.host_config.api import fields as host_field_api
from components.project_config.api import fields as project_field_api
from components.config.api import profiles as config_profile_api
from components.project_config_ui.api import project_screen_state as config_project_screen_state_api
from components.ui.api import text as ui_text_api


@dataclass(frozen=True)
class ProjectScreenRenderResult:
    projects: list[dict[str, Any]]
    fields: list[dict[str, Any]]
    selected_project: dict[str, Any] | None
    editing_cursor_yx: tuple[int, int] | None


@dataclass(frozen=True)
class ProjectFieldDisplayRow:
    kind: str
    field: dict[str, Any] | None = None
    field_index: int | None = None
    label: str = ""


class ProjectScreenRenderer:
    """Render the project configuration screen from controller state."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        app_dir: Path,
        project_fields_factory: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        project_field_service: project_field_api.ProjectFieldService | None = None,
    ) -> None:
        self.config = config
        self.app_dir = app_dir
        self.project_fields_factory = project_fields_factory
        self.project_field_service = project_field_service or project_field_api.project_field_service()

    def render(
        self,
        port: Any,
        *,
        height: int,
        width: int,
        params: list[dict[str, Any]],
        screen_state: config_project_screen_state_api.ProjectScreenStateController,
    ) -> ProjectScreenRenderResult:
        state = screen_state.state
        project = config_profile_api.active_project(self.config)
        projects = screen_state.projects()
        screen_state.sync_selection(projects, [])
        selected_project = screen_state.selected_project(projects)

        panel_top = 3
        panel_height = height - 6
        self._render_header(port, width, state.focus, project)
        port.draw_box(panel_top, 0, panel_height, width, "Projects")

        table_w = width - 4
        detail_x = 2
        detail_w = width - 4
        fields: list[dict[str, Any]] = []
        if selected_project is not None:
            fields = self.project_fields_factory(params)
            screen_state.sync_selection(projects, fields)
        else:
            screen_state.sync_selection(projects, [])

        min_detail_rows = 2 + min(len(fields), 11) + 3
        visible_projects = max(1, min(max(1, len(projects)), panel_height - min_detail_rows))
        table_y = panel_top + 1
        self._render_project_list(port, projects, table_y, table_w, visible_projects, state)

        row = self._render_project_count_if_needed(port, projects, visible_projects, table_y, detail_x, detail_w, state)
        editing_cursor_yx = self._render_project_details(
            port,
            fields,
            selected_project,
            row,
            height,
            panel_top,
            panel_height,
            detail_x,
            detail_w,
            state,
        )
        self._render_footer(port, height, width)
        return ProjectScreenRenderResult(
            projects=projects,
            fields=fields,
            selected_project=selected_project,
            editing_cursor_yx=editing_cursor_yx,
        )

    def _render_header(self, port: Any, width: int, focus: str, project: dict[str, Any]) -> None:
        port.add(0, 0, "Project configurations"[:width], curses.A_BOLD)
        active_name = str(project.get("label") or project.get("name") or "<none>")
        port.add(
            1,
            0,
            ui_text_api.fit_text(
                (
                    f"Active: {active_name} | Build host: "
                    f"{config_accessor_api.remote_spec_for_config(self.config)}:"
                    f"{config_accessor_api.remote_project_dir_for_config(self.config)}"
                ),
                width,
            ),
        )
        port.add(
            2,
            0,
            f"Focus: {'project list' if focus == 'projects' else 'fields'}"[:width],
            port.accent_attr(),
        )

    def _render_project_list(
        self,
        port: Any,
        projects: list[dict[str, Any]],
        table_y: int,
        table_w: int,
        visible_projects: int,
        state: config_project_screen_state_api.ProjectScreenState,
    ) -> None:
        project_scroll = host_field_api.host_profile_page_scroll(state.project_index, len(projects), visible_projects)
        port.add(table_y, 2, ui_text_api.fit_text("A Name               Manifest                         Targets", table_w), port.accent_attr())
        if not projects:
            port.add(table_y + 1, 2, "No projects configured. Press 'a' to add one."[:table_w], port.disabled_attr())
            return
        for offset, profile in enumerate(projects[project_scroll : project_scroll + visible_projects]):
            item_index = project_scroll + offset
            row_model = project_field_api.project_profile_row_model(
                profile,
                active_name=str(self.config.get("active_project", "")),
                selected=state.focus == "projects" and item_index == state.project_index,
            )
            attr = self._project_row_attr(port, str(row_model["state"]))
            port.add(table_y + 1 + offset, 2, ui_text_api.fit_text(str(row_model["text"]), table_w).ljust(table_w), attr)

    def _render_project_count_if_needed(
        self,
        port: Any,
        projects: list[dict[str, Any]],
        visible_projects: int,
        table_y: int,
        detail_x: int,
        detail_w: int,
        state: config_project_screen_state_api.ProjectScreenState,
    ) -> int:
        row = table_y + visible_projects + 2
        if len(projects) > visible_projects:
            port.add(
                row,
                detail_x,
                host_field_api.host_profile_count_label(state.project_index, len(projects), "projects")[:detail_w],
                port.disabled_attr(),
            )
            row += 1
        return row

    def _render_project_details(
        self,
        port: Any,
        fields: list[dict[str, Any]],
        selected_project: dict[str, Any] | None,
        row: int,
        height: int,
        panel_top: int,
        panel_height: int,
        detail_x: int,
        detail_w: int,
        state: config_project_screen_state_api.ProjectScreenState,
    ) -> tuple[int, int] | None:
        if selected_project is None:
            port.add(row, detail_x, "Selected project: <none>"[:detail_w], port.disabled_attr())
            return None
        display_rows = self._field_display_rows(fields)
        visible_fields = max(0, panel_top + panel_height - row - 5)
        selected_display_index = self._display_index_for_field(display_rows, state.field_index)
        field_scroll = min(
            max(0, selected_display_index - visible_fields + 1),
            max(0, len(display_rows) - visible_fields),
        )
        editing_cursor_yx = self._render_field_rows(
            port,
            display_rows,
            selected_project,
            row,
            field_scroll,
            visible_fields,
            detail_x,
            detail_w,
            state,
        )
        row += len(display_rows[field_scroll : field_scroll + visible_fields])
        self._render_field_hint(port, fields, selected_project, row, height, detail_x, detail_w, state)
        return editing_cursor_yx

    def _render_field_rows(
        self,
        port: Any,
        display_rows: list[ProjectFieldDisplayRow],
        selected_project: dict[str, Any],
        row: int,
        field_scroll: int,
        visible_fields: int,
        detail_x: int,
        detail_w: int,
        state: config_project_screen_state_api.ProjectScreenState,
    ) -> tuple[int, int] | None:
        editing_cursor_yx: tuple[int, int] | None = None
        for visible_offset, display_row in enumerate(display_rows[field_scroll : field_scroll + visible_fields]):
            if display_row.kind == "blank":
                port.add(row, detail_x, "".ljust(detail_w))
                row += 1
                continue
            if display_row.kind == "heading":
                port.add(row, detail_x, str(display_row.label).upper()[:detail_w], port.accent_attr())
                row += 1
                continue
            field = display_row.field or {}
            item_index = int(display_row.field_index or 0)
            key = str(field["key"])
            is_editing = state.focus == "fields" and key == state.editing_key
            raw_value = state.editing_value if is_editing else self.project_field_service.field_value(selected_project, field)
            enabled = self.project_field_service.field_enabled_for_config(
                field,
                selected_project,
                self.config,
                connected=port.connection_state == "connected",
            )
            row_model = host_field_api.host_field_row_model(
                label=str(field["label"]),
                key=key,
                profile=selected_project,
                value=raw_value,
                enabled=enabled,
                selected=state.focus == "fields" and item_index == state.field_index,
                editing=is_editing,
                label_width=22,
            )
            attr = self._field_row_attr(port, str(row_model["state"]))
            port.add(row, detail_x, ui_text_api.fit_text(str(row_model["text"]), detail_w).ljust(detail_w), attr)
            if is_editing:
                cursor_x = min(detail_x + 22 + state.editing_cursor, detail_x + detail_w - 1)
                editing_cursor_yx = (row, cursor_x)
            row += 1
        return editing_cursor_yx

    def _field_display_rows(self, fields: list[dict[str, Any]]) -> list[ProjectFieldDisplayRow]:
        rows: list[ProjectFieldDisplayRow] = []
        current_group = ""
        for index, field in enumerate(fields):
            group = self._field_group(field)
            if group != current_group:
                if rows:
                    rows.append(ProjectFieldDisplayRow(kind="blank"))
                rows.append(ProjectFieldDisplayRow(kind="heading", label=group))
                current_group = group
            rows.append(ProjectFieldDisplayRow(kind="field", field=field, field_index=index))
        return rows

    @staticmethod
    def _display_index_for_field(display_rows: list[ProjectFieldDisplayRow], field_index: int) -> int:
        for index, row in enumerate(display_rows):
            if row.field_index == field_index:
                return index
        return 0

    @staticmethod
    def _field_group(field: dict[str, Any]) -> str:
        key = str(field.get("key", ""))
        kind = str(field.get("kind", ""))
        if key in ("name", "label"):
            return "Profile"
        if key in ("project_dir", "local_project_dir"):
            return "Directories"
        if key in ("git_url", "git_ref"):
            return "Git"
        if key in ("moulin_manifest", "dockerfile", "docker_image") or kind in ("param", "targets"):
            return "Build"
        if key == "board_artifacts":
            return "Artifacts"
        return "Other"

    def _render_field_hint(
        self,
        port: Any,
        fields: list[dict[str, Any]],
        selected_project: dict[str, Any],
        row: int,
        height: int,
        detail_x: int,
        detail_w: int,
        state: config_project_screen_state_api.ProjectScreenState,
    ) -> None:
        if row >= height - 3 or not fields or state.focus != "fields":
            return
        field = fields[state.field_index]
        if state.editing_key:
            port.add(row, detail_x, "Enter: save | Esc: cancel | Left/Right/Home/End: move cursor"[:detail_w], port.accent_attr())
            return
        enabled = self.project_field_service.field_enabled_for_config(
            field,
            selected_project,
            self.config,
            connected=port.connection_state == "connected",
        )
        message = (
            self.project_field_service.field_hint_for_config(field, self.config, app_dir=str(self.app_dir))
            if enabled
            else self.project_field_service.field_disabled_reason_for_config(field, selected_project, self.config)
        )
        max_lines = max(1, height - 3 - row)
        port.draw_wrapped(row, detail_x, detail_w, message, port.accent_attr() if enabled else port.disabled_attr(), max_lines=max_lines)

    def _render_footer(self, port: Any, height: int, width: int) -> None:
        footer = "Left/Right: projects/fields | Enter: edit/open/save | a: add | d: delete | s: set active | Esc: projects/back | q: back"
        port.add(height - 2, 0, footer[:width], port.accent_attr())
        port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)

    def _project_row_attr(self, port: Any, state: str) -> int:
        if state == "selected-active":
            return port.selected_active_attr()
        if state == "selected":
            return port.selected_attr()
        if state == "active":
            return port.active_row_attr()
        return 0

    def _field_row_attr(self, port: Any, state: str) -> int:
        if state == "editing":
            return port.editing_attr()
        if state == "selected":
            return port.selected_attr()
        if state == "selected-disabled":
            return port.selected_disabled_attr()
        if state == "disabled":
            return port.disabled_attr()
        return 0


def project_screen_renderer(
    config: dict[str, Any],
    *,
    app_dir: Path,
    project_fields_factory: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> ProjectScreenRenderer:
    return ProjectScreenRenderer(
        config,
        app_dir=app_dir,
        project_fields_factory=project_fields_factory,
    )
