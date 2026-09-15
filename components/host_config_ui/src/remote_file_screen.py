"""Controllers for selecting project files from the remote build host."""

from __future__ import annotations

import curses
from pathlib import Path
from typing import Any, Callable

from components.config.api import accessors as config_accessor_api
from components.project_config.api import project_fields as project_fields_api
from components.moulin.api import manifest as moulin_manifest_api
from components.remote.api import discovery as remote_discovery_api
from components.ui.api import input as ui_input_api
from components.ui.api import menu as ui_menu_api
from components.ui.api import text as ui_text_api


class RemoteFileSelectionController:
    """Own remote project file selection workflows."""

    def __init__(
        self,
        config: dict[str, Any],
        app_dir: Path,
        *,
        fetch_git_tracked_files: Callable[[], list[str]],
        read_project_file: Callable[[dict[str, Any], str], str],
        manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
        default_moulin_manifest: str,
        save_config: Callable[[dict[str, Any]], Any],
        reset_preflight: Callable[[], Any],
    ) -> None:
        self.config = config
        self.app_dir = app_dir
        self.fetch_git_tracked_files = fetch_git_tracked_files
        self.read_project_file = read_project_file
        self.manifest_cache = manifest_cache
        self.default_moulin_manifest = default_moulin_manifest
        self.save_config = save_config
        self.reset_preflight = reset_preflight

    def select_moulin_manifest(self, port: Any) -> None:
        run_select_remote_moulin_manifest(
            port,
            self.config,
            self.app_dir,
            fetch_git_tracked_files=self.fetch_git_tracked_files,
            read_project_file=self.read_project_file,
            manifest_cache=self.manifest_cache,
            default_moulin_manifest=self.default_moulin_manifest,
            save_config=self.save_config,
            reset_preflight=self.reset_preflight,
        )

    def select_dockerfile(self, port: Any) -> None:
        run_select_remote_dockerfile(
            port,
            self.config,
            fetch_git_tracked_files=self.fetch_git_tracked_files,
            read_project_file=self.read_project_file,
            save_config=self.save_config,
            reset_preflight=self.reset_preflight,
        )


def draw_loading_message(port: Any, title: str, message: str) -> None:
    port.screen.erase()
    height, width = port.screen.getmaxyx()
    port.add(0, 0, title[:width], curses.A_BOLD)
    port.add(2, 0, message[:width], port.accent_attr())
    port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
    port.screen.refresh()


def validate_remote_project_file_candidate(
    config: dict[str, Any],
    path: str,
    validate_text: Callable[[str], tuple[bool, str]],
    *,
    read_project_file: Callable[[dict[str, Any], str], str],
) -> tuple[bool, str]:
    try:
        text = read_project_file(config, path)
    except Exception as exc:
        return False, str(exc)
    return validate_text(text)


def run_select_remote_candidate_screen(
    port: Any,
    config: dict[str, Any],
    title: str,
    candidates: list[dict[str, Any]],
    validator: Callable[[str], tuple[bool, str]],
) -> str | None:
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
                return None
            continue
        port.add(0, 0, title[:width], curses.A_BOLD)
        port.add(1, 0, f"Build host: {config_accessor_api.remote_spec_for_config(config)}:{config_accessor_api.remote_project_dir_for_config(config)}"[:width])
        port.draw_box(3, 0, height - 6, width, "Candidates")
        visible = max(1, height - 8)
        if not candidates:
            port.add(4, 2, "No candidates found."[: width - 4], port.warn_attr())
        else:
            index = ui_menu_api.clamp_index(index, len(candidates))
            scroll = ui_menu_api.list_scroll(index, len(candidates), visible)
            for offset, candidate in enumerate(candidates[scroll : scroll + visible]):
                item_index = scroll + offset
                valid = candidate.get("valid")
                marker = "?" if valid is None else ("ok" if valid else "bad")
                path = str(candidate.get("path", ""))
                detail = str(candidate.get("detail", ""))
                label = f"{marker:3} {path}  {detail}".strip()
                if item_index == index and valid is not False:
                    attr = port.selected_attr()
                elif item_index == index:
                    attr = port.selected_disabled_attr()
                elif valid is not False:
                    attr = 0
                else:
                    attr = port.disabled_attr()
                port.add(4 + offset, 2, ui_text_api.fit_text(label, width - 4).ljust(width - 4), attr)
        footer = "Up/Down: select | Enter: validate/select | q/Esc: back"
        port.add(height - 2, 0, footer[:width], port.accent_attr())
        port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
        port.screen.refresh()
        ch = port.read_key()
        if (ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k")) and candidates:
            index = ui_menu_api.move_index(index, len(candidates), -1)
        elif (ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j") or ch == ord("\t")) and candidates:
            index = ui_menu_api.move_index(index, len(candidates), 1)
        elif ch in (10, 13) and candidates:
            candidate = candidates[index]
            if candidate.get("valid") is None:
                path = str(candidate.get("path", ""))
                draw_loading_message(port, title, f"Validating {path}...")
                valid, detail = validator(path)
                candidate["valid"] = valid
                candidate["detail"] = detail
                port.status = detail
            if candidate.get("valid") is True:
                return str(candidate.get("path", ""))
            port.status = str(candidate.get("detail", "invalid candidate"))
        elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
            return None


def run_select_remote_moulin_manifest(
    port: Any,
    config: dict[str, Any],
    app_dir: Path,
    *,
    fetch_git_tracked_files: Callable[[], list[str]],
    read_project_file: Callable[[dict[str, Any], str], str],
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    default_moulin_manifest: str,
    save_config: Callable[[dict[str, Any]], Any],
    reset_preflight: Callable[[], Any],
) -> None:
    if not port.remote_project_config_ready():
        return
    try:
        draw_loading_message(port, "Select Moulin manifest", "Searching tracked root YAML files...")
        paths = remote_discovery_api.remote_project_discovery_service().root_yaml_candidates(fetch_git_tracked_files())
    except Exception as exc:
        port.status = f"Manifest search failed: {exc}"
        return
    candidates = [{"path": path, "valid": None, "detail": "press Enter to validate"} for path in paths[:200]]
    selected = run_select_remote_candidate_screen(
        port,
        config,
        "Select Moulin manifest",
        candidates,
        lambda path: validate_remote_project_file_candidate(
            config,
            path,
            moulin_manifest_api.validate_manifest_text,
            read_project_file=read_project_file,
        ),
    )
    if not selected:
        port.status = "Moulin manifest unchanged"
        return
    plan = project_fields_api.project_field_service().apply_active_file_selection_for_config(
        config,
        "moulin_manifest",
        selected,
    )
    if plan["manifest_cache_reset"]:
        manifest_cache.clear()
    if plan["build_params_reload"]:
        port.build_params = moulin_manifest_api.default_parameters_for_config(
            config,
            app_dir=app_dir,
            remote_read_project_file=read_project_file,
            cache=manifest_cache,
            default_moulin_manifest=default_moulin_manifest,
        )
    if plan["preflight_reset"]:
        reset_preflight()
    save_config(config)
    port.status = str(plan["status"])


def remote_file_selection_controller(
    config: dict[str, Any],
    app_dir: Path,
    *,
    fetch_git_tracked_files: Callable[[], list[str]],
    read_project_file: Callable[[dict[str, Any], str], str],
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    default_moulin_manifest: str,
    save_config: Callable[[dict[str, Any]], Any],
    reset_preflight: Callable[[], Any],
) -> RemoteFileSelectionController:
    return RemoteFileSelectionController(
        config,
        app_dir,
        fetch_git_tracked_files=fetch_git_tracked_files,
        read_project_file=read_project_file,
        manifest_cache=manifest_cache,
        default_moulin_manifest=default_moulin_manifest,
        save_config=save_config,
        reset_preflight=reset_preflight,
    )


def run_select_remote_dockerfile(
    port: Any,
    config: dict[str, Any],
    *,
    fetch_git_tracked_files: Callable[[], list[str]],
    read_project_file: Callable[[dict[str, Any], str], str],
    save_config: Callable[[dict[str, Any]], Any],
    reset_preflight: Callable[[], Any],
) -> None:
    if not port.remote_project_config_ready():
        return
    try:
        draw_loading_message(port, "Select Dockerfile", "Searching tracked Dockerfiles...")
        paths = remote_discovery_api.remote_project_discovery_service().dockerfile_candidates(fetch_git_tracked_files())
    except Exception as exc:
        port.status = f"Dockerfile search failed: {exc}"
        return
    candidates = [{"path": path, "valid": None, "detail": "press Enter to validate"} for path in paths[:200]]
    selected = run_select_remote_candidate_screen(
        port,
        config,
        "Select Dockerfile",
        candidates,
        lambda path: validate_remote_project_file_candidate(
            config,
            path,
            remote_discovery_api.remote_project_discovery_service().validate_dockerfile_text,
            read_project_file=read_project_file,
        ),
    )
    if not selected:
        port.status = "Dockerfile unchanged"
        return
    plan = project_fields_api.project_field_service().apply_active_file_selection_for_config(
        config,
        "dockerfile",
        selected,
    )
    if plan["preflight_reset"]:
        reset_preflight()
    save_config(config)
    port.status = str(plan["status"])
