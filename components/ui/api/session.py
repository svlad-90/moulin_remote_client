"""Session state UI API."""

from __future__ import annotations

from components.ui.src.session import (
    apply_state,
    board_host_connect_start_state,
    board_host_connection_preview,
    board_host_disconnected_state,
    board_host_disconnect_start_state,
    board_host_toggle_guard,
    board_host_toggle_plan,
    auto_connect_plan,
    build_host_connect_start_state,
    build_host_connection_preview,
    build_host_disconnected_state,
    build_host_disconnect_start_state,
    build_host_toggle_guard,
    build_host_toggle_plan,
    connect_job_started_state,
    connection_label,
    connection_menu_label,
    pending_board_connect_plan,
    reset_preflight,
    run_curses_app,
)

__all__ = [
    "apply_state",
    "auto_connect_plan",
    "board_host_connect_start_state",
    "board_host_connection_preview",
    "board_host_disconnected_state",
    "board_host_disconnect_start_state",
    "board_host_toggle_guard",
    "board_host_toggle_plan",
    "build_host_connect_start_state",
    "build_host_connection_preview",
    "build_host_disconnected_state",
    "build_host_disconnect_start_state",
    "build_host_toggle_guard",
    "build_host_toggle_plan",
    "connect_job_started_state",
    "connection_label",
    "connection_menu_label",
    "pending_board_connect_plan",
    "reset_preflight",
    "run_curses_app",
]
