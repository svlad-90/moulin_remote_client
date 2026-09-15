"""Controller for the project configuration screen."""

from __future__ import annotations

import curses
from pathlib import Path
from typing import Any, Callable

from components.host_config.api import fields as host_field_api
from components.project_config.api import fields as project_field_api
from components.project_config.api import project_field_action_service as config_project_field_action_api
from components.project_config.api import project_profile_screen_service as config_project_profile_screen_api
from components.project_config_ui.api import project_screen_renderer as config_project_screen_renderer_api
from components.project_config_ui.api import project_screen_state as config_project_screen_state_api
from components.build_runtime.api import runtime as config_runtime_api
from components.moulin.api import manifest as moulin_manifest_api
from components.ui.api import input as ui_input_api


def project_fields(params: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = [
        {"label": "Profile name", "key": "name", "kind": "text"},
        {"label": "Display label", "key": "label", "kind": "text"},
        {"label": "Project dir", "key": "project_dir", "kind": "text"},
        {"label": "Local overlay dir", "key": "local_project_dir", "kind": "text"},
        {"label": "Project Git URL", "key": "git_url", "kind": "text"},
        {"label": "Git branch/ref", "key": "git_ref", "kind": "git_ref"},
    ]
    fields.extend(
        {"label": str(param["name"]), "key": f"param:{param['name']}", "kind": "param", "param": param}
        for param in params
    )
    fields.extend(
        [
            {"label": "Moulin manifest", "key": "moulin_manifest", "kind": "manifest"},
            {"label": "Dockerfile", "key": "dockerfile", "kind": "dockerfile"},
            {"label": "Build targets", "key": "targets", "kind": "targets"},
            {"label": "Board artifacts", "key": "board_artifacts", "kind": "board_artifacts"},
            {"label": "Docker image name", "key": "docker_image", "kind": "text"},
        ]
    )
    return fields


def run_project_configurations_screen(
    port: Any,
    config: dict[str, Any],
    app_dir: Path,
    *,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    default_moulin_manifest: str,
    default_config_path: Path,
    save_config: Callable[[dict[str, Any]], Any],
    target_selection_controller_factory: Callable[[], Any] | None = None,
    project_settings_controller: Any | None = None,
    remote_file_selection_controller: Any | None = None,
    project_remote_dir_editor: Any | None = None,
    project_git_ref_selector: Any | None = None,
    profile_action_controller: Any | None = None,
    field_action_controller: Any | None = None,
    reload_runtime: Callable[[], Any] | None = None,
) -> None:
    project_field_service = project_field_api.project_field_service()
    field_action_service = config_project_field_action_api.ProjectFieldActionService(
        config,
        app_dir=app_dir,
        default_config_path=default_config_path,
        target_selection_controller_factory=target_selection_controller_factory,
        project_settings_controller=project_settings_controller,
        remote_file_selection_controller=remote_file_selection_controller,
        project_remote_dir_editor=project_remote_dir_editor,
        project_git_ref_selector=project_git_ref_selector,
        field_action_controller=field_action_controller,
        reload_runtime=reload_runtime,
        save_runtime_settings=config_runtime_api.save_current_runtime_build_settings,
    )
    profile_screen_service = config_project_profile_screen_api.ProjectProfileScreenService(
        config,
        profile_action_controller=profile_action_controller,
    )
    screen_state = config_project_screen_state_api.ProjectScreenStateController(config)
    renderer = config_project_screen_renderer_api.ProjectScreenRenderer(
        config,
        app_dir=app_dir,
        project_fields_factory=project_fields,
        project_field_service=project_field_service,
    )
    editing_cursor_yx: tuple[int, int] | None = None
    port.screen.timeout(-1)
    while True:
        state = screen_state.state
        editing_cursor_yx = None
        params = []
        if getattr(port, "connection_state", "disconnected") == "connected":
            params = moulin_manifest_api.parameters_for_config(
                config,
                app_dir=app_dir,
                remote_read_project_file=remote_read_project_file,
                cache=manifest_cache,
                default_moulin_manifest=default_moulin_manifest,
            )
        port.screen.clear()
        height, width = port.screen.getmaxyx()
        if height < 22 or width < 90:
            port.add(0, 0, "Terminal is too small. Need at least 90x22.", port.warn_attr())
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
            params=params,
            screen_state=screen_state,
        )
        projects = render_result.projects
        fields = render_result.fields
        selected_project = render_result.selected_project
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
                selected_project,
                field_action_service.apply_project_value,
            )
            continue
        port.set_cursor(False)
        action = host_field_api.configuration_screen_key_action(
            focus=state.focus,
            list_focus="projects",
            selected_exists=selected_project is not None,
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
            screen_state.apply_navigation_action(
                port,
                action,
                field_count=len(fields),
                project_count=len(projects),
            )
        elif action["action"] == "enter-field":
            field = fields[state.field_index]
            field_result = field_action_service.handle_enter_field(port, field, selected_project)
            if field_result["action"] == "edit-text":
                screen_state.begin_inline_edit(str(field_result["key"]), str(field_result["value"]))
        elif action["action"] == "add":
            projects = screen_state.apply_profile_state(profile_screen_service.add_project(port))
        elif action["action"] == "delete":
            projects = screen_state.apply_profile_state(
                profile_screen_service.delete_project(port, selected_project, state.project_index)
            )
        elif action["action"] == "set-active":
            profile_screen_service.set_active_project(port, selected_project)
        elif action["action"] == "quit":
            save_config(config)
            port.screen.timeout(250)
            return
