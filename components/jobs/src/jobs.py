"""Command job state helpers."""

from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable


JOB_STATE_WAKE_KEY = 0
STOP_MODE_PTY_INTERRUPT = "pty-interrupt"
STOP_TERM_TIMEOUT = 5.0
STOP_DEFAULT_TIMEOUT = 2.0
TERMINAL_ESCAPE_MAX_LENGTH = 64
PTY_TRACE_ENV = "MOULIN_PTY_TRACE"
PTY_TRACE_DEFAULT_PATH = "/tmp/moulin-pty-trace.jsonl"
PTY_TRACE_MAX_BYTES = 2 * 1024 * 1024
_PTY_TRACE_LOCK = threading.Lock()


def trace_job_event(job: dict[str, Any], event: str, **fields: Any) -> None:
    """Append one bounded, best-effort PTY diagnostic event when enabled."""
    configured_path = os.environ.get(PTY_TRACE_ENV, "").strip()
    if not configured_path:
        return
    path = Path(
        PTY_TRACE_DEFAULT_PATH
        if configured_path.lower() in {"1", "true", "yes"}
        else configured_path
    )
    record = {
        "time_ns": time.time_ns(),
        "event": event,
        "title": str(job.get("title", "")),
        "item_label": str(job.get("item_label", "")),
        **fields,
    }
    try:
        encoded = json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n"
        with _PTY_TRACE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = "w" if path.exists() and path.stat().st_size + len(encoded) > PTY_TRACE_MAX_BYTES else "a"
            with path.open(mode, encoding="utf-8") as trace_file:
                trace_file.write(encoded)
    except OSError:
        pass


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
        "output_revision": 0,
        "wrapped_output_cache": {},
        "process": None,
        "current_command": "",
        "rc": None,
        "finished": False,
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
    return not bool(job.get("finished"))


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


def compact_log_lines(source: list[str]) -> list[str]:
    compacted: list[str] = []
    previous = None
    repeats = 0
    for line in source:
        if line == "" and compacted and compacted[-1] == "":
            continue
        if line and line == previous:
            repeats += 1
            compacted[-1] = f"{line} [repeated {repeats} times]"
            continue
        compacted.append(line)
        previous = line if line else None
        repeats = 1
    return compacted


def _job_output_source_locked(job: dict[str, Any]) -> list[str]:
    return list(job.get("output", []))


def job_output_lines(job: dict[str, Any] | None) -> list[str]:
    if job is None:
        return []
    lock = job.get("output_lock")
    if hasattr(lock, "__enter__") and hasattr(lock, "__exit__"):
        with lock:
            return compact_log_lines(_job_output_source_locked(job))
    return compact_log_lines(_job_output_source_locked(job))


def clipboard_log_text(
    job: dict[str, Any] | None,
    start: int | None = None,
    end: int | None = None,
) -> str:
    """Return readable log text without screen wrapping or blank runs."""
    source = job_output_lines(job)
    if start is not None or end is not None:
        lower = max(0, start or 0)
        upper = len(source) - 1 if end is None else min(len(source) - 1, end)
        source = source[lower : upper + 1] if lower <= upper else []
    cleaned: list[str] = []
    for line in source:
        line = line.rstrip()
        if line:
            cleaned.append(line)
        elif cleaned and cleaned[-1]:
            cleaned.append("")
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return "\n".join(cleaned)


def _wrapped_job_output(
    job: dict[str, Any] | None,
    width: int,
) -> tuple[list[str], list[int]]:
    if job is None:
        return [], []
    inner_width = max(1, width)
    lock = job.get("output_lock")
    if hasattr(lock, "__enter__") and hasattr(lock, "__exit__"):
        with lock:
            revision = int(job.get("output_revision", 0))
            cache = job.setdefault("wrapped_output_cache", {})
            cached = cache.get(inner_width)
            if cached is not None and cached[0] == revision:
                return cached[1], cached[2]
            source = compact_log_lines(_job_output_source_locked(job))
    else:
        revision = int(job.get("output_revision", 0))
        cache = job.setdefault("wrapped_output_cache", {})
        cached = cache.get(inner_width)
        if cached is not None and cached[0] == revision:
            return cached[1], cached[2]
        source = compact_log_lines(_job_output_source_locked(job))

    lines: list[str] = []
    source_indices: list[int] = []
    for source_index, line in enumerate(source):
        if not line:
            lines.append("")
            source_indices.append(source_index)
            continue
        wrapped = textwrap.wrap(
            line,
            width=inner_width,
            subsequent_indent="  ",
            replace_whitespace=False,
            drop_whitespace=True,
        )
        wrapped = wrapped or [""]
        lines.extend(wrapped)
        source_indices.extend([source_index] * len(wrapped))
    cache.clear()
    cache[inner_width] = (revision, lines, source_indices)
    return lines, source_indices


def wrapped_job_output_lines(job: dict[str, Any] | None, width: int) -> list[str]:
    return _wrapped_job_output(job, width)[0]


def wrapped_job_output_source_indices(
    job: dict[str, Any] | None,
    width: int,
) -> list[int]:
    return _wrapped_job_output(job, width)[1]


def log_max_scroll(job: dict[str, Any] | None, visible: int, *, width: int | None = None) -> int:
    if job is None:
        return 0
    output = wrapped_job_output_lines(job, width) if width is not None else job_output_lines(job)
    return max(0, len(output) - max(1, visible))


def clamp_log_scroll(
    job: dict[str, Any] | None,
    visible: int,
    *,
    follow: bool,
    scroll: int,
    width: int | None = None,
) -> tuple[int, bool]:
    max_scroll = log_max_scroll(job, visible, width=width)
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
    width: int | None = None,
) -> dict[str, Any]:
    if job is None:
        return {"status": "No log for selected action"}
    max_scroll = log_max_scroll(job, visible, width=width)
    current, _ = clamp_log_scroll(job, visible, follow=follow, scroll=scroll, width=width)
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
    if (
        job.get("stopping")
        and job.get("current_stop_mode") == STOP_MODE_PTY_INTERRUPT
        and job.get("stop_phase") == "interrupt"
        and process_running
    ):
        job["stop_phase"] = "terminate"
        job["stop_requested_at"] = now
        return {
            "action": "terminate",
            "log": "forced SSH stop requested: SIGTERM",
            "status": "Forced SSH stop requested",
            "logs_dirty": True,
        }
    if job.get("stopping"):
        return {
            "action": "status",
            "status": "Command stop is already requested",
        }
    job["stopping"] = True
    if process_running:
        job["stop_requested_at"] = now
        if job.get("current_stop_mode") == STOP_MODE_PTY_INTERRUPT:
            job["stop_phase"] = "interrupt"
            return {
                "action": "interrupt",
                "log": "graceful stop requested: Ctrl-C",
                "status": "Waiting for command to stop",
                "logs_dirty": True,
            }
        job["stop_phase"] = "terminate"
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
    normalized_slot = "board" if slot == "board" else "build"
    if active_job_for_slot(normalized_slot, active_job=active_job, board_job=board_job) is not None:
        return {"rc": 1, "status": f"Another {normalized_slot} action is already running"}
    if action_running:
        return {"rc": 1, "status": "Another interactive action is already running"}
    return {
        "rc": 0,
        "slot": normalized_slot,
        "job": create_command_job(
            title=title,
            item_label=item_label,
            slot=normalized_slot,
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
    if job is not None:
        job["finished"] = True
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
    step_label: str = "",
) -> list[str]:
    job["current_command"] = current_command
    header = f"Starting step {int(index) + 1}/{int(total)}"
    if step_label:
        header += f": {step_label}"
    else:
        header += "..."
    separator = "=" * max(36, len(header))
    lines = [separator, header, separator, ""]
    if int(index) > 0:
        lines.insert(0, "")
    return lines + list(command_lines)


def command_step_label(command: list[str]) -> str:
    text = " ".join(command)
    if ".git/index.lock" in text and "git add -A" in text and "git checkout " in text:
        return "Checkout project Git ref"
    if "git add -A" in text and "git stash push" in text and "git checkout " in text:
        return "Stash changes and checkout project Git ref"
    if "git checkout " in text and "git fetch origin --prune" in text:
        return "Checkout project Git ref"
    if ".git/index.lock" in text and "rm -f" in text:
        return "Clear stale Git index lock"
    if "Clean project folder" in text and "rm -rf" in text:
        return "Clean project folder"
    if 'ACTION = "clean"' in text:
        return "Clean impacted Yocto recipes"
    if 'ACTION = "rebuild"' in text:
        return "Rebuild impacted Yocto recipes"
    if 'ACTION = "analyze"' in text:
        return "Analyze changed Yocto recipes"
    if "repo sync " in text:
        return "Synchronize Repo source workspaces"
    if " moulin " in text or "moulin " in text:
        return "Regenerate Moulin/Ninja"
    if " ninja " in text or "ninja " in text:
        return "Run product build"
    if "docker build " in text:
        return "Build Docker image"
    if "rsync " in text or "Copy mapped files" in text:
        return "Copy mapped files"
    if "Prepare board artifacts directory" in text:
        return "Prepare board artifacts directory"
    if "Deploy board helper" in text:
        return "Deploy board helper"
    if "board console: start xt-imager" in text or "XT_FLASH_IMAGE" in text:
        return "Run UFS flasher"
    if "run bootloader flasher" in text:
        return "Run bootloader flasher"
    if "unpack boot artifacts" in text:
        return "Unpack boot artifacts"
    if "install bootloader flasher" in text:
        return "Install bootloader flasher"
    if "run: x5h_flash" in text:
        return "Enter bootloader flash mode"
    return ""


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
        step_label=command_step_label(command),
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


def schedule_connect_timeout_wakeup(job: dict[str, Any], wake: Callable[[], None]) -> None:
    if job.get("kind") not in {"connect", "board-connect"}:
        return
    timeout = float(job.get("timeout") or 0.0)
    if timeout <= 0:
        return
    timer = threading.Timer(timeout + 0.05, wake)
    timer.daemon = True
    job["timeout_wakeup_timer"] = timer
    timer.start()


def cancel_connect_timeout_wakeup(job: dict[str, Any] | None) -> None:
    timer = job.get("timeout_wakeup_timer") if job is not None else None
    cancel = getattr(timer, "cancel", None)
    if callable(cancel):
        cancel()


def completed_command_sequence_state(job: dict[str, Any]) -> dict[str, Any]:
    rc = int(job.get("rc") or 0)
    title = str(job.get("title", "Command"))
    state: dict[str, Any] = {
        "last_exit": rc,
        "status": f"{title}: exit {rc}",
    }
    if title in {"Prepare remote project", "Checkout project Git ref", "Update product"} and rc == 0:
        state["needs_preflight_reset"] = True
        state["needs_preflight_refresh"] = True
        state["needs_config_reload"] = True
        state["status"] = f"{title}: done; refreshing preflight"
    if title == "Clean project folder" and rc == 0:
        state["preflight"] = "project missing | disk ? | git ? | docker ? | origin ? | ref ?"
        state["preflight_values"] = {
            "project": "missing",
            "disk": "?",
            "git": "?",
            "docker": "?",
            "origin": "?",
            "ref": "?",
        }
        state["menu_dirty"] = True
        state["status"] = "Clean project folder: done; prepare remote project to fetch checkout"
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
    if job.get("stopping") and process_running:
        phase = job.get("stop_phase", "terminate")
        timeout = (
            STOP_TERM_TIMEOUT
            if job.get("current_stop_mode") == STOP_MODE_PTY_INTERRUPT
            else STOP_DEFAULT_TIMEOUT
        )
        if phase == "terminate" and stop_timeout_due(job, now, timeout=timeout):
            job["stop_phase"] = "kill"
            return {"action": "stop_kill", "log": "stop timeout: SIGKILL"}
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
    completion_log = (
        f"Remote command completed with exit code {int(rc)}"
        if job.get("current_stop_mode") == STOP_MODE_PTY_INTERRUPT
        else f"exit: {int(rc)}"
    )
    return {
        "action": "process_complete",
        "log": completion_log,
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
    output.append(line)
    job["last_log_line_blank"] = line == ""
    return True


def trim_output(output: Any, max_lines: int = 1000) -> None:
    if not isinstance(output, deque) and len(output) > max_lines:
        del output[: len(output) - max_lines]


def finish_stream_line_locked(job: dict[str, Any]) -> None:
    job["partial_output"] = ""
    job["partial_live"] = False
    job["terminal_cursor_column"] = 0
    job.pop("terminal_cursor_up", None)
    job.pop("terminal_escape", None)


def append_job_output(job: dict[str, Any], line: str) -> None:
    lines = [sanitize_log_line(part) for part in re.split(r"\r\n|\n|\r", line)]
    lock = job.get("output_lock")
    if hasattr(lock, "__enter__") and hasattr(lock, "__exit__"):
        with lock:
            finish_stream_line_locked(job)
            output = job.setdefault("output", deque(maxlen=1000))
            for clean_line in lines:
                append_log_line_locked(job, output, clean_line)
            trim_output(output)
            job["output_revision"] = int(job.get("output_revision", 0)) + 1
    else:
        finish_stream_line_locked(job)
        output = job.setdefault("output", deque(maxlen=1000))
        for clean_line in lines:
            append_log_line_locked(job, output, clean_line)
        trim_output(output)
        job["output_revision"] = int(job.get("output_revision", 0)) + 1


def append_job_output_stream(job: dict[str, Any], text: str) -> None:
    lock = job.get("output_lock")
    if hasattr(lock, "__enter__") and hasattr(lock, "__exit__"):
        with lock:
            append_job_output_stream_locked(job, text)
    else:
        append_job_output_stream_locked(job, text)


def erase_rewound_display_tail_locked(
    job: dict[str, Any],
    output: Any,
    line: str,
    cursor: int,
    live: bool,
) -> tuple[str, bool]:
    cursor_up = max(1, int(job.pop("terminal_cursor_up")))
    current_index = len(output) - 1 if live else len(output)
    target_index = current_index - cursor_up
    if target_index < 0:
        output.clear()
        line = ""
    else:
        line = str(output[target_index])[:cursor]
        while len(output) > target_index:
            output.pop()
        if line:
            output.append(line)
    live = bool(line)
    job["last_log_line_blank"] = bool(output and output[-1] == "")
    job.pop("last_log_line_value", None)
    job.pop("last_log_line_repeats", None)
    return line, live


def append_job_output_stream_locked(job: dict[str, Any], text: str) -> None:
    output = job.setdefault("output", deque(maxlen=1000))
    line = str(job.get("partial_output", ""))
    cursor = max(0, int(job.get("terminal_cursor_column", len(line))))
    live = bool(job.get("partial_live", False))
    text = str(job.pop("terminal_escape", "")) + text

    def set_live(value: str) -> None:
        nonlocal live
        if live and output:
            output[-1] = value
        else:
            output.append(value)
            live = True
        job["last_log_line_blank"] = value == ""

    def render_line() -> None:
        nonlocal live
        clean_line = sanitize_log_line(line)
        if clean_line:
            set_live(clean_line)
        elif live:
            if output:
                output.pop()
            live = False
            job["last_log_line_blank"] = bool(output and output[-1] == "")

    def csi_mode(params: str) -> int:
        first_param = params.split(";", 1)[0]
        return int(first_param) if first_param.isdigit() else 0

    index = 0
    while index < len(text):
        char = text[index]
        if char == "\x1b" and index + 1 >= len(text):
            job["terminal_escape"] = text[index:]
            break
        if char == "\x1b" and text[index + 1] == "[":
            match = re.match(r"\x1b\[([0-?]*)([ -/]*)([@-~])", text[index:])
            if match is None:
                sequence_end = index + 2
                while sequence_end < len(text) and "0" <= text[sequence_end] <= "?":
                    sequence_end += 1
                while sequence_end < len(text) and " " <= text[sequence_end] <= "/":
                    sequence_end += 1
                if sequence_end == len(text):
                    pending_escape = text[index:]
                    if len(pending_escape) <= TERMINAL_ESCAPE_MAX_LENGTH:
                        job["terminal_escape"] = pending_escape
                    break
                if text[sequence_end] == "\r":
                    # A control byte cannot finish CSI. Recover at the next
                    # progress frame instead of buffering subsequent output.
                    line = ""
                    cursor = 0
                    render_line()
                index = sequence_end
                continue
            params, _intermediate, final = match.groups()
            if final == "A":
                first_param = params.split(";", 1)[0]
                cursor_up = int(first_param) if first_param.isdigit() else 1
                job["terminal_cursor_up"] = int(job.get("terminal_cursor_up", 0)) + max(1, cursor_up)
            elif final == "J":
                mode = csi_mode(params)
                rewound = "terminal_cursor_up" in job
                if mode == 0 and rewound:
                    line, live = erase_rewound_display_tail_locked(job, output, line, cursor, live)
                else:
                    job.pop("terminal_cursor_up", None)
                if mode == 1 and not rewound:
                    output.clear()
                    erased = min(cursor + 1, len(line))
                    line = (" " * erased) + line[erased:]
                elif mode == 2:
                    output.clear()
                    line = ""
                elif mode == 0 and not rewound:
                    line = line[:cursor]
                render_line()
            elif final == "K":
                job.pop("terminal_cursor_up", None)
                mode = csi_mode(params)
                if mode == 1:
                    erased = min(cursor + 1, len(line))
                    line = (" " * erased) + line[erased:]
                elif mode == 2:
                    line = ""
                else:
                    line = line[:cursor]
                render_line()
            elif final != "m":
                job.pop("terminal_cursor_up", None)
            index += match.end()
            continue
        if char == "\r":
            job.pop("terminal_cursor_up", None)
            cursor = 0
            index += 1
            continue
        if char == "\n":
            job.pop("terminal_cursor_up", None)
            if live and output:
                completed = output.pop()
                live = False
                append_log_line_locked(job, output, completed)
            elif line:
                append_log_line_locked(job, output, sanitize_log_line(line))
            else:
                append_log_line_locked(job, output, "")
            line = ""
            cursor = 0
            index += 1
            continue
        job.pop("terminal_cursor_up", None)
        if cursor > len(line):
            line += " " * (cursor - len(line))
        if cursor == len(line):
            line += char
        else:
            line = line[:cursor] + char + line[cursor + 1 :]
        cursor += 1
        render_line()
        index += 1
    job["partial_output"] = line
    job["partial_live"] = live
    job["terminal_cursor_column"] = cursor
    if text:
        job["output_revision"] = int(job.get("output_revision", 0)) + 1
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
            decoded = chunk.decode(errors="replace")
            revision_before = int(job.get("output_revision", 0))
            append_job_output_stream(job, decoded)
            if job.get("current_stop_mode") == STOP_MODE_PTY_INTERRUPT:
                trace_job_event(
                    job,
                    "pty-chunk",
                    bytes=len(chunk),
                    carriage_returns=decoded.count("\r"),
                    newlines=decoded.count("\n"),
                    escapes=decoded.count("\x1b"),
                    revision_before=revision_before,
                    revision_after=int(job.get("output_revision", 0)),
                    screen_lines=len(job.get("output", [])),
                    tail=decoded[-160:],
                )
            if mark_dirty is not None:
                mark_dirty()
    finally:
        try:
            stdout.close()
        except Exception:
            pass
        wait = getattr(process, "wait", None)
        if callable(wait):
            wait()
        if job.get("current_stop_mode") == STOP_MODE_PTY_INTERRUPT:
            trace_job_event(
                job,
                "pty-eof",
                returncode=getattr(process, "returncode", None),
                revision=int(job.get("output_revision", 0)),
                screen_lines=len(job.get("output", [])),
            )
        process_finished = job.get("process_finished")
        if callable(process_finished):
            process_finished()


def start_command_process(
    job: dict[str, Any],
    command: list[str],
    mark_dirty: Callable[[], None] | None = None,
) -> Any:
    pty_interrupt = (
        bool(command)
        and os.path.basename(command[0]) == "ssh"
        and any(
            argument.startswith("-") and argument[1:] and set(argument[1:]) == {"t"}
            for argument in command[1:]
        )
    )
    job["current_stop_mode"] = STOP_MODE_PTY_INTERRUPT if pty_interrupt else None
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE if pty_interrupt else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    job["process"] = process
    if pty_interrupt:
        trace_job_event(job, "pty-start", pid=getattr(process, "pid", None))
    reader = threading.Thread(target=read_process_output_stream, args=(process, job, mark_dirty), daemon=True)
    job["output_reader"] = reader
    reader.start()
    return process


def send_process_interrupt(process: Any) -> bool:
    stream = getattr(process, "stdin", None)
    if stream is None:
        return False
    try:
        stream.write(b"\x03")
        stream.flush()
    except (BrokenPipeError, OSError, ValueError):
        return False
    return True
