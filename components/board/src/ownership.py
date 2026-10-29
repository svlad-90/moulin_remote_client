"""Non-blocking board ownership status monitoring."""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Callable

from components.board.api import builder as board_builder_api
from components.config.api import accessors as config_accessors
from components.config.api import profiles as config_profiles


OWNERSHIP_ACTION_LABELS = {"Acquire board", "Release board"}


def parse_ownership_status(output: str) -> dict[str, str]:
    """Normalize a configured status command result into a generic state."""
    payload: dict[str, Any] | None = None
    for line in reversed(output.splitlines()):
        try:
            candidate = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    if payload is not None:
        owner = str(payload.get("owner") or "").strip()
        user = str(payload.get("user") or "").strip()
        if not owner:
            return {"state": "free", "text": "free", "owner": ""}
        owner_user = owner.rsplit("/", 1)[-1]
        if user and owner_user == user:
            return {"state": "owned", "text": "acquired by you", "owner": owner}
        return {"state": "busy", "text": f"acquired by {owner}", "owner": owner}

    token = output.strip().lower().splitlines()[-1:] or [""]
    value = token[0]
    if value in {"free", "available", "unowned"}:
        return {"state": "free", "text": "free", "owner": ""}
    if value in {"owned", "acquired", "yours"}:
        return {"state": "owned", "text": "acquired by you", "owner": ""}
    if value == "busy":
        return {"state": "busy", "text": "acquired by another user", "owner": ""}
    raise ValueError("ownership status command returned an unsupported result")


class BoardOwnershipMonitor:
    """Poll the configured ownership status without blocking the TUI."""

    def __init__(
        self,
        *,
        capture_command: Callable[..., str],
        monotonic: Callable[[], float] = time.monotonic,
        interval_seconds: float = 5.0,
    ) -> None:
        self.capture_command = capture_command
        self.monotonic = monotonic
        self.interval_seconds = interval_seconds
        self.command_builder = board_builder_api.board_command_builder()

    def poll(self, port: Any) -> None:
        identity, command = self._status_command(port.config)
        if identity != getattr(port, "board_ownership_identity", ""):
            port.board_ownership_identity = identity
            port.board_ownership_task = None
            port.board_ownership_next_poll = 0.0
            self._set_status(port, self._initial_status(command))
        if not command:
            return
        if getattr(port, "board_connection_state", "") != "connected":
            port.board_ownership_task = None
            self._set_status(port, {"state": "unknown", "text": "unknown", "owner": ""})
            return

        self._notice_completed_action(port)
        task = getattr(port, "board_ownership_task", None)
        if isinstance(task, dict):
            self._poll_task(port, task, identity)
            return
        if getattr(port, "board_job", None) is not None:
            return
        if self.monotonic() < float(getattr(port, "board_ownership_next_poll", 0.0)):
            return
        self._start_task(port, identity, command)

    def _status_command(self, config: dict[str, Any]) -> tuple[str, list[str] | None]:
        target = config_profiles.board_target(config)
        commands = target.get("commands")
        if not isinstance(commands, dict):
            return "", None
        acquire = str(commands.get("ownership_acquire", "")).strip()
        release = str(commands.get("ownership_release", "")).strip()
        status = str(commands.get("ownership_status", "")).strip()
        if not acquire or not release or not status:
            return "", None
        board_id = str(target.get("name") or target.get("id") or "")
        board_host = config_accessors.board_host_spec_for_config(config)
        identity = "\0".join((board_id, board_host, status))
        return identity, self.command_builder.board_ssh_command(board_host, status)

    def _initial_status(self, command: list[str] | None) -> dict[str, str]:
        if command is None:
            return {"state": "disabled", "text": "", "owner": ""}
        return {"state": "unknown", "text": "unknown", "owner": ""}

    def _start_task(self, port: Any, identity: str, command: list[str]) -> None:
        results: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()

        def query() -> None:
            try:
                output = self.capture_command(command, echo=False, timeout=12)
                results.put(("ok", parse_ownership_status(output)))
            except Exception as exc:
                results.put(("error", exc))

        thread = threading.Thread(target=query, name="moulin-board-ownership", daemon=True)
        port.board_ownership_task = {
            "identity": identity,
            "results": results,
            "thread": thread,
        }
        if getattr(port, "board_ownership_status", {}).get("state") == "unknown":
            self._set_status(port, {"state": "checking", "text": "checking...", "owner": ""})
        thread.start()

    def _poll_task(self, port: Any, task: dict[str, Any], identity: str) -> None:
        try:
            outcome, value = task["results"].get_nowait()
        except queue.Empty:
            return
        if task is not getattr(port, "board_ownership_task", None):
            return
        port.board_ownership_task = None
        port.board_ownership_next_poll = self.monotonic() + self.interval_seconds
        if task["identity"] != identity:
            return
        if outcome == "ok":
            self._set_status(port, value)
        else:
            self._set_status(
                port,
                {"state": "error", "text": "status unavailable", "owner": "", "detail": str(value)},
            )

    def _notice_completed_action(self, port: Any) -> None:
        job = getattr(port, "last_board_job", None)
        if not isinstance(job, dict) or job.get("item_label") not in OWNERSHIP_ACTION_LABELS:
            return
        marker = id(job)
        if marker == getattr(port, "board_ownership_last_job", None):
            return
        port.board_ownership_last_job = marker
        port.board_ownership_next_poll = 0.0

    def _set_status(self, port: Any, status: dict[str, str]) -> None:
        if status == getattr(port, "board_ownership_status", None):
            return
        port.board_ownership_status = status
        self._refresh_menu(port)
        port.menu_dirty = True
        port.main_full_redraw = True
        render_cache = getattr(port, "render_cache", None)
        if isinstance(render_cache, dict):
            render_cache.pop("header", None)

    def _refresh_menu(self, port: Any) -> None:
        build_items = getattr(port, "build_items", None)
        items = getattr(port, "items", None)
        if not callable(build_items) or not isinstance(items, list):
            return
        selected = int(getattr(port, "selected", 0))
        selected_item = items[selected] if 0 <= selected < len(items) else None
        selected_key = (
            str(getattr(selected_item, "group", "")),
            str(getattr(selected_item, "label", "")),
        )
        new_items = build_items()
        port.items = new_items
        for index, item in enumerate(new_items):
            if (str(getattr(item, "group", "")), str(getattr(item, "label", ""))) == selected_key:
                port.selected = index
                return
        port.selected = min(selected, max(0, len(new_items) - 1))


def board_ownership_monitor(*, capture_command: Callable[..., str]) -> BoardOwnershipMonitor:
    return BoardOwnershipMonitor(capture_command=capture_command)
