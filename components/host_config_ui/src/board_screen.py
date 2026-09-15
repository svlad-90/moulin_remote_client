"""Controller for the board host configuration screen."""

from __future__ import annotations

import curses
from typing import Any, Callable

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
    save_config: Callable[[dict[str, Any]], Any],
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
        fields = render_result.fields
        selected_host = render_result.selected_host
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
            screen_state.handle_inline_edit_key(
                port,
                ch,
                selected_host,
                (
                    lambda target_port, board_host, key, value: port.apply_board_host_inline_value(board_host, key, value)
                    if field_action_controller is None
                    else field_action_controller.apply_board_host_inline_value(target_port, board_host, key, value)
                ),
            )
            continue
        port.set_cursor(False)
        action = config_field_api.configuration_screen_key_action(
            focus=state.focus,
            list_focus="hosts",
            selected_exists=selected_host is not None,
            fields_exist=bool(fields),
            selected_field_key=screen_state.selected_field_key(fields),
            left=ch == curses.KEY_LEFT or ui_input_api.key_code_matches(ch, "h"),
            right=ch == curses.KEY_RIGHT or ui_input_api.key_code_matches(ch, "l"),
            up=ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"),
            down=ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j") or ch == ord("\t"),
            enter=ch in (10, 13),
            space=ch == ord(" "),
            add=ui_input_api.key_code_matches(ch, "a"),
            delete=ui_input_api.key_code_matches(ch, "d"),
            set_active=ui_input_api.key_code_matches(ch, "s"),
            escape=ch == 27,
            quit=ui_input_api.key_code_matches(ch, "q"),
        )
        if action["action"] in {"focus-list", "focus-fields", "move-field", "move-list", "status"}:
            screen_state.apply_navigation_action(port, action, field_count=len(fields), host_count=len(hosts))
        elif action["action"] == "enter-field":
            label, key = fields[state.field_index]
            if not board_field_service.field_enabled(key, selected_host):
                port.status = board_field_service.field_disabled_reason(key, selected_host)
            elif key == "direct_copy":
                if field_action_controller is None:
                    port.toggle_board_host_direct_copy(selected_host)
                else:
                    field_action_controller.toggle_board_host_direct_copy(port, selected_host)
            elif key == "type":
                value = select_board_type(port, board_field_service, str(selected_host.get("type", "")))
                if value is not None:
                    if field_action_controller is None:
                        port.apply_board_host_inline_value(selected_host, key, value)
                    else:
                        field_action_controller.apply_board_host_inline_value(port, selected_host, key, value)
            else:
                screen_state.begin_inline_edit(key, str(selected_host.get(key, "")))
                port.status = f"Editing {label}"
        elif action["action"] == "toggle-field-choice":
            selected_key = screen_state.selected_field_key(fields)
            if selected_key == "direct_copy":
                if field_action_controller is None:
                    port.toggle_board_host_direct_copy(selected_host)
                else:
                    field_action_controller.toggle_board_host_direct_copy(port, selected_host)
            elif selected_key == "type":
                value = select_board_type(port, board_field_service, str(selected_host.get("type", "")))
                if value is not None:
                    if field_action_controller is None:
                        port.apply_board_host_inline_value(selected_host, selected_key, value)
                    else:
                        field_action_controller.apply_board_host_inline_value(port, selected_host, selected_key, value)
        elif action["action"] == "add":
            if profile_action_controller is None:
                port.add_empty_board_host()
            else:
                profile_action_controller.add_board_host(port)
            screen_state.apply_add_state()
        elif action["action"] == "delete":
            if profile_action_controller is None:
                port.delete_board_host(selected_host)
            else:
                profile_action_controller.delete_board_host(port, selected_host)
            screen_state.apply_delete_state()
        elif action["action"] == "set-active":
            if profile_action_controller is None:
                port.set_active_board_host(selected_host)
            else:
                profile_action_controller.set_active_board_host(port, selected_host)
        elif action["action"] == "quit":
            save_config(config)
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
