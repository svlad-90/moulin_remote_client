"""Controller for the sync mapped files screen."""

from __future__ import annotations

import curses
from pathlib import Path
from typing import Any, Callable

from components.config.api import accessors as config_accessors
from components.project.api import core as project_core_api
from components.project.api import selection as project_selection_api
from components.sync.api import screen_workflow as sync_screen_workflow_api
from components.ui.api import input as ui_input_api
from components.ui.api import menu as ui_menu_api


def run_sync_screen(
    port: Any,
    config: dict[str, Any],
    app_dir: Path,
    *,
    connected: Callable[[], bool],
    action_controller: Any,
    screen_workflow: sync_screen_workflow_api.SyncScreenWorkflowService | None = None,
) -> None:
    workflow = screen_workflow or sync_screen_workflow_api.sync_screen_workflow_service()
    mapping_service = project_core_api.project_mapping_core_service()
    selection_service = project_selection_api.project_mapping_selection_service()
    actions = workflow.actions()
    index = 0
    port.screen.timeout(-1)
    while True:
        port.screen.erase()
        height, width = port.screen.getmaxyx()
        if height < 18 or width < 80:
            port.add(0, 0, "Terminal is too small. Need at least 80x18.", port.warn_attr())
            port.screen.refresh()
            ch = port.read_key()
            if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                port.screen.timeout(250)
                return
            continue

        left_width = min(38, max(30, width // 3))
        right_left = left_width + 1
        right_width = width - right_left
        panel_top = 3
        panel_height = height - 6
        selected_names = selection_service.read_mapping_selection_for_config(
            config,
            config_accessors.mapping_selection_path_for_config(config, app_dir),
            required=False,
        )

        port.add(0, 0, "Sync mapped files"[:width], curses.A_BOLD)
        port.add(1, 0, f"Selected mappings: {', '.join(selected_names) or 'none'}"[:width])
        port.draw_box(panel_top, 0, panel_height, left_width, "Actions")
        port.draw_box(panel_top, right_left, panel_height, right_width, "Details")

        is_connected = connected()
        for offset, action in enumerate(actions):
            row = panel_top + 1 + offset
            enabled = workflow.action_enabled(action, connected=is_connected)
            label = f"{offset + 1}. {action['label']}"
            attr = port.selected_attr() if offset == index else 0
            if not enabled:
                attr = port.disabled_attr()
            port.add(row, 2, label[: left_width - 4].ljust(left_width - 4), attr)

        action = actions[index]
        detail_x = right_left + 2
        detail_w = right_width - 4
        row = panel_top + 2
        port.add(row, detail_x, str(action["label"])[:detail_w], curses.A_BOLD)
        row += 2
        row = port.draw_wrapped(row, detail_x, detail_w, str(action["description"]), max_lines=4)
        row += 1
        disabled_status = workflow.disabled_status(action, connected=is_connected)
        if disabled_status:
            port.add(row, detail_x, f"Status: {disabled_status}"[:detail_w], port.disabled_attr())
            row += 1
        port.add(row, detail_x, "Configured mappings:"[:detail_w], port.accent_attr())
        row += 1
        detail_rows = workflow.mapping_detail_rows(
            mapping_service.mappings_for_config(config),
            selected_names,
            limit=panel_top + panel_height - row - 2,
        )
        for detail_row in detail_rows:
            port.add(row, detail_x, detail_row[:detail_w])
            row += 1

        footer = "Up/Down: select | Enter: run | q/Esc: back"
        port.add(height - 2, 0, footer[:width], port.accent_attr())
        port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
        port.screen.refresh()
        ch = port.read_key()
        if ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
            index = ui_menu_api.move_index(index, len(actions), -1)
        elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"):
            index = ui_menu_api.move_index(index, len(actions), 1)
        elif ch in (10, 13):
            action = actions[index]
            if action["kind"] == "back":
                port.screen.timeout(250)
                return
            is_connected = connected()
            if not workflow.action_enabled(action, connected=is_connected):
                port.status = "Connect to the build host first"
                continue
            if action["confirm"] and not port.confirm_sync_action(str(action["label"]), str(action["description"])):
                port.screen.timeout(-1)
                port.status = f"Cancelled: {action['label']}"
                continue
            port.screen.timeout(-1)
            try:
                result = workflow.action_result_for_config(config, action, app_dir=app_dir)
                action_controller.run_action_result(port, result)
            except SystemExit as exc:
                port.status = f"{action['label']}: failed"
                port.show_message("Action failed", [str(exc)])
                continue
            if action["label"] in {"Select mappings", "Activate mappings"}:
                port.screen.timeout(-1)
                continue
            port.screen.timeout(250)
            return
        elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
            port.screen.timeout(250)
            return
