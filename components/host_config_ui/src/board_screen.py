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
            elif state.detail_scope == "board" and key == "board_commands":
                run_board_commands_screen(
                    port,
                    selected_board,
                    board_field_service=board_field_service,
                    field_action_controller=field_action_controller,
                )
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


def run_board_commands_screen(
    port: Any,
    board: dict[str, Any],
    *,
    board_field_service: Any,
    field_action_controller: Any,
) -> None:
    """Edit board command overrides without crowding the board profile screen."""
    commands = board_field_service.command_defaults_for_host(board)
    index = 0
    port.screen.timeout(-1)
    while True:
        port.screen.clear()
        height, width = port.screen.getmaxyx()
        if height < 16 or width < 70:
            port.add(0, 0, "Terminal is too small. Need at least 70x16.", port.warn_attr())
            port.screen.refresh()
            ch = port.read_key()
            if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                return
            continue

        index = ui_menu_api.clamp_index(index, len(commands))
        port.add(0, 0, "Board commands"[:width], curses.A_BOLD)
        port.add(1, 0, f"Board: {board.get('name') or '<unnamed>'}"[:width], port.accent_attr())
        port.draw_box(3, 0, height - 5, width, "Command overrides")
        visible = max(1, min(len(commands), height - 13))
        scroll = ui_menu_api.list_scroll(index, len(commands), visible)
        for offset, command in enumerate(commands[scroll : scroll + visible]):
            command_index = scroll + offset
            override = board_field_service.command_override_value(board, command["key"]).strip()
            effective = override or command["default"] or "<not configured>"
            compact_command = " ".join(effective.split())
            text = f"{command['label']:<28} {compact_command}"
            attr = port.selected_attr() if command_index == index else 0
            port.add(4 + offset, 2, ui_text_api.fit_text(text, width - 4).ljust(width - 4), attr)

        selected = commands[index]
        override = board_field_service.command_override_value(board, selected["key"]).strip()
        effective = override or selected["default"] or "<not configured>"
        detail_row = 5 + visible
        port.add(detail_row, 2, ui_text_api.fit_text(selected["description"], width - 4), port.accent_attr())
        port.add(detail_row + 2, 2, "Effective command:", curses.A_BOLD)
        port.draw_wrapped(detail_row + 3, 2, width - 4, effective, max_lines=max(1, height - detail_row - 8))
        footer = "Enter: edit override | Delete: use default | Esc/q: board profile"
        port.add(height - 2, 0, footer[:width].ljust(width), port.accent_attr())
        port.screen.refresh()

        ch = port.read_key()
        if ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
            index = (index - 1) % len(commands)
        elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"):
            index = (index + 1) % len(commands)
        elif ch in (10, 13):
            if field_action_controller is None:
                port.status = "Board command editor is unavailable"
                continue
            run_board_command_editor(
                port,
                board,
                selected,
                board_field_service=board_field_service,
                field_action_controller=field_action_controller,
            )
        elif ch in (curses.KEY_DC, curses.KEY_BACKSPACE):
            if field_action_controller is None:
                port.status = "Board command editor is unavailable"
                continue
            field_action_controller.apply_board_inline_value(port, board, selected["key"], "")
            port.status = f"Using default for {selected['label']}"
        elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
            return


def run_board_command_editor(
    port: Any,
    board: dict[str, Any],
    command: dict[str, str],
    *,
    board_field_service: Any,
    field_action_controller: Any,
) -> None:
    """Edit one command in a full-screen, multiline text field."""
    override = board_field_service.command_override_value(board, command["key"]).strip()
    value = override or command["default"]
    cursor = len(value)
    preferred_column: int | None = None
    port.screen.timeout(-1)
    port.set_cursor(True)
    try:
        while True:
            port.screen.clear()
            height, width = port.screen.getmaxyx()
            if height < 14 or width < 60:
                port.set_cursor(False)
                port.add(0, 0, "Terminal is too small. Need at least 60x14.", port.warn_attr())
                port.screen.refresh()
                ch = port.read_key()
                if ch == 27:
                    port.status = "Board command edit cancelled"
                    return
                port.set_cursor(True)
                continue

            field_width = width - 4
            field_height = height - 10
            rows = _command_editor_rows(value, field_width)
            cursor_row, cursor_column = _command_editor_cursor(rows, cursor)
            scroll = min(
                max(0, cursor_row - field_height + 1),
                max(0, len(rows) - field_height),
            )

            port.add(0, 0, "Edit board command"[:width], curses.A_BOLD)
            port.add(1, 0, f"Board: {board.get('name') or '<unnamed>'}"[:width], port.accent_attr())
            port.add(2, 0, f"Command: {command['label']}"[:width], port.accent_attr())
            port.add(3, 0, ui_text_api.fit_text(command["description"], width), port.disabled_attr())
            port.draw_box(5, 0, field_height + 2, width, "Command text")
            for offset, (text, _start, _end) in enumerate(rows[scroll : scroll + field_height]):
                port.add(6 + offset, 2, text[:field_width].ljust(field_width))
            footer = "F2/Ctrl+S: save override | Ctrl+D: use default | Enter: newline | Esc: cancel"
            port.add(height - 2, 0, footer[:width].ljust(width), port.accent_attr())
            try:
                port.screen.move(6 + cursor_row - scroll, 2 + min(cursor_column, field_width - 1))
            except curses.error:
                pass
            port.screen.refresh()

            ch = port.read_key()
            if ch == 27:
                port.status = "Board command edit cancelled"
                return
            if ch in (curses.KEY_F2, 19):
                saved_value = "" if not override and value.strip() == command["default"].strip() else value
                field_action_controller.apply_board_inline_value(port, board, command["key"], saved_value)
                port.status = f"Updated {command['label']}"
                return
            if ch == 4:
                field_action_controller.apply_board_inline_value(port, board, command["key"], "")
                port.status = f"Using default for {command['label']}"
                return
            if ch in (10, 13):
                value = value[:cursor] + "\n" + value[cursor:]
                cursor += 1
                preferred_column = None
                continue
            if ch in (curses.KEY_UP, curses.KEY_DOWN):
                direction = -1 if ch == curses.KEY_UP else 1
                if preferred_column is None:
                    preferred_column = cursor_column
                cursor = _move_command_editor_cursor(rows, cursor_row, preferred_column, direction)
                continue

            edit = ui_input_api.inline_edit_key_action(value, cursor, ch)
            if edit.action == "noop":
                edit = ui_input_api.inline_edit_key_action(value, cursor, ch, port.read_queued_text(ch))
            if edit.action == "edit":
                value = edit.value
                cursor = edit.cursor
                preferred_column = None
    finally:
        port.set_cursor(False)


def _command_editor_rows(value: str, width: int) -> list[tuple[str, int, int]]:
    """Return hard-wrapped rows with source offsets for cursor placement."""
    width = max(1, width)
    rows: list[tuple[str, int, int]] = []
    start = 0
    text = ""
    for index, char in enumerate(value):
        if char == "\n":
            rows.append((text, start, index))
            start = index + 1
            text = ""
            continue
        text += char
        if len(text) == width:
            rows.append((text, start, index + 1))
            start = index + 1
            text = ""
    if text or not rows or value.endswith("\n"):
        rows.append((text, start, len(value)))
    return rows


def _command_editor_cursor(rows: list[tuple[str, int, int]], cursor: int) -> tuple[int, int]:
    cursor = max(0, cursor)
    for index, (_text, start, end) in enumerate(rows):
        if cursor < end or cursor == end and (index + 1 == len(rows) or rows[index + 1][1] > cursor):
            return index, max(0, cursor - start)
    text, start, _end = rows[-1]
    return len(rows) - 1, min(len(text), max(0, cursor - start))


def _move_command_editor_cursor(
    rows: list[tuple[str, int, int]],
    row: int,
    column: int,
    direction: int,
) -> int:
    target_row = min(max(0, row + direction), len(rows) - 1)
    text, start, _end = rows[target_row]
    return start + min(max(0, column), len(text))


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
