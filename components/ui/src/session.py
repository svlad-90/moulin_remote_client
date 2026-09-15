"""Session state display helpers."""

from __future__ import annotations

import shlex
from typing import Any, Callable


def apply_state(target: Any, state: dict[str, Any]) -> None:
    for name, value in state.items():
        setattr(target, name, value)


def reset_preflight(target: Any) -> None:
    target.preflight = "not run"
    target.preflight_values = {}
    if hasattr(target, "menu_dirty"):
        target.menu_dirty = True
    render_cache = getattr(target, "render_cache", None)
    if isinstance(render_cache, dict):
        render_cache.pop("header", None)


def run_curses_app(
    config: dict[str, Any],
    *,
    app_factory: Callable[[Any, dict[str, Any]], Any],
    wrapper: Callable[[Callable[[Any], Any]], Any],
) -> Any:
    return wrapper(lambda screen: app_factory(screen, config).run())


def connection_label(state: str) -> str:
    labels = {
        "connected": "Disconnect",
        "connecting": "Connecting...",
        "disconnecting": "Disconnecting...",
        "disconnected": "Connect",
    }
    return labels.get(state, "Connect")


def connection_menu_label(item_label: str, *, build_state: str, board_state: str) -> str:
    if item_label == "Connect build host":
        return f"{connection_label(build_state)} build host"
    if item_label == "Connect board host":
        return f"{connection_label(board_state)} board host"
    return item_label


def build_host_toggle_guard(
    *,
    action_running: bool,
    active_job_exists: bool,
    connected: bool,
    remote_has_user: bool,
    remote_has_host: bool,
) -> dict[str, str | bool]:
    if action_running:
        return {"allowed": False, "status": "Another action is already running"}
    if active_job_exists and not connected:
        return {"allowed": False, "status": "Another command is already running"}
    if not remote_has_user:
        return {"allowed": False, "status": "set SSH user first"}
    if not remote_has_host:
        return {"allowed": False, "status": "set SSH host first"}
    return {"allowed": True, "status": ""}


def build_host_toggle_plan(
    *,
    action_running: bool,
    active_job_exists: bool,
    connected: bool,
    remote_has_user: bool,
    remote_has_host: bool,
    remote_label: str,
    remote_spec: str,
) -> dict[str, Any]:
    guard = build_host_toggle_guard(
        action_running=action_running,
        active_job_exists=active_job_exists,
        connected=connected,
        remote_has_user=remote_has_user,
        remote_has_host=remote_has_host,
    )
    if not guard["allowed"]:
        return {"action": "status", "status": guard["status"]}
    if connected:
        return {
            "action": "confirm_disconnect",
            "confirm_title": "Disconnect",
            "confirm_subject": f"{remote_label}  {remote_spec}",
            "cancel_status": "Cancelled: Disconnect",
            "start_state": build_host_disconnect_start_state(),
            "done_state": build_host_disconnected_state(),
        }
    return {"action": "start_connect"}


def board_host_toggle_guard(
    *,
    action_running: bool,
    board_job_exists: bool,
    connected: bool,
    board_has_user: bool,
    board_has_host: bool,
) -> dict[str, str | bool]:
    if action_running:
        return {"allowed": False, "status": "Another action is already running"}
    if board_job_exists and not connected:
        return {"allowed": False, "status": "Another board command is already running"}
    if not board_has_user:
        return {"allowed": False, "status": "set board SSH user first"}
    if not board_has_host:
        return {"allowed": False, "status": "set board SSH host first"}
    return {"allowed": True, "status": ""}


def board_host_toggle_plan(
    *,
    action_running: bool,
    board_job_exists: bool,
    connected: bool,
    board_has_user: bool,
    board_has_host: bool,
    board_label: str,
    board_spec: str,
) -> dict[str, Any]:
    guard = board_host_toggle_guard(
        action_running=action_running,
        board_job_exists=board_job_exists,
        connected=connected,
        board_has_user=board_has_user,
        board_has_host=board_has_host,
    )
    if not guard["allowed"]:
        return {"action": "status", "status": guard["status"]}
    if connected:
        return {
            "action": "confirm_disconnect",
            "confirm_title": "Disconnect board host",
            "confirm_subject": f"{board_label}  {board_spec}",
            "cancel_status": "Cancelled: Disconnect board host",
            "start_state": board_host_disconnect_start_state(),
            "done_state": board_host_disconnected_state(),
        }
    return {"action": "start_connect"}


def build_host_disconnect_start_state() -> dict[str, str]:
    return {"connection_state": "disconnecting", "status": "Disconnecting..."}


def build_host_disconnected_state() -> dict[str, str]:
    return {"connection_state": "disconnected", "status": "Disconnected"}


def board_host_disconnect_start_state() -> dict[str, str]:
    return {"board_connection_state": "disconnecting", "status": "Disconnecting board host..."}


def board_host_disconnected_state() -> dict[str, str]:
    return {"board_connection_state": "disconnected", "status": "Board host disconnected"}


def build_host_connect_start_state() -> dict[str, str]:
    return {
        "connection_state": "connecting",
        "preflight": "checking...",
        "status": "Connecting...",
    }


def board_host_connect_start_state() -> dict[str, str]:
    return {"board_connection_state": "connecting", "status": "Connecting board host..."}


def connect_job_started_state() -> dict[str, str | bool]:
    return {
        "focus_panel": "actions",
        "menu_dirty": True,
        "main_full_redraw": True,
        "logs_dirty": True,
    }


def auto_connect_plan(
    *,
    auto_connect_done: bool,
    board_has_ssh: bool,
    remote_has_ssh: bool,
) -> dict[str, Any]:
    if auto_connect_done:
        return {"action": "noop"}
    if remote_has_ssh:
        return {
            "action": "start_build",
            "state": {
                "auto_connect_done": True,
                "pending_auto_board_connect": board_has_ssh,
            },
        }
    if board_has_ssh:
        return {
            "action": "start_board",
            "state": {
                "auto_connect_done": True,
                "pending_auto_board_connect": False,
            },
        }
    return {
        "action": "status",
        "state": {
            "auto_connect_done": True,
            "pending_auto_board_connect": False,
            "status": "Build and board SSH user/host are not configured",
        },
    }


def pending_board_connect_plan(
    *,
    pending_auto_board_connect: bool,
    action_running: bool,
    board_job_exists: bool,
    board_has_ssh: bool,
    board_connected: bool,
) -> dict[str, Any]:
    if not pending_auto_board_connect:
        return {"action": "noop"}
    state = {"pending_auto_board_connect": False}
    if action_running or board_job_exists or not board_has_ssh or board_connected:
        return {"action": "clear", "state": state}
    return {"action": "start_board", "state": state}


def build_host_connection_preview(state: str, connect_command: list[str]) -> str:
    if state == "connected":
        return "disconnect from Moulin client build host session"
    if state == "connecting":
        return "checking SSH access to the build host"
    if state == "disconnecting":
        return "clearing local connection state"
    return shlex.join(connect_command)


def board_host_connection_preview(state: str, connect_command: list[str]) -> str:
    if state == "connected":
        return "disconnect from Moulin client board host session"
    if state == "connecting":
        return "checking SSH access to the board host"
    if state == "disconnecting":
        return "clearing board connection state"
    return shlex.join(connect_command)
