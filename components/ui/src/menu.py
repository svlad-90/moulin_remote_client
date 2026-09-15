"""Menu model helpers for the terminal UI."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any, Callable

BOARD_COMMAND_LABELS = {"Copy build artifacts", "Flash bootloaders", "Flash UFS image"}


@dataclass(frozen=True)
class MenuItem:
    label: str
    group: str
    description: str
    preview: Callable[[Any], str]
    handler: Callable[[Any], None]
    confirm: bool = False
    requires_remote: bool = False
    requires_ssh: bool = False
    requires_project: bool = False
    allow_during_job: bool = False


def item_job_slot(item: MenuItem) -> str | None:
    if item.group == "board commands" or item.label == "Connect board host":
        return "board"
    if item.group in {"build commands", "sync"} or item.label == "Connect build host":
        return "build"
    return None


def job_for_item(item: MenuItem, jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for job in jobs:
        if item.label == job.get("item_label"):
            return job
    return None


def display_job_for_item(
    item: MenuItem,
    *,
    active_job: dict[str, Any] | None,
    board_job: dict[str, Any] | None,
    last_board_job: dict[str, Any] | None,
    last_job: dict[str, Any] | None,
) -> dict[str, Any] | None:
    active_item_job = job_for_item(item, [job for job in (active_job, board_job) if job is not None])
    if active_item_job is not None:
        return active_item_job
    if last_board_job is not None and item.label == last_board_job.get("item_label"):
        return last_board_job
    if last_job is not None and item.label == last_job.get("item_label"):
        return last_job
    return None


def menu_rows(items: list[MenuItem], labels: list[str]) -> list[tuple[str, int | None]]:
    rows: list[tuple[str, int | None]] = []
    last_group = ""
    for index, item in enumerate(items):
        if item.group != last_group:
            if last_group:
                rows.append(("", None))
            rows.append((item.group.upper(), None))
            last_group = item.group
        rows.append((f"{index + 1}. {labels[index]}", index))
    return rows


def command_preview(commands: list[list[str]]) -> str:
    if not commands:
        return "no commands"
    return "\n".join(shlex.join(command) for command in commands[:3])


def selected_menu_row(rows: list[tuple[str, int | None]], selected: int) -> int:
    return next((row for row, (_, item_index) in enumerate(rows) if item_index == selected), 0)


def clamp_menu_scroll(rows: list[tuple[str, int | None]], selected: int, scroll: int, visible_rows: int) -> int:
    selected_row = selected_menu_row(rows, selected)
    if selected_row < scroll:
        return selected_row
    if selected_row >= scroll + visible_rows:
        return selected_row - visible_rows + 1
    return scroll


def clamp_index(index: int, count: int) -> int:
    if count <= 0:
        return 0
    return min(max(0, index), count - 1)


def move_index(index: int, count: int, delta: int) -> int:
    if count <= 0:
        return 0
    return (index + delta) % count


def list_scroll(index: int, count: int, visible: int) -> int:
    visible = max(1, visible)
    return min(max(0, index - visible + 1), max(0, count - visible))


def move_selection(selected: int, enabled: list[bool], delta: int) -> int:
    if not enabled:
        return 0
    start = selected
    for step in range(1, len(enabled) + 1):
        candidate = (start + delta * step) % len(enabled)
        if enabled[candidate]:
            return candidate
    return (selected + delta) % len(enabled)


def nearest_enabled_selection(selected: int, enabled: list[bool]) -> int:
    if not enabled:
        return 0
    for offset in range(len(enabled)):
        down = (selected + offset) % len(enabled)
        if enabled[down]:
            return down
        up = (selected - offset) % len(enabled)
        if enabled[up]:
            return up
    return selected


def normalize_selection(selected: int, enabled: list[bool]) -> int:
    if not enabled:
        return 0
    normalized = min(max(0, selected), len(enabled) - 1)
    if not enabled[normalized]:
        normalized = nearest_enabled_selection(normalized, enabled)
    return normalized


def sync_menu_selection(
    previous_items: list[MenuItem],
    previous_selected: int,
    next_items: list[MenuItem],
    next_enabled: list[bool],
) -> int:
    selected = previous_selected
    if previous_items:
        selected = min(max(0, selected), len(previous_items) - 1)
    selected_label = previous_items[selected].label if previous_items else ""
    if not next_items:
        return 0
    selected = next(
        (index for index, item in enumerate(next_items) if item.label == selected_label),
        min(selected, len(next_items) - 1),
    )
    return normalize_selection(selected, next_enabled)


def active_job_for_slot(
    slot: str | None,
    *,
    active_job: dict[str, Any] | None,
    board_job: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if slot == "board":
        return board_job
    if slot == "build":
        return active_job
    return None


def stoppable_command_job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if job is None:
        return None
    if job.get("kind") in {"connect", "board-connect"}:
        return None
    return job


def item_enabled(
    item: MenuItem,
    *,
    active_job: dict[str, Any] | None,
    board_job: dict[str, Any] | None,
    board_host_has_ssh: bool,
    board_connected: bool,
    build_connected: bool,
    remote_has_ssh: bool,
    remote_has_project_dir: bool,
    prepare_remote_project_needed: bool,
    checkout_git_ref_needed: bool,
) -> bool:
    if item.label == "Stop running command" and stoppable_command_job(active_job) is None:
        return False
    if item.label == "Stop running command":
        return True
    if item.label == "Stop board command" and stoppable_command_job(board_job) is None:
        return False
    if item.label == "Stop board command":
        return True
    jobs = [job for job in (active_job, board_job) if job is not None]
    if job_for_item(item, jobs) is not None:
        return True
    slot = item_job_slot(item)
    if slot is not None and active_job_for_slot(slot, active_job=active_job, board_job=board_job) is not None:
        return False
    if item.label in {"Connect board host", "Open board host shell"} and not board_host_has_ssh:
        return False
    if item.label == "Open board host shell" and not board_connected:
        return False
    if item.group == "board commands":
        if not board_host_has_ssh or not board_connected:
            return False
    if item.requires_ssh and not remote_has_ssh:
        return False
    if item.requires_remote and not build_connected:
        return False
    if item.requires_project and not remote_has_project_dir:
        return False
    if item.label != "Prepare remote project" and item.requires_project and prepare_remote_project_needed:
        return False
    if item.label != "Checkout project Git ref" and item.requires_project and checkout_git_ref_needed:
        return False
    return True


def disabled_reason(
    item: MenuItem,
    *,
    active_job: dict[str, Any] | None,
    board_job: dict[str, Any] | None,
    board_host_user: str,
    board_host_host: str,
    board_connected: bool,
    build_connected: bool,
    remote_has_user: bool,
    remote_has_host: bool,
    remote_has_project_dir: bool,
    prepare_remote_project_needed: bool,
    checkout_git_ref_needed: bool,
) -> str:
    if item.label == "Stop running command" and stoppable_command_job(active_job) is None:
        return "no build or sync command is running"
    if item.label == "Stop running command":
        return ""
    if item.label == "Stop board command" and stoppable_command_job(board_job) is None:
        return "no board command is running"
    if item.label == "Stop board command":
        return ""
    jobs = [job for job in (active_job, board_job) if job is not None]
    slot = item_job_slot(item)
    slot_job = active_job_for_slot(slot, active_job=active_job, board_job=board_job)
    if slot is not None and slot_job is not None and job_for_item(item, jobs) is None:
        return f"{slot} command is already running"
    is_board_item = item.label in {"Connect board host", "Open board host shell"} or item.group == "board commands"
    if is_board_item and not board_host_user:
        return "set board SSH user first"
    if is_board_item and not board_host_host:
        return "set board SSH host first"
    if item.group == "board commands" and not board_connected:
        return "connect to the board host first"
    if item.label == "Open board host shell" and not board_connected:
        return "connect to the board host first"
    if item.requires_ssh and not remote_has_user:
        return "set SSH user first"
    if item.requires_ssh and not remote_has_host:
        return "set SSH host first"
    if item.requires_remote and not build_connected:
        return "connect to the build host first"
    if item.requires_project and not remote_has_project_dir:
        return "select remote project directory first"
    if item.label != "Prepare remote project" and item.requires_project and prepare_remote_project_needed:
        return "remote project needs preparation"
    if item.label != "Checkout project Git ref" and item.requires_project and checkout_git_ref_needed:
        return "remote project Git ref mismatch"
    return "disabled"


def selected_action_guard(
    item: MenuItem,
    *,
    action_running: bool,
    item_running: bool,
    enabled: bool,
    disabled_status: str,
) -> dict[str, str | bool]:
    if action_running:
        return {"allowed": False, "status": "Another action is already running"}
    if item_running:
        return {"allowed": False, "status": "Command is already running; live log is shown in Logs"}
    if not enabled:
        return {"allowed": False, "status": disabled_status}
    return {"allowed": True, "status": ""}


def selected_action_plan(
    item: MenuItem,
    running_jobs: list[dict[str, Any]],
    *,
    action_running: bool,
    enabled_for_item: Callable[[MenuItem], bool],
    disabled_reason_for_item: Callable[[MenuItem], str],
) -> dict[str, Any]:
    item_running = job_for_item(item, running_jobs) is not None
    enabled = True
    disabled_status = ""
    if not action_running and not item_running:
        enabled = enabled_for_item(item)
        if not enabled:
            disabled_status = disabled_reason_for_item(item)
    guard = selected_action_guard(
        item,
        action_running=action_running,
        item_running=item_running,
        enabled=enabled,
        disabled_status=disabled_status,
    )
    return {
        "item_running": item_running,
        "enabled": enabled,
        "disabled_status": disabled_status,
        "guard": guard,
    }
