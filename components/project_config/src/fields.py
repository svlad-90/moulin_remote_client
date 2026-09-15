"""Project configuration field UI policy helpers."""

from __future__ import annotations

from typing import Any

from components.project_config.api import project_fields
from components.project_config.api import settings_policy
from components.project_config.api import target_policy


def project_profile_row_model(
    project: dict[str, Any],
    *,
    active_name: str,
    selected: bool,
) -> dict[str, Any]:
    is_active = str(project.get("name", "")) == str(active_name)
    active_mark = "*" if is_active else " "
    manifest = str(project.get("moulin_manifest", "")) or "<not set>"
    targets = str(project.get("targets", "")) or "<not set>"
    active_suffix = "  ACTIVE" if is_active else ""
    text = f"{active_mark} {str(project.get('name', ''))[:18]:18} {manifest[:30]:30} {targets}{active_suffix}"
    if selected and is_active:
        state = "selected-active"
    elif selected:
        state = "selected"
    elif is_active:
        state = "active"
    else:
        state = "normal"
    return {
        "text": text,
        "state": state,
        "active": is_active,
        "selected": selected,
    }


def project_is_active(project: dict[str, Any], active_project: str) -> bool:
    return project_fields.project_field_service().project_is_active(project, active_project)


def project_field_value(project: dict[str, Any], field: dict[str, Any]) -> str:
    return project_fields.project_field_service().field_value(project, field)


def normalize_project_field_value(key: str, value: str) -> str:
    return project_fields.project_field_service().normalize_value(key, value)


def project_dir_field_update(key: str, value: str) -> tuple[str, str]:
    return project_fields.project_field_service().project_dir_field_update(key, value)


def project_runtime_reload_needed(key: str) -> bool:
    return project_fields.project_field_service().runtime_reload_needed(key)


def project_preflight_reset_needed(key: str) -> bool:
    return project_fields.project_field_service().preflight_reset_needed(key)


def project_docker_image_update_needed(key: str) -> bool:
    return project_fields.project_field_service().docker_image_update_needed(key)


def apply_project_inline_field_update_for_config(
    config: dict[str, Any],
    project: dict[str, Any],
    key: str,
    raw_value: str,
) -> dict[str, Any]:
    return project_fields.project_field_service().apply_inline_field_update_for_config(config, project, key, raw_value)


def apply_active_project_file_selection_for_config(
    config: dict[str, Any],
    key: str,
    selected: str,
) -> dict[str, Any]:
    return project_fields.project_field_service().apply_active_file_selection_for_config(config, key, selected)


def apply_active_project_settings_field_for_config(
    config: dict[str, Any],
    key: str,
    raw_value: str,
) -> dict[str, Any]:
    return project_fields.project_field_service().apply_active_settings_field_for_config(config, key, raw_value)


def project_field_enabled(
    field: dict[str, Any],
    project: dict[str, Any],
    *,
    active_project: str,
    connected: bool,
    remote_has_ssh: bool,
    remote_has_project_dir: bool,
) -> bool:
    return project_fields.project_field_service().field_enabled(
        field,
        project,
        active_project=active_project,
        connected=connected,
        remote_has_ssh=remote_has_ssh,
        remote_has_project_dir=remote_has_project_dir,
    )


def project_field_disabled_reason(
    field: dict[str, Any],
    project: dict[str, Any],
    *,
    active_project: str,
    remote_has_user: bool,
    remote_has_host: bool,
    remote_has_project_dir: bool,
) -> str:
    return project_fields.project_field_service().field_disabled_reason(
        field,
        project,
        active_project=active_project,
        remote_has_user=remote_has_user,
        remote_has_host=remote_has_host,
        remote_has_project_dir=remote_has_project_dir,
    )


def project_field_hint(
    field: dict[str, Any],
    *,
    build_host_projects_dir: str,
    app_dir: str,
) -> str:
    return project_fields.project_field_service().field_hint(
        field,
        build_host_projects_dir=build_host_projects_dir,
        app_dir=app_dir,
    )


def project_is_active_for_config(project: dict[str, Any], config: dict[str, Any]) -> bool:
    return project_fields.project_field_service().project_is_active_for_config(project, config)


def project_field_enabled_for_config(
    field: dict[str, Any],
    project: dict[str, Any],
    config: dict[str, Any],
    *,
    connected: bool,
) -> bool:
    return project_fields.project_field_service().field_enabled_for_config(
        field,
        project,
        config,
        connected=connected,
    )


def project_field_disabled_reason_for_config(
    field: dict[str, Any],
    project: dict[str, Any],
    config: dict[str, Any],
) -> str:
    return project_fields.project_field_service().field_disabled_reason_for_config(field, project, config)


def project_field_enter_action_for_config(
    field: dict[str, Any],
    project: dict[str, Any],
    config: dict[str, Any],
    *,
    connected: bool,
) -> dict[str, Any]:
    return project_fields.project_field_service().field_enter_action_for_config(
        field,
        project,
        config,
        connected=connected,
    )


def project_field_hint_for_config(
    field: dict[str, Any],
    config: dict[str, Any],
    *,
    app_dir: str,
) -> str:
    return project_fields.project_field_service().field_hint_for_config(field, config, app_dir=app_dir)


def ordered_targets_for_text(
    candidates: list[dict[str, str]],
    selected: set[str],
    *,
    current_text: str | None,
    default_text: str,
) -> list[str]:
    return target_policy.target_selection_policy_service().ordered_targets_for_text(
        candidates,
        selected,
        current_text=current_text,
        default_text=default_text,
    )


def selected_targets_from_text(text: str) -> set[str]:
    return target_policy.target_selection_policy_service().selected_targets_from_text(text)


def target_actions(candidates: list[dict[str, str]]) -> list[dict[str, Any]]:
    return target_policy.target_selection_policy_service().target_actions(candidates)


def target_text_for_selection(
    candidates: list[dict[str, str]],
    selected: set[str],
    *,
    current_text: str | None,
    default_text: str,
) -> str:
    return target_policy.target_selection_policy_service().target_text_for_selection(
        candidates,
        selected,
        current_text=current_text,
        default_text=default_text,
    )


def target_display_text(
    candidates: list[dict[str, str]],
    selected: set[str],
    *,
    current_text: str | None,
    default_text: str,
) -> str:
    return target_policy.target_selection_policy_service().target_display_text(
        candidates,
        selected,
        current_text=current_text,
        default_text=default_text,
    )


def toggle_target_selection(action: dict[str, Any], selected: set[str]) -> tuple[set[str], str]:
    return target_policy.target_selection_policy_service().toggle_target_selection(action, selected)


def settings_action_label(
    action: dict[str, Any],
    *,
    active_project: dict[str, Any],
    build_params: dict[str, str],
    local_project_dir: str,
    moulin_manifest_name: str,
    project_git_url: str,
    configured_dockerfile: str,
    build_targets: str,
    board_artifacts: str,
    docker_image: str,
) -> str:
    return settings_policy.project_settings_policy_service().action_label(
        action,
        active_project=active_project,
        build_params=build_params,
        local_project_dir=local_project_dir,
        moulin_manifest_name=moulin_manifest_name,
        project_git_url=project_git_url,
        configured_dockerfile=configured_dockerfile,
        build_targets=build_targets,
        board_artifacts=board_artifacts,
        docker_image=docker_image,
    )


def settings_action_description(action: dict[str, Any]) -> str:
    return settings_policy.project_settings_policy_service().action_description(action)


def ordered_targets(
    candidates: list[dict[str, str]],
    selected: set[str],
    current_text: str,
) -> list[str]:
    return target_policy.target_selection_policy_service().ordered_targets(candidates, selected, current_text)


def build_target_action_label(action: dict[str, Any], selected: set[str]) -> str:
    return target_policy.target_selection_policy_service().action_label(action, selected)


def build_target_action_description(action: dict[str, Any]) -> str:
    return target_policy.target_selection_policy_service().action_description(action)


def next_parameter_value(param: dict[str, Any], current: str) -> str | None:
    return settings_policy.project_settings_policy_service().next_parameter_value(param, current)
