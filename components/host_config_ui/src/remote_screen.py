"""Controller for the build host configuration screen."""

from __future__ import annotations

import curses
from typing import Any, Callable

from components.host_config.api import fields as config_field_api
from components.host_config.api import remote_draft_workflow as config_remote_draft_workflow_api
from components.host_config_ui.api import remote_edit_workflow as config_remote_edit_workflow_api
from components.host_config_ui.api import remote_screen_renderer as config_remote_screen_renderer_api
from components.host_config_ui.api import remote_screen_state as config_remote_screen_state_api
from components.ui.api import input as ui_input_api
from components.ui.api import text as ui_text_api


def run_add_remote_screen(
    port: Any,
    config: dict[str, Any],
    *,
    save_config: Callable[[dict[str, Any]], Any],
    reset_preflight: Callable[[], Any],
) -> None:
    workflow = config_remote_draft_workflow_api.RemoteDraftWorkflowService(
        config,
        save_config=save_config,
        reset_preflight=reset_preflight,
    )
    port.screen.timeout(-1)
    while True:
        port.screen.erase()
        height, width = port.screen.getmaxyx()
        if height < 20 or width < 90:
            port.add(0, 0, "Terminal is too small. Need at least 90x20.", port.warn_attr())
            port.screen.refresh()
            ch = port.read_key()
            if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                return
            continue

        left_width = min(42, max(34, width // 3))
        right_left = left_width + 1
        right_width = width - right_left
        panel_top = 3
        panel_height = height - 6
        port.add(0, 0, "Add remote"[:width], curses.A_BOLD)
        port.add(1, 0, "Fill fields, then run Create remote. Nothing is saved before Create."[:width])
        port.draw_box(panel_top, 0, panel_height, left_width, "Fields")
        port.draw_box(panel_top, right_left, panel_height, right_width, "Details")

        action_models = workflow.action_models()
        for offset, model in enumerate(action_models):
            if offset == workflow.index and model["enabled"]:
                attr = port.selected_attr()
            elif offset == workflow.index:
                attr = port.selected_disabled_attr()
            elif not model["enabled"]:
                attr = port.disabled_attr()
            else:
                attr = 0
            port.add(panel_top + 1 + offset, 2, f"{offset + 1}. {model['text']}"[: left_width - 4].ljust(left_width - 4), attr)

        selected_model = action_models[workflow.index]
        detail_x = right_left + 2
        detail_w = right_width - 4
        row = panel_top + 2
        port.add(row, detail_x, str(selected_model["label"])[:detail_w], curses.A_BOLD)
        row += 2
        row = port.draw_wrapped(row, detail_x, detail_w, str(selected_model["description"]), max_lines=3)
        row += 1
        if selected_model["disabled_reason"]:
            port.add(row, detail_x, f"Status: {selected_model['disabled_reason']}"[:detail_w], port.disabled_attr())
            row += 2
        else:
            row += 1
        for key in ("name", "label", "user", "host"):
            value = workflow.draft[key] or "<not set>"
            port.add(row, detail_x, f"{key}:".ljust(10), port.accent_attr())
            port.add(row, detail_x + 10, ui_text_api.fit_text(value, detail_w - 10), port.disabled_attr() if value == "<not set>" else 0)
            row += 1

        footer = "Up/Down/Tab: select | Enter: edit/run | q/Esc: cancel"
        port.add(height - 2, 0, footer[:width], port.accent_attr())
        port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
        port.screen.refresh()
        ch = port.read_key()
        if ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
            workflow.move(-1)
        elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j") or ch == ord("\t"):
            workflow.move(1)
        elif ch in (10, 13):
            if workflow.handle_enter(port):
                return
        elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
            workflow.cancel(port)
            return


def run_edit_remote_screen(
    port: Any,
    config: dict[str, Any],
    remote: dict[str, Any],
    *,
    save_config: Callable[[dict[str, Any]], Any],
    profile_action_controller: Any,
    field_action_controller: Any,
    browse_project_directory: Callable[[str], str | None],
) -> None:
    workflow = config_remote_edit_workflow_api.RemoteEditWorkflowService(
        config,
        remote,
        save_config=save_config,
        profile_action_controller=profile_action_controller,
        field_action_controller=field_action_controller,
        browse_project_directory=browse_project_directory,
    )
    port.screen.timeout(-1)
    while True:
        port.screen.clear()
        height, width = port.screen.getmaxyx()
        if height < 18 or width < 80:
            port.add(0, 0, "Terminal is too small. Need at least 80x18.", port.warn_attr())
            port.screen.refresh()
            ch = port.read_key()
            if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                port.screen.timeout(250)
                return
            continue

        name = str(remote.get("name", ""))
        active = workflow.is_active()
        port.add(0, 0, "Edit remote"[:width], curses.A_BOLD)
        port.add(1, 0, f"{name or '<unnamed>'} | {'active' if active else 'inactive'} | connection: {port.connection_state}"[:width])
        port.draw_box(3, 0, height - 6, width, "Fields")
        for offset, (label, key) in enumerate(workflow.fields):
            value = workflow.field_value(key)
            enabled = workflow.field_enabled(key, connected=port.connection_state == "connected")
            if offset == workflow.index and enabled:
                attr = port.selected_attr()
            elif offset == workflow.index:
                attr = port.selected_disabled_attr()
            elif not enabled:
                attr = port.disabled_attr()
            else:
                attr = 0
            text = f"{offset + 1}. {label}".ljust(22) + (value if value else "")
            port.add(4 + offset, 2, ui_text_api.fit_text(text, width - 4).ljust(width - 4), attr)

        _selected_label, selected_key = workflow.selected_field()
        detail_row = 4 + len(workflow.fields) + 2
        if detail_row < height - 3:
            port.add(detail_row, 2, workflow.field_hint(selected_key)[: width - 4], port.accent_attr())
        reason = workflow.field_disabled_reason(selected_key)
        if reason and detail_row + 1 < height - 3:
            port.add(detail_row + 1, 2, f"Status: {reason}"[: width - 4], port.disabled_attr())

        footer = "Enter: edit | b: browse projects dir | s: set active | q/Esc: back"
        port.add(height - 2, 0, footer[:width], port.accent_attr())
        port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
        port.screen.refresh()
        ch = port.read_key()
        if ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
            workflow.move(-1)
        elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j") or ch == ord("\t"):
            workflow.move(1)
        elif ui_input_api.key_code_matches(ch, "s"):
            workflow.set_active(port)
        elif ui_input_api.key_code_matches(ch, "b"):
            workflow.browse_projects_dir(port)
        elif ch in (10, 13):
            if workflow.handle_enter(port):
                port.screen.timeout(250)
                return
        elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
            workflow.save_and_close()
            port.screen.timeout(250)
            return


def run_remote_configurations_screen(
    port: Any,
    config: dict[str, Any],
    *,
    save_config: Callable[[dict[str, Any]], Any],
    remote_file_selection_controller: Any | None = None,
    profile_action_controller: Any | None = None,
    field_action_controller: Any | None = None,
) -> None:
    build_field_service = config_field_api.build_host_field_service()
    screen_state = config_remote_screen_state_api.RemoteScreenStateController(config)
    renderer = config_remote_screen_renderer_api.RemoteScreenRenderer(
        config,
        remote_fields_factory=config_field_api.remote_fields,
        build_field_service=build_field_service,
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
        remotes = render_result.remotes
        fields = render_result.fields
        selected_remote = render_result.selected_remote
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
                selected_remote,
                (
                    lambda target_port, remote_profile, key, value: port.apply_remote_inline_value(remote_profile, key, value)
                    if field_action_controller is None
                    else field_action_controller.apply_remote_inline_value(target_port, remote_profile, key, value)
                ),
            )
            continue
        port.set_cursor(False)
        action = config_field_api.configuration_screen_key_action(
            focus=state.focus,
            list_focus="remotes",
            selected_exists=selected_remote is not None,
            fields_exist=bool(fields),
            selected_field_key=screen_state.selected_field_key(fields),
            left=ch == curses.KEY_LEFT or ui_input_api.key_code_matches(ch, "h"),
            right=ch == curses.KEY_RIGHT or ui_input_api.key_code_matches(ch, "l"),
            up=ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"),
            down=ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j") or ch == ord("\t"),
            enter=ch in (10, 13),
            add=ui_input_api.key_code_matches(ch, "a"),
            delete=ui_input_api.key_code_matches(ch, "d"),
            set_active=ui_input_api.key_code_matches(ch, "s"),
            escape=ch == 27,
            quit=ui_input_api.key_code_matches(ch, "q"),
        )
        if action["action"] in {"focus-list", "focus-fields", "move-field", "move-list", "status"}:
            screen_state.apply_navigation_action(port, action, field_count=len(fields), remote_count=len(remotes))
        elif action["action"] == "enter-field":
            label, key = fields[state.field_index]
            if not build_field_service.field_enabled_for_config(
                key,
                selected_remote,
                config,
                connected=port.connection_state == "connected",
            ):
                port.status = build_field_service.field_disabled_reason_for_config(key, selected_remote, config)
            elif key == "moulin_manifest":
                if remote_file_selection_controller is None:
                    fallback = getattr(port, "select_remote_moulin_manifest", None)
                    if fallback is not None:
                        fallback()
                else:
                    remote_file_selection_controller.select_moulin_manifest(port)
            elif key == "dockerfile":
                if remote_file_selection_controller is None:
                    fallback = getattr(port, "select_remote_dockerfile", None)
                    if fallback is not None:
                        fallback()
                else:
                    remote_file_selection_controller.select_dockerfile(port)
            else:
                screen_state.begin_inline_edit(key, str(selected_remote.get(key, "")))
                port.status = f"Editing {label}"
        elif action["action"] == "add":
            if profile_action_controller is None:
                port.add_empty_remote()
            else:
                profile_action_controller.add_remote(port)
            screen_state.apply_add_state()
        elif action["action"] == "delete":
            if profile_action_controller is None:
                port.delete_remote(selected_remote)
            else:
                profile_action_controller.delete_remote(port, selected_remote)
            screen_state.apply_delete_state()
        elif action["action"] == "set-active":
            if profile_action_controller is None:
                port.set_active_remote(selected_remote)
            else:
                profile_action_controller.set_active_remote(port, selected_remote)
        elif action["action"] == "quit":
            save_config(config)
            port.screen.timeout(250)
            return
