"""Controller for the board host configuration screen."""

from __future__ import annotations

import curses
from typing import Any

from components.host_config_ui.api import board_screen_renderer as config_board_screen_renderer_api
from components.host_config_ui.api import board_screen_state as config_board_screen_state_api
from components.host_config.api import fields as config_field_api
from components.ui.api import input as ui_input_api
from components.ui.api import menu as ui_menu_api
from components.ui.api import text as ui_text_api


def run_board_host_configurations_screen(
    port: Any,
    config: dict[str, Any],
    *,
    profile_action_controller: Any | None = None,
    field_action_controller: Any | None = None,
) -> None:
    board_field_service = config_field_api.board_host_field_service()
    screen_state = config_board_screen_state_api.BoardScreenStateController(config)
    renderer = config_board_screen_renderer_api.BoardScreenRenderer(
        config,
        board_host_fields_factory=config_field_api.board_host_fields,
        board_field_service=board_field_service,
    )
    editing_cursor_yx: tuple[int, int] | None = None
    port.screen.timeout(-1)
    while True:
        state = screen_state.state
        editing_cursor_yx = None
        port.screen.clear()
        height, width = port.screen.getmaxyx()
        if height < 20 or width < 90:
            port.add(0, 0, "Terminal is too small. Need at least 90x20.", port.warn_attr())
            port.screen.refresh()
            ch = port.read_key()
            if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                port.screen.timeout(250)
                return
            continue

        render_result = renderer.render(
            port,
            height=height,
            width=width,
            screen_state=screen_state,
        )
        hosts = render_result.hosts
        boards = render_result.boards
        fields = render_result.fields
        selected_host = render_result.selected_host
        selected_board = render_result.selected_board
        selected_target = render_result.selected_target
        editing_cursor_yx = render_result.editing_cursor_yx
        if editing_cursor_yx is not None:
            port.set_cursor(True)
            try:
                port.screen.move(*editing_cursor_yx)
            except curses.error:
                pass
        else:
            port.set_cursor(False)
        port.screen.timeout(-1)
        port.screen.refresh()
        ch = port.read_key()
        if ch == -1:
            continue
        if state.editing_key:
            def apply_value(target_port: Any, target: dict[str, Any], key: str, value: str) -> None:
                if state.detail_scope == "host":
                    field_action_controller.apply_board_host_inline_value(target_port, target, key, value)
                    return
                field_action_controller.apply_board_inline_value(target_port, target, key, value)

            screen_state.handle_inline_edit_key(
                port,
                ch,
                selected_target,
                apply_value,
            )
            continue
        port.set_cursor(False)
        if ch == curses.KEY_LEFT or ui_input_api.key_code_matches(ch, "h"):
            if state.focus == "fields":
                state.focus = "hosts" if state.detail_scope == "host" else "boards"
            elif state.focus == "boards":
                state.focus = "hosts"
                state.detail_scope = "host"
        elif ch == curses.KEY_RIGHT or ui_input_api.key_code_matches(ch, "l") or ch == ord("\t"):
            if state.focus == "hosts" and selected_host is not None:
                if boards:
                    state.focus = "boards"
                    state.detail_scope = "board"
                else:
                    state.focus = "fields"
                    state.detail_scope = "host"
                state.field_index = 0
            elif state.focus == "boards" and selected_board is not None:
                state.focus = "fields"
        elif ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
            if state.focus == "hosts" and hosts:
                state.host_index = (state.host_index - 1) % len(hosts)
                state.board_index = 0
            elif state.focus == "boards" and boards:
                state.board_index = (state.board_index - 1) % len(boards)
            elif fields:
                state.field_index = (state.field_index - 1) % len(fields)
        elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"):
            if state.focus == "hosts" and hosts:
                state.host_index = (state.host_index + 1) % len(hosts)
                state.board_index = 0
            elif state.focus == "boards" and boards:
                state.board_index = (state.board_index + 1) % len(boards)
            elif fields:
                state.field_index = (state.field_index + 1) % len(fields)
        elif ch in (10, 13) and state.focus == "hosts":
            if boards:
                state.focus = "boards"
                state.detail_scope = "board"
            else:
                state.focus = "fields"
                state.detail_scope = "host"
            state.field_index = 0
        elif ch in (10, 13) and state.focus == "boards":
            state.detail_scope = "board"
            state.focus = "fields"
            state.field_index = 0
        elif ch in (10, 13) and state.focus == "fields" and selected_target is not None:
            label, key = fields[state.field_index]
            if not board_field_service.field_enabled(key, selected_target):
                port.status = board_field_service.field_disabled_reason(key, selected_target)
            elif state.detail_scope == "host" and key == "direct_copy":
                field_action_controller.toggle_board_host_direct_copy(port, selected_host)
            elif state.detail_scope == "board" and key == "type":
                value = select_board_type(port, board_field_service, str(selected_board.get("type", "")))
                if value is not None:
                    field_action_controller.apply_board_inline_value(port, selected_board, key, value)
            else:
                if key.startswith("command_"):
                    value = board_field_service.command_override_value(selected_target, key)
                else:
                    value = str(selected_target.get(key, ""))
                screen_state.begin_inline_edit(key, value)
                port.status = f"Editing {label}"
        elif ui_input_api.key_code_matches(ch, "e") and state.focus in {"hosts", "boards"}:
            if state.focus == "hosts":
                state.detail_scope = "host"
            elif selected_board is not None:
                state.detail_scope = "board"
            else:
                continue
            state.focus = "fields"
            state.field_index = 0
        elif ui_input_api.key_code_matches(ch, "a"):
            if state.focus == "hosts":
                profile_action_controller.add_board_host(port)
            elif selected_host is not None:
                board = profile_action_controller.add_board(port, selected_host)
                if board is not None:
                    state.board_index = len(screen_state.boards(selected_host)) - 1
        elif ui_input_api.key_code_matches(ch, "d"):
            if state.focus == "hosts" and selected_host is not None:
                profile_action_controller.delete_board_host(port, selected_host)
            elif state.focus == "boards" and selected_board is not None:
                if profile_action_controller.delete_board(
                    port, selected_host, selected_board
                ):
                    state.board_index = max(0, state.board_index - 1)
        elif ui_input_api.key_code_matches(ch, "s") and selected_board is not None:
            profile_action_controller.set_active_board(port, selected_board)
        elif ch == 27 and state.focus == "fields":
            state.focus = "hosts" if state.detail_scope == "host" else "boards"
        elif ch == 27 and state.focus == "boards":
            state.focus = "hosts"
            state.detail_scope = "host"
        elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
            port.screen.timeout(250)
            return


def select_board_type(
    port: Any,
    board_field_service: config_field_api.BoardHostFieldService,
    current: str,
) -> str | None:
    options = board_field_service.available_board_type_options()
    if not options:
        port.status = "No board types available"
        return None
    values = [option["type"] for option in options]
    index = values.index(current) if current in values else 0
    port.screen.timeout(-1)
    while True:
        port.screen.clear()
        height, width = port.screen.getmaxyx()
        if height < 10 or width < 60:
            port.add(0, 0, "Terminal is too small. Need at least 60x10.", port.warn_attr())
            port.screen.refresh()
            ch = port.read_key()
            if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                port.status = "Board type selection cancelled"
                return None
            continue
        index = ui_menu_api.clamp_index(index, len(options))
        visible = max(1, height - 7)
        scroll = ui_menu_api.list_scroll(index, len(options), visible)
        port.draw_box(0, 0, height - 2, width, "Board type")
        port.add(1, 2, "Select board behavior type:", port.accent_attr())
        for offset, option in enumerate(options[scroll : scroll + visible]):
            item_index = scroll + offset
            selected = item_index == index
            mark = "*" if option["type"] == current else " "
            label = f"{mark} {option['type']}: {option['label']}"
            attr = port.selected_attr() if selected else 0
            port.add(3 + offset, 2, ui_text_api.fit_text(label, width - 4).ljust(width - 4), attr)
        description = str(options[index].get("description", ""))
        if description:
            port.add(height - 4, 2, ui_text_api.fit_text(description, width - 4))
        footer = "Up/Down: select | Enter: choose | q/Esc: cancel"
        port.add(height - 2, 0, footer[:width], port.accent_attr())
        port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
        port.screen.refresh()
        ch = port.read_key()
        if (ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k")) and options:
            index = ui_menu_api.move_index(index, len(options), -1)
        elif (ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j")) and options:
            index = ui_menu_api.move_index(index, len(options), 1)
        elif ch in (10, 13):
            value = options[index]["type"]
            port.status = f"Board type: {value}"
            return value
        elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
            port.status = "Board type selection cancelled"
            return None
