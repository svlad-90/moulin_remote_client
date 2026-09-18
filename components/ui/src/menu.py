"""Menu model helpers for the terminal UI."""

from __future__ import annotations

import shlex
import textwrap
from dataclasses import dataclass
from typing import Any, Callable

BOARD_COMMAND_LABELS = {
    "Copy build artifacts",
    "Flash bootloaders",
    "Flash UFS image",
    "Deploy TFTP boot artifacts",
    "Deploy DomD NFS rootfs",
    "Deploy Android image to NFS",
    "Deploy full TFTP/NFS set",
    "Pull TFTP/NFS workspace",
    "Push TFTP/NFS workspace",
    "Apply U-Boot network env",
}
GROUP_SEPARATOR = " / "
TAB_ORDER = ["configuration", "sessions", "build", "flashing", "tftp/nfs"]
TAB_LABELS = {
    "configuration": "Configuration",
    "build": "Build",
    "sessions": "Sessions",
    "flashing": "Board",
    "tftp/nfs": "TFTP/NFS",
}


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
    if is_open_item(item):
        return None
    if is_board_command_item(item) or item.label == "Connect board host":
        return "board"
    if is_build_command_group(item.group) or item.group == "sync" or item.label == "Connect build host":
        return "build"
    return None


def is_build_command_group(group: str) -> bool:
    parent, _child = split_group(group)
    return parent in {"build", "build commands"}


def is_board_command_item(item: MenuItem) -> bool:
    if is_open_item(item):
        return False
    parent, _child = split_group(item.group)
    if parent == "tftp/nfs" and item.label.startswith("Open local "):
        return False
    return parent in {"board commands", "flashing", "tftp/nfs"} or item.label in BOARD_COMMAND_LABELS


def is_open_item(item: MenuItem) -> bool:
    return item.label.startswith("Open ")


def split_group(group: str) -> tuple[str, str]:
    if GROUP_SEPARATOR not in group:
        return group, ""
    parent, child = group.split(GROUP_SEPARATOR, 1)
    return parent, child


def tab_for_group(group: str) -> str:
    parent, _child = split_group(group)
    if parent in TAB_ORDER:
        return parent
    if parent in {"setup"}:
        return "configuration"
    if parent in {"build commands", "sync"}:
        return "build"
    if parent in {"build host session", "board host session"}:
        return "sessions"
    if parent == "board commands":
        return "flashing"
    return parent or "build"


def item_tab(item: MenuItem) -> str:
    return tab_for_group(item.group)


def menu_tabs(items: list[MenuItem]) -> list[str]:
    present = {item_tab(item) for item in items}
    ordered = [tab for tab in TAB_ORDER if tab in present]
    ordered.extend(sorted(present - set(ordered)))
    return ordered


def tab_label(tab: str) -> str:
    return TAB_LABELS.get(tab, tab.capitalize())


def normalize_active_tab(active_tab: str, items: list[MenuItem], selected: int) -> str:
    tabs = menu_tabs(items)
    if not tabs:
        return ""
    if active_tab in tabs:
        return active_tab
    if 0 <= selected < len(items):
        selected_tab = item_tab(items[selected])
        if selected_tab in tabs:
            return selected_tab
    return tabs[0]


def visible_item_indices(items: list[MenuItem], active_tab: str) -> list[int]:
    return [index for index, item in enumerate(items) if item_tab(item) == active_tab]


def selected_in_indices(selected: int, indices: list[int]) -> bool:
    return selected in set(indices)


def nearest_visible_selection(selected: int, indices: list[int], enabled: list[bool]) -> int:
    candidates = [index for index in indices if 0 <= index < len(enabled) and enabled[index]]
    if not candidates:
        return indices[0] if indices else 0
    if selected in candidates:
        return selected
    return min(candidates, key=lambda index: abs(index - selected))


def move_visible_selection(selected: int, indices: list[int], enabled: list[bool], delta: int) -> int:
    candidates = [index for index in indices if 0 <= index < len(enabled) and enabled[index]]
    if not candidates:
        return selected
    if selected not in candidates:
        return candidates[0]
    pos = candidates.index(selected)
    return candidates[(pos + delta) % len(candidates)]


def menu_rows_for_indices(items: list[MenuItem], labels: list[str], indices: list[int]) -> list[tuple[str, int | None]]:
    rows: list[tuple[str, int | None]] = []
    last_group = ""
    for display_index, index in enumerate(indices, start=1):
        item = items[index]
        parent, child = split_group(item.group)
        group_label = child or tab_label(parent)
        if group_label != last_group:
            if rows and rows[-1][0]:
                rows.append(("", None))
            rows.append((group_label.upper(), None))
            last_group = group_label
        rows.append((f"{display_index}. {labels[index]}", index))
    return rows


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
    last_board_jobs_by_label: dict[str, dict[str, Any]] | None = None,
    last_jobs_by_label: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    active_item_job = job_for_item(item, [job for job in (active_job, board_job) if job is not None])
    if active_item_job is not None:
        return active_item_job
    label = item.label
    if last_board_jobs_by_label is not None and label in last_board_jobs_by_label:
        return last_board_jobs_by_label[label]
    if last_jobs_by_label is not None and label in last_jobs_by_label:
        return last_jobs_by_label[label]
    if last_board_job is not None and item.label == last_board_job.get("item_label"):
        return last_board_job
    if last_job is not None and item.label == last_job.get("item_label"):
        return last_job
    return None


def menu_rows(items: list[MenuItem], labels: list[str]) -> list[tuple[str, int | None]]:
    rows: list[tuple[str, int | None]] = []
    last_parent = ""
    last_child = ""
    for index, item in enumerate(items):
        parent, child = split_group(item.group)
        if parent != last_parent:
            if last_parent:
                rows.append(("", None))
            rows.append((parent.upper(), None))
            last_parent = parent
            last_child = ""
        if child and child != last_child:
            if rows and rows[-1][0]:
                rows.append(("", None))
            rows.append((child.upper(), None))
            last_child = child
        elif not child:
            if last_child and rows and rows[-1][0]:
                rows.append(("", None))
            last_child = ""
        rows.append((f"{index + 1}. {labels[index]}", index))
    return rows


def wrapped_menu_rows(rows: list[tuple[str, int | None]], width: int) -> list[tuple[str, int | None]]:
    if width <= 0:
        return [("", item_index) for _label, item_index in rows]
    wrapped: list[tuple[str, int | None]] = []
    for label, item_index in rows:
        if not label or item_index is None or len(label) <= width:
            wrapped.append((label[:width], item_index))
            continue
        continuation_indent = " " * _menu_item_prefix_width(label)
        lines = textwrap.wrap(
            label,
            width=width,
            subsequent_indent=continuation_indent,
            break_long_words=True,
            break_on_hyphens=False,
        )
        wrapped.extend((line, item_index) for line in lines or [label[:width]])
    return wrapped


def _menu_item_prefix_width(label: str) -> int:
    number_end = label.find(". ")
    if number_end <= 0 or not label[:number_end].isdigit():
        return 0
    return number_end + 2


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
    if item.label == "Stop current board command" and stoppable_command_job(board_job) is None:
        return False
    if item.label == "Stop current board command":
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
    if is_board_command_item(item):
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
    if item.label == "Stop current board command" and stoppable_command_job(board_job) is None:
        return "no board command is running"
    if item.label == "Stop current board command":
        return ""
    jobs = [job for job in (active_job, board_job) if job is not None]
    slot = item_job_slot(item)
    slot_job = active_job_for_slot(slot, active_job=active_job, board_job=board_job)
    if slot is not None and slot_job is not None and job_for_item(item, jobs) is None:
        return f"{slot} command is already running"
    is_board_item = item.label in {"Connect board host", "Open board host shell"} or is_board_command_item(item)
    if is_board_item and not board_host_user:
        return "set board SSH user first"
    if is_board_item and not board_host_host:
        return "set board SSH host first"
    if is_board_command_item(item) and not board_connected:
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
    if action_running and not item.allow_during_job:
        return {"allowed": False, "status": "Another interactive action is already running"}
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
    if (not action_running or item.allow_during_job) and not item_running:
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
