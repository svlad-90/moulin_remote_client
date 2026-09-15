"""Configuration field UI policy helpers."""

from __future__ import annotations

from typing import Any

from components.config.api import accessors
from components.host_config.api import host_fields
from components.config.api import profiles as config_profiles


def board_host_fields() -> list[tuple[str, str]]:
    return [
        ("Profile name", "name"),
        ("Display label", "label"),
        ("Board type", "type"),
        ("SSH user", "user"),
        ("SSH host", "host"),
        ("Working dir", "work_dir"),
        ("Console device", "console_device"),
        ("UFS load addr", "ufs_loadaddr"),
        ("UFS buffer size", "ufs_buffersize"),
        ("Direct copy", "direct_copy"),
    ]


def remote_fields() -> list[tuple[str, str]]:
    return [
        ("Profile name", "name"),
        ("Display label", "label"),
        ("SSH user", "user"),
        ("SSH host", "host"),
        ("Projects dir", "projects_dir"),
    ]


def host_profile_row_model(
    profile: dict[str, Any],
    *,
    active_name: str,
    selected: bool,
) -> dict[str, Any]:
    is_active = str(profile.get("name", "")) == str(active_name)
    active_mark = "*" if is_active else " "
    user_host = f"{profile.get('user', '')}@{profile.get('host', '')}"
    active_suffix = "  ACTIVE" if is_active else ""
    text = f"{active_mark} {str(profile.get('name', ''))[:18]:18} {user_host}{active_suffix}"
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


def host_profile_page_scroll(index: int, total: int, visible: int) -> int:
    return min(max(0, index - visible + 1), max(0, total - visible))


def host_profile_count_label(index: int, total: int, label: str) -> str:
    return f"{index + 1}/{total} {label}"


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


def host_field_row_model(
    *,
    label: str,
    key: str,
    profile: dict[str, Any],
    value: str,
    enabled: bool,
    selected: bool,
    editing: bool,
    label_width: int = 20,
) -> dict[str, Any]:
    display_value = value or "<not set>"
    if editing:
        state = "editing"
    elif selected and enabled:
        state = "selected"
    elif selected:
        state = "selected-disabled"
    elif not enabled:
        state = "disabled"
    else:
        state = "normal"
    return {
        "key": key,
        "label": label,
        "value": display_value,
        "text": f"{label}:".ljust(label_width) + display_value,
        "state": state,
        "enabled": enabled,
        "selected": selected,
        "editing": editing,
        "raw": profile.get(key, ""),
    }


def configuration_screen_key_action(
    *,
    focus: str,
    list_focus: str,
    selected_exists: bool,
    fields_exist: bool,
    selected_field_key: str = "",
    left: bool = False,
    right: bool = False,
    up: bool = False,
    down: bool = False,
    enter: bool = False,
    space: bool = False,
    add: bool = False,
    delete: bool = False,
    set_active: bool = False,
    escape: bool = False,
    quit: bool = False,
) -> dict[str, Any]:
    if left:
        return {"action": "focus-list", "focus": list_focus}
    if right:
        if selected_exists:
            return {"action": "focus-fields"}
        return {"action": "status", "status": "add-first"}
    if up:
        if focus == "fields" and fields_exist:
            return {"action": "move-field", "delta": -1}
        return {"action": "move-list", "delta": -1}
    if down:
        if focus == "fields" and fields_exist:
            return {"action": "move-field", "delta": 1}
        return {"action": "move-list", "delta": 1}
    if enter:
        if not selected_exists:
            return {"action": "status", "status": "add-first"}
        if focus == list_focus:
            return {"action": "focus-fields"}
        return {"action": "enter-field"}
    if space and selected_exists and focus == "fields" and selected_field_key in ("direct_copy", "type"):
        return {"action": "toggle-field-choice"}
    if add:
        return {"action": "add"}
    if delete:
        if selected_exists:
            return {"action": "delete"}
        return {"action": "status", "status": "none-selected"}
    if set_active:
        if selected_exists:
            return {"action": "set-active"}
        return {"action": "status", "status": "none-selected"}
    if escape and focus == "fields":
        return {"action": "focus-list", "focus": list_focus, "status": "list-focused"}
    if quit or escape:
        return {"action": "quit"}
    return {"action": "noop"}


def normalize_board_host_field_value(key: str, value: str) -> str:
    return host_fields.board_host_field_service().normalize_value(key, value)


def next_direct_copy_value(current: str) -> str:
    return host_fields.board_host_field_service().next_direct_copy_value(current)


def next_board_type_value(current: str) -> str:
    return host_fields.board_host_field_service().next_board_type_value(current)


def available_board_type_options() -> list[dict[str, str]]:
    return host_fields.board_host_field_service().available_board_type_options()


def board_host_connection_reset_needed(key: str, host_name: str, active_board_host: str) -> bool:
    return host_fields.board_host_field_service().connection_reset_needed(key, host_name, active_board_host)


def apply_board_host_inline_field_update_for_config(
    config: dict[str, Any],
    host: dict[str, Any],
    key: str,
    raw_value: str,
) -> dict[str, Any]:
    return host_fields.board_host_field_service().apply_inline_field_update_for_config(config, host, key, raw_value)


def apply_board_host_direct_copy_toggle_for_config(config: dict[str, Any], host: dict[str, Any]) -> dict[str, Any]:
    return host_fields.board_host_field_service().apply_direct_copy_toggle_for_config(config, host)


def normalize_remote_field_value(key: str, value: str) -> str:
    return host_fields.build_host_field_service().normalize_value(key, value)


def remote_connection_reset_needed(key: str, remote_name: str, active_remote: str) -> bool:
    return host_fields.build_host_field_service().connection_reset_needed(key, remote_name, active_remote)


def apply_remote_inline_field_update_for_config(
    config: dict[str, Any],
    remote: dict[str, Any],
    key: str,
    raw_value: str,
) -> dict[str, Any]:
    return host_fields.build_host_field_service().apply_inline_field_update_for_config(config, remote, key, raw_value)


def apply_remote_labeled_field_update_for_config(
    config: dict[str, Any],
    remote: dict[str, Any],
    key: str,
    raw_value: str,
    label: str,
) -> dict[str, Any]:
    return host_fields.build_host_field_service().apply_labeled_field_update_for_config(
        config,
        remote,
        key,
        raw_value,
        label,
    )


def apply_remote_projects_dir_selection_for_config(
    config: dict[str, Any],
    remote: dict[str, Any],
    selected: str,
) -> dict[str, Any]:
    return host_fields.build_host_field_service().apply_projects_dir_selection_for_config(config, remote, selected)


def board_host_field_enabled(key: str, host: dict[str, Any]) -> bool:
    return host_fields.board_host_field_service().field_enabled(key, host)


def board_host_field_disabled_reason(key: str, host: dict[str, Any]) -> str:
    return host_fields.board_host_field_service().field_disabled_reason(key, host)


def board_host_field_hint(key: str) -> str:
    return host_fields.board_host_field_service().field_hint(key)


def remote_field_enabled(key: str, remote: dict[str, Any], *, active_remote: str, connected: bool) -> bool:
    return host_fields.build_host_field_service().field_enabled(
        key,
        remote,
        active_remote=active_remote,
        connected=connected,
    )


def remote_field_disabled_reason(
    key: str,
    remote: dict[str, Any],
    *,
    active_remote: str,
    remote_has_project_dir: bool,
) -> str:
    return host_fields.build_host_field_service().field_disabled_reason(
        key,
        remote,
        active_remote=active_remote,
        remote_has_project_dir=remote_has_project_dir,
    )


def remote_field_hint(key: str) -> str:
    return host_fields.build_host_field_service().field_hint(key)


def remote_field_enabled_for_config(
    key: str,
    remote: dict[str, Any],
    config: dict[str, Any],
    *,
    connected: bool,
) -> bool:
    return host_fields.build_host_field_service().field_enabled_for_config(
        key,
        remote,
        config,
        connected=connected,
    )


def remote_field_disabled_reason_for_config(
    key: str,
    remote: dict[str, Any],
    config: dict[str, Any],
) -> str:
    return host_fields.build_host_field_service().field_disabled_reason_for_config(key, remote, config)


def remote_draft_for_config(config: dict[str, Any]) -> dict[str, str]:
    return {
        "name": config_profiles.next_remote_name(config.get("remotes", [])),
        "label": "",
        "user": "",
        "host": "",
        "projects_dir": "",
    }


def remote_draft_actions() -> list[dict[str, str]]:
    return [
        {"label": "Edit profile name", "kind": "name", "description": "Unique local profile id."},
        {"label": "Edit display label", "kind": "label", "description": "Human-readable label shown in the header."},
        {"label": "Edit SSH user", "kind": "user", "description": "Remote SSH user. Required before the profile can be used."},
        {"label": "Edit SSH host", "kind": "host", "description": "Remote SSH host. Required before the profile can be used."},
        {"label": "Create remote", "kind": "create", "description": "Save this profile and make it active."},
        {"label": "Cancel", "kind": "cancel", "description": "Return without saving this profile."},
    ]


def add_remote_action_enabled(kind: str, draft: dict[str, str], remotes: list[dict[str, Any]]) -> bool:
    if kind == "create":
        return not add_remote_action_disabled_reason(kind, draft, remotes)
    return True


def add_remote_action_disabled_reason(kind: str, draft: dict[str, str], remotes: list[dict[str, Any]]) -> str:
    if kind != "create":
        return ""
    name = draft.get("name", "").strip()
    if not name:
        return "set profile name first"
    if any(str(remote.get("name", "")) == name for remote in remotes):
        return "profile name already exists"
    if not draft.get("user", "").strip():
        return "set SSH user first"
    if not draft.get("host", "").strip():
        return "set SSH host first"
    return ""


def remote_draft_action_model(
    action: dict[str, str],
    draft: dict[str, str],
    remotes: list[dict[str, Any]],
) -> dict[str, Any]:
    kind = str(action["kind"])
    value = f": {draft[kind] or '<not set>'}" if kind in draft else ""
    return {
        "label": str(action["label"]),
        "kind": kind,
        "description": str(action["description"]),
        "enabled": add_remote_action_enabled(kind, draft, remotes),
        "disabled_reason": add_remote_action_disabled_reason(kind, draft, remotes),
        "text": f"{action['label']}{value}",
    }


def remote_draft_enter_action_for_config(
    config: dict[str, Any],
    draft: dict[str, str],
    action: dict[str, str],
) -> dict[str, Any]:
    model = remote_draft_action_model(action, draft, config.get("remotes", []))
    if not model["enabled"]:
        return {"action": "status", "status": model["disabled_reason"]}
    kind = str(model["kind"])
    if kind in draft:
        return {"action": "edit", "kind": kind, "label": str(model["label"]).removeprefix("Edit ")}
    if kind == "create":
        return {"action": "create"}
    if kind == "cancel":
        return {"action": "cancel", "status": "Build host add cancelled"}
    return {"action": "noop"}


def apply_remote_draft_create_for_config(config: dict[str, Any], draft: dict[str, str]) -> dict[str, Any]:
    new_remote = {key: str(value).strip() for key, value in draft.items()}
    if not new_remote.get("label"):
        new_remote["label"] = new_remote["name"]
    new_remote["projects_dir"] = ""
    config.setdefault("remotes", []).append(new_remote)
    config["active_remote"] = new_remote["name"]
    config_profiles.sync_active_remote(config)
    return {
        "status": f"Remote profile added: {new_remote['name']}",
        "connection_reset": True,
        "preflight_reset": True,
    }
