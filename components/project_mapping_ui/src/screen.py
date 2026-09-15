"""Controllers for project mapping screens."""

from __future__ import annotations

import curses
from pathlib import Path
from typing import Any, Callable

from components.config.api import accessors as config_accessors
from components.project.api.browser_workflow import ProjectBrowserWorkflowService, project_browser_workflow_service
from components.project.api.core import ProjectMappingCoreService, project_mapping_core_service
from components.project.api.presentation import ProjectMappingPresentationService, project_mapping_presentation_service
from components.project.api.selection import ProjectMappingSelectionService, project_mapping_selection_service
from components.ui.api import input as ui_input_api
from components.ui.api import menu as ui_menu_api


class ProjectMappingScreenController:
    """Own interactive project mapping screen workflows."""

    def __init__(
        self,
        *,
        mapping_service: ProjectMappingCoreService | None = None,
        browser_service: ProjectBrowserWorkflowService | None = None,
        presentation_service: ProjectMappingPresentationService | None = None,
        selection_service: ProjectMappingSelectionService | None = None,
    ) -> None:
        self.mapping_service = mapping_service or project_mapping_core_service()
        self.browser_service = browser_service or project_browser_workflow_service()
        self.presentation_service = presentation_service or project_mapping_presentation_service()
        self.selection_service = selection_service or project_mapping_selection_service(mapping_service=self.mapping_service)

    def run_delete_mapping_screen(
        self,
        port: Any,
        config: dict[str, Any],
        app_dir: Path,
        *,
        save_config: Callable[[dict[str, Any]], Any],
    ) -> None:
        all_mappings = self.mapping_service.mappings_for_config(config)
        if not all_mappings:
            port.status = "No mappings to delete"
            return
        index = 0
        port.screen.timeout(-1)
        while True:
            port.screen.erase()
            height, width = port.screen.getmaxyx()
            if height < 16 or width < 80:
                port.add(0, 0, "Terminal is too small. Need at least 80x16.", port.warn_attr())
                port.screen.refresh()
                ch = port.read_key()
                if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                    return
                continue

            left_width = min(44, max(34, width // 3))
            right_left = left_width + 1
            right_width = width - right_left
            panel_top = 3
            panel_height = height - 6
            port.add(0, 0, "Delete mapping"[:width], curses.A_BOLD)
            port.add(1, 0, "Delete removes the mapping from the local Moulin client config only."[:width])
            port.draw_box(panel_top, 0, panel_height, left_width, "Mappings")
            port.draw_box(panel_top, right_left, panel_height, right_width, "Details")

            visible = max(1, panel_height - 2)
            scroll = ui_menu_api.list_scroll(index, len(all_mappings), visible)
            for offset, mapping in enumerate(all_mappings[scroll : scroll + visible]):
                row = panel_top + 1 + offset
                item_index = scroll + offset
                attr = port.selected_attr() if item_index == index else 0
                port.add(row, 2, f"{item_index + 1}. {mapping['name']}"[: left_width - 4].ljust(left_width - 4), attr)

            current = all_mappings[index]
            detail_x = right_left + 2
            detail_w = right_width - 4
            row = panel_top + 2
            port.add(row, detail_x, current["name"][:detail_w], curses.A_BOLD)
            row += 2
            row = port.draw_wrapped(row, detail_x, detail_w, current["role"], max_lines=3)
            row += 1
            port.add(row, detail_x, f"kind:   {current['kind']}"[:detail_w])
            row += 1
            port.add(row, detail_x, f"push:   {'yes' if current['push'] else 'no'}"[:detail_w])
            row += 2
            port.add(row, detail_x, f"remote: {current['remote']}"[:detail_w])
            row += 1
            port.add(row, detail_x, f"local:  {current['local']}"[:detail_w])

            footer = "Up/Down: select | Enter/d: delete | q/Esc: back"
            port.add(height - 2, 0, footer[:width], port.accent_attr())
            port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
            port.screen.refresh()
            ch = port.read_key()
            if ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
                index = ui_menu_api.move_index(index, len(all_mappings), -1)
            elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"):
                index = ui_menu_api.move_index(index, len(all_mappings), 1)
            elif ch in (10, 13) or ui_input_api.key_code_matches(ch, "d"):
                if not port.confirm_sync_action("Delete mapping", f"Remove mapping {current['name']} from the client config."):
                    port.screen.timeout(-1)
                    port.status = "Mapping delete cancelled"
                    continue
                name = current["name"]
                result = self.selection_service.delete_mapping_selection_action_for_config(
                    config,
                    config_accessors.mapping_selection_path_for_config(config, app_dir),
                    name,
                    save_config=save_config,
                )
                port.status = str(result["status"])
                return
            elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
                return

    def run_select_mappings_screen(
        self,
        port: Any,
        config: dict[str, Any],
        app_dir: Path,
        *,
        save_config: Callable[[dict[str, Any]], Any],
        add_mapping_screen: Callable[[], Any],
    ) -> None:
        selection_path = config_accessors.mapping_selection_path_for_config(config, app_dir)
        state = self.selection_service.mapping_selection_screen_state_for_config(config, selection_path)
        all_mappings = state["all_mappings"]
        selected = state["selected"]
        index = 0
        scroll = 0
        port.screen.timeout(-1)
        while True:
            port.screen.erase()
            height, width = port.screen.getmaxyx()
            if height < 16 or width < 80:
                port.add(0, 0, "Terminal is too small. Need at least 80x16.", port.warn_attr())
                port.screen.refresh()
                ch = port.read_key()
                if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                    port.screen.timeout(250)
                    return
                continue

            left_width = min(44, max(34, width // 3))
            right_left = left_width + 1
            right_width = width - right_left
            panel_top = 3
            panel_height = height - 6
            visible = max(1, panel_height - 2)
            scroll = ui_menu_api.list_scroll(index, len(all_mappings), visible)

            port.add(0, 0, "Activate mappings"[:width], curses.A_BOLD)
            header = (
                f"Build host: {config_accessors.remote_spec_for_config(config)}:"
                f"{config_accessors.remote_project_dir_for_config(config)}"
            )
            port.add(1, 0, header[:width])
            port.draw_box(panel_top, 0, panel_height, left_width, "Mappings")
            port.draw_box(panel_top, right_left, panel_height, right_width, "Details")

            if not all_mappings:
                port.add(panel_top + 1, 2, "No mappings configured."[: left_width - 4], port.warn_attr())
                detail_x = right_left + 2
                detail_w = right_width - 4
                row = panel_top + 2
                port.add(row, detail_x, "No mappings yet"[:detail_w], curses.A_BOLD)
                row += 2
                port.draw_wrapped(
                    row,
                    detail_x,
                    detail_w,
                    "Use Select mappings to add file or directory mappings from the remote project browser.",
                    max_lines=4,
                )
                footer = "a: select mappings | q/Esc: back"
                port.add(height - 2, 0, footer[:width], port.accent_attr())
                port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
                port.screen.refresh()
                ch = port.read_key()
                action = self.selection_service.mapping_selection_key_action(
                    mappings_exist=False,
                    add_key=ui_input_api.key_code_matches(ch, "a"),
                    close_key=ui_input_api.key_code_matches(ch, "q") or ch in (27, 10, 13),
                )
                if action["action"] == "add":
                    add_mapping_screen()
                    state = self.selection_service.mapping_selection_screen_state_for_config(config, selection_path)
                    all_mappings = state["all_mappings"]
                    selected = state["selected"]
                    index = 0
                    scroll = 0
                elif action["action"] == "close":
                    port.status = "Activate mappings closed"
                    port.screen.timeout(250)
                    return
                continue

            for offset, mapping in enumerate(all_mappings[scroll : scroll + visible]):
                row = panel_top + 1 + offset
                label = self.presentation_service.mapping_selection_row_label(mapping, selected)
                attr = port.selected_attr() if scroll + offset == index else 0
                port.add(row, 2, label[: left_width - 4].ljust(left_width - 4), attr)

            current = all_mappings[index]
            detail = self.presentation_service.mapping_selection_detail_for_config(
                config,
                app_dir,
                current,
                selected_count=len(selected),
                total_count=len(all_mappings),
            )
            detail_x = right_left + 2
            detail_w = right_width - 4
            row = panel_top + 2
            port.add(row, detail_x, detail["name"][:detail_w], curses.A_BOLD)
            row += 2
            row = port.draw_wrapped(row, detail_x, detail_w, detail["role"], max_lines=3)
            row += 1
            port.add(row, detail_x, f"kind:   {detail['kind']}"[:detail_w])
            row += 1
            port.add(row, detail_x, f"push:   {detail['push']}"[:detail_w])
            row += 2
            port.add(row, detail_x, "remote:", port.accent_attr())
            row += 1
            row = port.draw_wrapped(row, detail_x, detail_w, detail["remote"], max_lines=3)
            row += 1
            port.add(row, detail_x, "local:", port.accent_attr())
            row += 1
            row = port.draw_wrapped(row, detail_x, detail_w, detail["local"], max_lines=3)
            row += 1
            port.add(row, detail_x, f"selected: {detail['selected']}"[:detail_w])

            footer = "Up/Down: select | Space: activate/deactivate | d: delete | a: all | n: none | Enter/q/Esc: back"
            port.add(height - 2, 0, footer[:width], port.accent_attr())
            port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
            port.screen.refresh()
            ch = port.read_key()
            action = self.selection_service.mapping_selection_key_action(
                mappings_exist=bool(all_mappings),
                up=ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"),
                down=ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"),
                toggle=ch == ord(" "),
                delete=ui_input_api.key_code_matches(ch, "d"),
                all_key=ui_input_api.key_code_matches(ch, "a"),
                none_key=ui_input_api.key_code_matches(ch, "n"),
                close_key=ch in (10, 13) or ui_input_api.key_code_matches(ch, "q") or ch == 27,
            )
            if action["action"] == "move":
                index = ui_menu_api.move_index(index, len(all_mappings), int(action["delta"]))
            elif action["action"] == "toggle":
                result = self.selection_service.toggle_mapping_selection_for_config(
                    config,
                    selection_path,
                    all_mappings,
                    selected,
                    index,
                    save_config=save_config,
                )
                selected = result["selected"]
                port.status = str(result["status"])
            elif action["action"] == "delete":
                current = all_mappings[index]
                if not port.confirm_sync_action("Delete mapping", f"Remove mapping {current['name']} from the client config."):
                    port.screen.timeout(-1)
                    port.status = "Mapping delete cancelled"
                    continue
                name = current["name"]
                result = self.selection_service.delete_mapping_selection_action_for_config(
                    config,
                    selection_path,
                    name,
                    save_config=save_config,
                )
                all_mappings = result["all_mappings"]
                selected = result["selected"]
                if all_mappings:
                    index = min(index, len(all_mappings) - 1)
                    scroll = min(scroll, max(0, len(all_mappings) - visible))
                else:
                    index = 0
                    scroll = 0
                port.screen.timeout(-1)
                port.status = str(result["status"])
            elif action["action"] == "all":
                result = self.selection_service.select_all_mappings_for_config(
                    config,
                    selection_path,
                    all_mappings,
                    save_config=save_config,
                )
                selected = result["selected"]
                port.status = str(result["status"])
            elif action["action"] == "none":
                result = self.selection_service.clear_mapping_selection_for_config(
                    config,
                    selection_path,
                    save_config=save_config,
                )
                selected = result["selected"]
                port.status = str(result["status"])
            elif action["action"] == "close":
                port.status = "Activate mappings closed"
                port.screen.timeout(250)
                return

    def run_add_mapping_screen(
        self,
        port: Any,
        config: dict[str, Any],
        app_dir: Path,
        *,
        fetch_project_listing: Callable[[str], list[dict[str, str]]],
        save_config: Callable[[dict[str, Any]], Any],
    ) -> None:
        current_dir = "."
        index = 0
        scroll = 0
        entries: list[dict[str, str]] = []
        error = ""
        need_load = True
        draft: dict[str, Any] = {}
        port.screen.timeout(-1)
        while True:
            if need_load:
                try:
                    loaded = fetch_project_listing(current_dir)
                    entries = self.presentation_service.listing_with_parent_entry(current_dir, loaded)
                    error = "" if entries else "Directory is empty"
                    index = 0
                    scroll = 0
                    draft = {}
                except Exception as exc:
                    error = str(exc)
                need_load = False

            port.screen.erase()
            height, width = port.screen.getmaxyx()
            if height < 18 or width < 80:
                port.add(0, 0, "Terminal is too small. Need at least 80x18.", port.warn_attr())
                port.screen.refresh()
                ch = port.read_key()
                if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                    return
                continue

            left_width = min(64, max(40, width // 2))
            right_left = left_width + 1
            right_width = width - right_left
            panel_top = 3
            panel_height = height - 6
            visible = max(1, panel_height - 2)
            scroll = ui_menu_api.list_scroll(index, len(entries), visible)

            current_remote = f"{config_accessors.remote_spec_for_config(config)}:{config_accessors.remote_project_dir_for_config(config)}"
            display_dir = "~" if current_dir == "." else current_dir
            port.add(0, 0, "Select mappings from remote project browser"[:width], curses.A_BOLD)
            port.add(1, 0, f"Build host: {current_remote} | dir={display_dir}"[:width])
            port.draw_box(panel_top, 0, panel_height, left_width, "Project")
            port.draw_box(panel_top, right_left, panel_height, right_width, "Mapping")

            if error:
                port.add(panel_top + 1, 2, error[: left_width - 4], port.error_attr())
            path_state = self.browser_service.path_state(
                config,
                config_accessors.mapping_selection_path_for_config(config, app_dir),
            )
            mapped_paths = path_state["mapped_paths"]
            selected_paths = path_state["selected_paths"]
            port.draw_scrollbar(panel_top + 1, left_width - 2, visible, len(entries), visible, scroll)
            for offset, entry in enumerate(entries[scroll : scroll + visible]):
                row = panel_top + 1 + offset
                item_index = scroll + offset
                label = self.presentation_service.mapping_browser_entry_label(
                    entry,
                    selected_paths=selected_paths,
                    mapped_paths=mapped_paths,
                )
                attr = port.selected_attr() if item_index == index else 0
                port.add(row, 2, label[: left_width - 4].ljust(left_width - 4), attr)

            current = self.browser_service.current_entry(entries, index)
            draft = self.presentation_service.refresh_mapping_draft_for_entry(draft, current)
            detail_x = right_left + 2
            detail_w = right_width - 4
            row = panel_top + 2
            current_path = current["path"] or current_dir
            row = port.draw_wrapped(row, detail_x, detail_w, current_path, curses.A_BOLD, max_lines=3)
            row += 1
            row = port.draw_label_value_wrapped(row, detail_x, detail_w, "kind", self.presentation_service.mapping_browser_entry_kind(current), max_lines=1)
            row = port.draw_label_value_wrapped(row, detail_x, detail_w, "name", str(draft["name"]), max_lines=2)
            row = port.draw_label_value_wrapped(row, detail_x, detail_w, "local path", str(draft["local"]), max_lines=3)
            row = port.draw_label_value_wrapped(row, detail_x, detail_w, "role", str(draft["role"]), max_lines=3)
            row = port.draw_label_value_wrapped(row, detail_x, detail_w, "push", "yes" if draft["push"] else "no", max_lines=1)
            row += 1
            mapped_state = self.presentation_service.mapping_state_label(current["path"], selected_paths, mapped_paths)
            row = port.draw_label_value_wrapped(row, detail_x, detail_w, "mapped", mapped_state, max_lines=1)
            row += 1
            port.draw_wrapped(
                row,
                detail_x,
                detail_w,
                "Enter opens directories. Space toggles the selected path as a mapping. Use n/l/r/p before adding to edit name, local path, role, or push permission.",
                max_lines=4,
            )

            footer = "S selected | s has selected | * mapped | + has mapped | Enter: open | Space: toggle | q/Esc: back"
            port.add(height - 2, 0, footer[:width], port.accent_attr())
            port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
            port.screen.refresh()
            ch = port.read_key()
            action = self.browser_service.key_action(
                entries_exist=bool(entries),
                current_kind=current["kind"],
                up=ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"),
                down=ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"),
                enter=ch in (10, 13),
                toggle=ch == ord(" "),
                edit_name=ui_input_api.key_code_matches(ch, "n"),
                edit_local=ui_input_api.key_code_matches(ch, "l"),
                edit_role=ui_input_api.key_code_matches(ch, "r"),
                edit_push=ui_input_api.key_code_matches(ch, "p"),
                quit_key=ui_input_api.key_code_matches(ch, "q") or ch == 27,
            )
            if action["action"] == "move":
                index = ui_menu_api.move_index(index, len(entries), int(action["delta"]))
            elif action["action"] == "open":
                current_dir = current["path"]
                port.status = f"Loading {current_dir}..."
                need_load = True
            elif action["action"] == "status":
                port.status = str(action["status"])
            elif action["action"] == "toggle":
                result = self.browser_service.toggle_action_for_config(
                    config,
                    config_accessors.mapping_selection_path_for_config(config, app_dir),
                    current,
                    draft,
                    mapped_paths=mapped_paths,
                    save_config=save_config,
                )
                port.status = str(result["status"])
                draft = {}
            elif action["action"] == "edit_name":
                name = port.prompt("Mapping name", str(draft["name"])).strip()
                if ui_input_api.prompt_was_cancelled(port):
                    port.status = "Edit cancelled"
                    continue
                if name:
                    draft["name"] = name
            elif action["action"] == "edit_local":
                value = port.prompt("Local path", str(draft["local"]))
                if ui_input_api.prompt_was_cancelled(port):
                    port.status = "Edit cancelled"
                    continue
                draft["local"] = value
            elif action["action"] == "edit_role":
                value = port.prompt("Role", str(draft["role"]))
                if ui_input_api.prompt_was_cancelled(port):
                    port.status = "Edit cancelled"
                    continue
                draft["role"] = value
            elif action["action"] == "edit_push":
                push_raw = port.prompt("Allow push: yes or no", "yes" if draft["push"] else "no").strip().lower()
                if ui_input_api.prompt_was_cancelled(port):
                    port.status = "Edit cancelled"
                    continue
                if push_raw not in ("yes", "no", "y", "n", "true", "false", "1", "0"):
                    port.status = "Mapping add failed: push must be yes or no"
                    continue
                draft["push"] = push_raw in ("yes", "y", "true", "1")
            elif action["action"] == "quit":
                return


def project_mapping_screen_controller() -> ProjectMappingScreenController:
    return ProjectMappingScreenController()


def run_add_mapping_screen(
    port: Any,
    config: dict[str, Any],
    app_dir: Path,
    *,
    fetch_project_listing: Callable[[str], list[dict[str, str]]],
    save_config: Callable[[dict[str, Any]], Any],
) -> None:
    project_mapping_screen_controller().run_add_mapping_screen(
        port,
        config,
        app_dir,
        fetch_project_listing=fetch_project_listing,
        save_config=save_config,
    )


def run_delete_mapping_screen(
    port: Any,
    config: dict[str, Any],
    app_dir: Path,
    *,
    save_config: Callable[[dict[str, Any]], Any],
) -> None:
    project_mapping_screen_controller().run_delete_mapping_screen(
        port,
        config,
        app_dir,
        save_config=save_config,
    )


def run_select_mappings_screen(
    port: Any,
    config: dict[str, Any],
    app_dir: Path,
    *,
    save_config: Callable[[dict[str, Any]], Any],
    add_mapping_screen: Callable[[], Any],
) -> None:
    project_mapping_screen_controller().run_select_mappings_screen(
        port,
        config,
        app_dir,
        save_config=save_config,
        add_mapping_screen=add_mapping_screen,
    )
