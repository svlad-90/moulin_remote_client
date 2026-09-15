"""Build target and board artifact selection controller."""

from __future__ import annotations

import curses
from pathlib import Path
from typing import Any, Callable

from components.config.api import accessors as config_accessor_api
from components.project_config.api import fields as project_field_api
from components.config.api import profiles as config_profile_api
from components.build_runtime.api import runtime as config_runtime_api
from components.moulin.api import manifest as moulin_manifest_api
from components.ui.api import input as ui_input_api
from components.ui.api import menu as ui_menu_api
from components.ui.api import text as ui_text_api


class TargetSelectionController:
    """Own target-like selection workflows for the project configuration screen."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        target_candidates: Callable[[dict[str, str]], list[dict[str, str]]],
        app_dir: Path,
        default_config_path: Path,
        save_config: Callable[[dict[str, Any]], Any],
        target_policy_service: project_field_api.TargetSelectionPolicyService | None = None,
    ) -> None:
        self.config = config
        self.target_candidates = target_candidates
        self.app_dir = app_dir
        self.default_config_path = default_config_path
        self.save_config = save_config
        self.target_policy_service = target_policy_service or project_field_api.target_selection_policy_service()

    def select_build_targets(
        self,
        port: Any,
        *,
        reload_runtime: Callable[[], Any],
    ) -> None:
        selected_text = self.select_targets(
            port,
            title="Build Targets",
            selected_text=port.build_targets,
            default_text=port.build_targets,
            build_params=port.build_params,
            empty_message="No build targets found in Moulin manifest.",
            saved_status="Build target selection saved",
            cancelled_status="Build target selection cancelled",
        )
        if selected_text is None:
            return
        port.build_targets = selected_text
        plan = config_profile_api.apply_active_project_targets_for_config(self.config, selected_text)
        config_runtime_api.save_current_runtime_build_settings(
            self.config,
            parameters=port.build_params,
            targets=port.build_targets,
            docker_image=port.docker_image,
            app_dir=self.app_dir,
            default_path=self.default_config_path,
        )
        self.save_config(self.config)
        if plan["runtime_reload"]:
            reload_runtime()
        port.status = str(plan["status"])

    def select_board_artifacts(
        self,
        port: Any,
        *,
        reload_runtime: Callable[[], Any],
    ) -> None:
        project = config_profile_api.active_project(self.config)
        selected_text = self.select_targets(
            port,
            title="Board Artifacts",
            selected_text=str(project.get("board_artifacts", "")) or port.build_targets,
            default_text=port.build_targets,
            build_params=port.build_params,
            empty_message="No artifacts found in Moulin manifest.",
            saved_status="Board artifact selection saved",
            cancelled_status="Board artifact selection cancelled",
        )
        if selected_text is None:
            return
        plan = config_profile_api.apply_active_project_board_artifacts_for_config(self.config, selected_text)
        self.save_config(self.config)
        if plan["runtime_reload"]:
            reload_runtime()
        port.status = str(plan["status"])

    def select_targets(
        self,
        port: Any,
        *,
        title: str,
        selected_text: str,
        default_text: str,
        build_params: dict[str, str],
        empty_message: str,
        saved_status: str,
        cancelled_status: str,
    ) -> str | None:
        candidates = self.target_candidates(build_params)
        selected = self.target_policy_service.selected_targets_from_text(selected_text)
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
                    return None
                continue

            actions = self.target_policy_service.target_actions(candidates)
            index = ui_menu_api.clamp_index(index, len(actions))
            port.draw_box(0, 0, height - 2, width, title)
            port.add(1, 2, "Manifest:", port.accent_attr())
            port.add(1, 18, ui_text_api.fit_text(config_accessor_api.moulin_manifest_name_for_config(self.config), width - 20))
            port.add(2, 2, "Selected:", port.accent_attr())
            display_selected = self.target_policy_service.target_display_text(
                candidates,
                selected,
                current_text=selected_text,
                default_text=default_text,
            )
            port.add(2, 18, ui_text_api.fit_text(display_selected, width - 20))

            top = 4
            visible = max(1, height - 10)
            if not candidates:
                port.add(top, 2, empty_message, port.warn_attr())
                top += 2
            if actions:
                for offset, action in enumerate(actions[:visible]):
                    row = top + offset
                    label = self.target_policy_service.action_label(action, selected)
                    attr = port.selected_attr() if offset == index else 0
                    port.add(row, 2, label[: width - 4].ljust(width - 4), attr)

            if actions:
                port.add(height - 4, 2, ui_text_api.fit_text(self.target_policy_service.action_description(actions[index]), width - 4))
            footer = "Up/Down: select | Space: toggle | Enter: save | q/Esc: cancel"
            port.add(height - 2, 0, footer[:width], port.accent_attr())
            port.add(height - 1, 0, port.status[:width].ljust(width), curses.A_REVERSE)
            port.screen.refresh()
            ch = port.read_key()
            if (ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k")) and actions:
                index = ui_menu_api.move_index(index, len(actions), -1)
            elif (ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j")) and actions:
                index = ui_menu_api.move_index(index, len(actions), 1)
            elif ch == ord(" ") and actions:
                selected, port.status = self.target_policy_service.toggle_target_selection(actions[index], selected)
            elif ch in (10, 13):
                selected_text = self.target_policy_service.target_text_for_selection(
                    candidates,
                    selected,
                    current_text=selected_text,
                    default_text=default_text,
                )
                port.status = saved_status
                port.screen.timeout(250)
                return selected_text
            elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
                port.status = cancelled_status
                port.screen.timeout(250)
                return None


def target_selection_controller_for_config(
    config: dict[str, Any],
    *,
    app_dir: Path,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    default_moulin_manifest: str,
    default_config_path: Path,
    save_config: Callable[[dict[str, Any]], Any],
) -> TargetSelectionController:
    return TargetSelectionController(
        config,
        target_candidates=lambda build_params: moulin_manifest_api.target_candidates_for_config(
            config,
            app_dir=app_dir,
            remote_read_project_file=remote_read_project_file,
            cache=manifest_cache,
            default_moulin_manifest=default_moulin_manifest,
            build_params=build_params,
        ),
        app_dir=app_dir,
        default_config_path=default_config_path,
        save_config=save_config,
    )
