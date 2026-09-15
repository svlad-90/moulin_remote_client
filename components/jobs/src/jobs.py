"""Command job state helpers."""

from __future__ import annotations

import os
import subprocess
import threading
import re
from collections import deque
from typing import Any, Callable


def create_command_job(
    *,
    title: str,
    item_label: str,
    slot: str | None,
    commands: list[list[str]],
    kind: str | None = None,
    initial_output: list[str] | None = None,
    started_at: float | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    job = {
        "title": title,
        "item_label": item_label,
        "slot": slot or "build",
        "commands": commands,
        "index": 0,
        "output": deque(initial_output or [], maxlen=1000),
        "output_lock": threading.Lock(),
        "process": None,
        "current_command": "",
        "rc": None,
    }
    if kind is not None:
        job["kind"] = kind
    if started_at is not None:
        job["started_at"] = started_at
    if timeout is not None:
        job["timeout"] = timeout
    return job


def create_build_connect_job(*, item_label: str, command: list[str], started_at: float) -> dict[str, Any]:
    return create_command_job(
        kind="connect",
        title="Connect to build host",
        item_label=item_label,
        slot="build",
        commands=[command],
        initial_output=["Starting remote preflight..."],
        started_at=started_at,
        timeout=10.0,
    )


def create_board_connect_job(*, item_label: str, command: list[str], started_at: float) -> dict[str, Any]:
    return create_command_job(
        kind="board-connect",
        title="Connect to board host",
        item_label=item_label,
        slot="board",
        commands=[command],
        initial_output=["Starting board host SSH check..."],
        started_at=started_at,
        timeout=10.0,
    )


def job_running(job: dict[str, Any] | None) -> bool:
    if job is None:
        return False
    return process_running(job.get("process"))


def process_returncode(process: Any) -> int | None:
    poll = getattr(process, "poll", None)
    if not callable(poll):
        return None
    return poll()


def process_running(process: Any) -> bool:
    poll = getattr(process, "poll", None)
    return callable(poll) and poll() is None


def process_pid(process: Any) -> int | None:
    pid = getattr(process, "pid", None)
    return int(pid) if isinstance(pid, int) else None


def running_job_list(
    active_job: dict[str, Any] | None,
    board_job: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    return [job for job in (active_job, board_job) if job is not None]


def has_active_job(
    active_job: dict[str, Any] | None,
    board_job: dict[str, Any] | None,
) -> bool:
    return active_job is not None or board_job is not None


def any_job_running(jobs: list[dict[str, Any]]) -> bool:
    return any(job_running(job) for job in jobs)


def no_running_command_message(slot: str | None, *, punctuation: bool) -> str:
    if slot == "board":
        text = "No board command is running"
    elif slot == "build":
        text = "No build or sync command is running"
    else:
        text = "No command is running"
    return text + "." if punctuation else text


def stop_running_preview(job: dict[str, Any] | None, slot: str | None = None) -> str:
    if job is None:
        return no_running_command_message(slot, punctuation=True)
    title = str(job.get("title", "Command"))
    return f"Stop active command: {title}"


def log_visible_lines(height: int, *, expanded: bool) -> int:
    if expanded:
        return max(1, height - 6)
    panel_top = 11
    panel_height = height - 13
    details_height = max(8, panel_height // 2)
    logs_height = max(5, panel_height - details_height - 1)
    return max(1, logs_height - 6)


def job_output_lines(job: dict[str, Any] | None) -> list[str]:
    if job is None:
        return []
    lock = job.get("output_lock")
    if hasattr(lock, "__enter__") and hasattr(lock, "__exit__"):
        with lock:
            return list(job.get("output", []))
    return list(job.get("output", []))


def log_max_scroll(job: dict[str, Any] | None, visible: int) -> int:
    if job is None:
        return 0
    return max(0, len(job_output_lines(job)) - max(1, visible))


def clamp_log_scroll(
    job: dict[str, Any] | None,
    visible: int,
    *,
    follow: bool,
    scroll: int,
) -> tuple[int, bool]:
    max_scroll = log_max_scroll(job, visible)
    if follow:
        return max_scroll, True
    return min(max(0, scroll), max_scroll), False


def log_scroll_plan(
    job: dict[str, Any] | None,
    visible: int,
    *,
    follow: bool,
    scroll: int,
    delta: int,
) -> dict[str, Any]:
    if job is None:
        return {"status": "No log for selected action"}
    max_scroll = log_max_scroll(job, visible)
    current, _ = clamp_log_scroll(job, visible, follow=follow, scroll=scroll)
    if delta < 0:
        return {
            "log_scroll": max(0, current + delta),
            "log_follow": False,
        }
    next_scroll = min(max_scroll, current + delta)
    return {
        "log_scroll": next_scroll,
        "log_follow": next_scroll >= max_scroll,
    }


def display_job_for_label(
    label: str,
    active_job: dict[str, Any] | None,
    last_board_job: dict[str, Any] | None,
    last_job: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if active_job is not None:
        return active_job
    if last_board_job is not None and label == last_board_job.get("item_label"):
        return last_board_job
    if last_job is not None and label == last_job.get("item_label"):
        return last_job
    return None


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


def selected_or_first_running_job(
    *,
    slot: str | None,
    active_job: dict[str, Any] | None,
    board_job: dict[str, Any] | None,
    selected_job: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if slot in {"build", "board"}:
        return active_job_for_slot(slot, active_job=active_job, board_job=board_job)
    if selected_job is not None:
        return selected_job
    jobs = [job for job in (active_job, board_job) if job is not None]
    return jobs[0] if jobs else None


def selected_or_first_running_job_for_label(
    *,
    slot: str | None,
    active_job: dict[str, Any] | None,
    board_job: dict[str, Any] | None,
    selected_item_label: str | None,
) -> dict[str, Any] | None:
    selected_job = None
    if selected_item_label is not None:
        for job in running_job_list(active_job, board_job):
            if selected_item_label == job.get("item_label"):
                selected_job = job
                break
    return selected_or_first_running_job(
        slot=slot,
        active_job=active_job,
        board_job=board_job,
        selected_job=selected_job,
    )


def stop_running_preview_for_label(
    *,
    slot: str | None,
    active_job: dict[str, Any] | None,
    board_job: dict[str, Any] | None,
    selected_item_label: str | None,
) -> str:
    return stop_running_preview(
        selected_or_first_running_job_for_label(
            slot=slot,
            active_job=active_job,
            board_job=board_job,
            selected_item_label=selected_item_label,
        ),
        slot,
    )


def request_stop_plan(
    job: dict[str, Any] | None,
    slot: str | None,
    *,
    process_running: bool,
    now: float,
) -> dict[str, Any]:
    if job is None:
        return {
            "action": "status",
            "status": no_running_command_message(slot, punctuation=False),
        }
    if job.get("stopping"):
        return {
            "action": "status",
            "status": "Command stop is already requested",
        }
    job["stopping"] = True
    if process_running:
        job["stop_requested_at"] = now
        return {
            "action": "terminate",
            "log": "stop requested: SIGTERM",
            "status": "Stop requested",
            "logs_dirty": True,
        }
    job["rc"] = 130
    return {
        "action": "finish",
        "log": "stopped: no active process",
        "state": {
            "last_exit": 130,
            "status": f"{job.get('title', 'Command')}: stopped",
        },
    }


def build_command_start_plan(
    *,
    title: str,
    item_label: str,
    slot: str | None,
    commands: list[list[str]],
    action_running: bool,
    active_job: dict[str, Any] | None,
    board_job: dict[str, Any] | None,
) -> dict[str, Any]:
    if action_running:
        return {"rc": 1, "status": "Another action is already running"}
    if active_job_for_slot(slot, active_job=active_job, board_job=board_job) is not None:
        return {"rc": 1, "status": f"Another {slot or 'command'} action is already running"}
    return {
        "rc": 0,
        "slot": "board" if slot == "board" else "build",
        "job": create_command_job(
            title=title,
            item_label=item_label,
            slot=slot,
            commands=commands,
        ),
        "state": command_started_state(title),
    }


def command_started_state(title: str) -> dict[str, Any]:
    return {
        "status": f"Running: {title}",
        "focus_panel": "actions",
        "menu_dirty": True,
        "main_full_redraw": True,
        "logs_dirty": True,
    }


def finish_job_state(
    job: dict[str, Any] | None,
    *,
    active_job: dict[str, Any] | None,
    board_job: dict[str, Any] | None,
) -> dict[str, Any]:
    if job is board_job:
        return {
            "last_board_job": board_job,
            "board_job": None,
            "menu_dirty": True,
            "main_full_redraw": True,
            "logs_dirty": True,
        }
    if job is active_job:
        return {
            "last_job": active_job,
            "active_job": None,
            "menu_dirty": True,
            "main_full_redraw": True,
            "logs_dirty": True,
        }
    return {}


def next_command_step_plan(job: dict[str, Any]) -> dict[str, Any]:
    commands = job["commands"]
    index = int(job["index"])
    if index >= len(commands):
        return {
            "action": "complete",
            "state": completed_command_sequence_state(job),
        }
    return {
        "action": "start",
        "command": commands[index],
        "index": index,
        "total": len(commands),
    }


def record_command_step_start(
    job: dict[str, Any],
    *,
    index: int,
    total: int,
    current_command: str,
    command_lines: list[str],
) -> list[str]:
    job["current_command"] = current_command
    return [f"Starting step {int(index) + 1}/{int(total)}..."] + list(command_lines)


def prepare_command_step_start(
    job: dict[str, Any],
    plan: dict[str, Any],
    *,
    display_command: Callable[[list[str]], str],
    display_command_lines: Callable[[list[str]], list[str]],
) -> dict[str, Any]:
    command = list(plan["command"])
    lines = record_command_step_start(
        job,
        index=int(plan["index"]),
        total=int(plan["total"]),
        current_command=display_command(command),
        command_lines=display_command_lines(command),
    )
    return {"command": command, "log_lines": lines}


def advance_completed_command_step(job: dict[str, Any]) -> None:
    job["index"] = int(job["index"]) + 1
    job["process"] = None


def join_output_reader(job: dict[str, Any], *, timeout: float = 0.2) -> None:
    reader = job.get("output_reader")
    is_alive = getattr(reader, "is_alive", None)
    join = getattr(reader, "join", None)
    if callable(is_alive) and callable(join) and is_alive():
        join(timeout=timeout)


def completed_command_sequence_state(job: dict[str, Any]) -> dict[str, Any]:
    rc = int(job.get("rc") or 0)
    title = str(job.get("title", "Command"))
    state: dict[str, Any] = {
        "last_exit": rc,
        "status": f"{title}: exit {rc}",
    }
    if title == "Prepare remote project" and rc == 0:
        state["needs_preflight_reset"] = True
        state["status"] = "Prepare remote project: done; reconnect to refresh preflight"
    return state


def poll_process_plan(
    job: dict[str, Any],
    *,
    process_running: bool,
    rc: int | None,
    now: float,
) -> dict[str, Any]:
    if job.get("process") is None:
        return {"action": "start_next"}
    if job.get("stopping") and process_running and stop_timeout_due(job, now):
        return {"action": "stop_timeout", "log": "stop timeout: SIGKILL"}
    if job.get("kind") in {"connect", "board-connect"} and process_running and connect_timeout_due(job, now):
        return {
            "action": "connect_timeout",
            "log": "timeout",
            "state": connect_timeout_state(job.get("kind")),
            "start_pending_auto_board_connect": job.get("kind") == "connect",
        }
    if rc is None:
        return {"action": "wait"}
    job["rc"] = int(rc)
    return {
        "action": "process_complete",
        "log": f"exit: {int(rc)}",
        "completed": completed_process_action(job, int(rc)),
    }


def stop_timeout_due(job: dict[str, Any], now: float, *, timeout: float = 2.0) -> bool:
    return bool(job.get("stopping")) and now - float(job.get("stop_requested_at", now)) > timeout


def connect_timeout_due(job: dict[str, Any], now: float) -> bool:
    return (
        job.get("kind") in {"connect", "board-connect"}
        and now - float(job.get("started_at", now)) > float(job.get("timeout", 10.0))
    )


def connect_timeout_state(kind: str | None) -> dict[str, Any]:
    state: dict[str, Any] = {"last_exit": 124}
    if kind == "board-connect":
        state["board_connection_state"] = "disconnected"
        state["status"] = "Board host disconnected: connect timeout"
    else:
        state["preflight"] = "timeout"
        state["preflight_values"] = {}
        state["connection_state"] = "disconnected"
        state["status"] = "Disconnected: connect timeout"
    return state


def stopped_state(title: str, rc: int) -> dict[str, Any]:
    return {"last_exit": int(rc), "status": f"{title}: stopped ({rc})"}


def connect_completed_state(rc: int) -> dict[str, Any]:
    connected = int(rc) == 0
    return {
        "last_exit": int(rc),
        "connection_state": "connected" if connected else "disconnected",
        "status": "Connected" if connected else "Disconnected: connect failed",
    }


def board_connect_completed_state(rc: int) -> dict[str, Any]:
    connected = int(rc) == 0
    return {
        "last_exit": int(rc),
        "board_connection_state": "connected" if connected else "disconnected",
        "status": "Board host connected" if connected else "Board host disconnected: connect failed",
    }


def command_failed_state(title: str, rc: int) -> dict[str, Any]:
    return {"last_exit": int(rc), "status": f"{title}: exit {rc}"}


def completed_process_action(job: dict[str, Any], rc: int) -> dict[str, Any]:
    title = str(job.get("title", "Command"))
    kind = job.get("kind")
    if job.get("stopping"):
        return {"action": "finish", "state": stopped_state(title, rc)}
    if kind == "connect":
        return {"action": "connect", "state": connect_completed_state(rc)}
    if kind == "board-connect":
        return {"action": "board-connect", "state": board_connect_completed_state(rc)}
    if int(rc) != 0:
        return {"action": "finish", "state": command_failed_state(title, rc)}
    return {"action": "advance", "state": {}}


def sanitize_log_line(line: str) -> str:
    line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line)
    return "".join(char if char == "\t" or ord(char) >= 32 else " " for char in line)


def append_log_line_locked(job: dict[str, Any], output: Any, line: str) -> bool:
    if line == "" and job.get("last_log_line_blank"):
        return False
    output.append(line)
    job["last_log_line_blank"] = line == ""
    return True


def trim_output(output: Any, max_lines: int = 1000) -> None:
    if not isinstance(output, deque) and len(output) > max_lines:
        del output[: len(output) - max_lines]


def append_job_output(job: dict[str, Any], line: str) -> None:
    lines = [sanitize_log_line(part) for part in re.split(r"\r\n|\n|\r", line)]
    lock = job.get("output_lock")
    if hasattr(lock, "__enter__") and hasattr(lock, "__exit__"):
        with lock:
            output = job.setdefault("output", deque(maxlen=1000))
            for clean_line in lines:
                append_log_line_locked(job, output, clean_line)
            trim_output(output)
    else:
        output = job.setdefault("output", deque(maxlen=1000))
        for clean_line in lines:
            append_log_line_locked(job, output, clean_line)
        trim_output(output)


def append_job_output_stream(job: dict[str, Any], text: str) -> None:
    lock = job.get("output_lock")
    if hasattr(lock, "__enter__") and hasattr(lock, "__exit__"):
        with lock:
            append_job_output_stream_locked(job, text)
    else:
        append_job_output_stream_locked(job, text)


def append_job_output_stream_locked(job: dict[str, Any], text: str) -> None:
    output = job.setdefault("output", deque(maxlen=1000))
    partial = str(job.get("partial_output", ""))
    live = bool(job.get("partial_live", False))

    def set_live(value: str) -> None:
        nonlocal live
        if live and output:
            output[-1] = value
            job["last_log_line_blank"] = value == ""
        else:
            live = append_log_line_locked(job, output, value)

    for char in text:
        if char in "\r\n":
            if partial:
                set_live(sanitize_log_line(partial))
                partial = ""
            live = False
            continue
        partial += char
        if len(partial) >= 120 or live:
            set_live(sanitize_log_line(partial))
    if partial:
        set_live(sanitize_log_line(partial))
    job["partial_output"] = partial
    job["partial_live"] = live
    trim_output(output)


def read_process_output_stream(
    process: Any,
    job: dict[str, Any],
    mark_dirty: Callable[[], None] | None = None,
) -> None:
    stdout = getattr(process, "stdout", None)
    if stdout is None:
        return
    try:
        while True:
            chunk = os.read(stdout.fileno(), 4096)
            if not chunk:
                break
            append_job_output_stream(job, chunk.decode(errors="replace"))
            if mark_dirty is not None:
                mark_dirty()
    finally:
        try:
            stdout.close()
        except Exception:
            pass


def start_command_process(
    job: dict[str, Any],
    command: list[str],
    mark_dirty: Callable[[], None] | None = None,
) -> Any:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    job["process"] = process
    reader = threading.Thread(target=read_process_output_stream, args=(process, job, mark_dirty), daemon=True)
    job["output_reader"] = reader
    reader.start()
    return process
