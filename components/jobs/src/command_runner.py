"""Command sequence runner service."""

from __future__ import annotations

from typing import Any, Callable

from components.jobs.api import jobs as job_api
from components.ui.api import menu as ui_menu_api
from components.ui.api import session as ui_session_api


class CommandRunnerService:
    """Own the UI workflow for starting a command sequence."""

    def start_commands(
        self,
        port: Any,
        title: str,
        commands: list[list[str]],
        *,
        start_next_command: Callable[[dict[str, Any]], None],
    ) -> int:
        item = port.items[port.selected]
        slot = ui_menu_api.item_job_slot(item)
        plan = job_api.build_command_start_plan(
            title=title,
            item_label=item.label,
            slot=slot,
            commands=commands,
            action_running=port.action_running,
            active_job=port.active_job,
            board_job=port.board_job,
        )
        if int(plan["rc"]) != 0:
            port.status = str(plan["status"])
            return int(plan["rc"])

        job = plan["job"]
        if plan["slot"] == "board":
            port.board_job = job
        else:
            port.active_job = job
        start_next_command(job)
        ui_session_api.apply_state(port, plan["state"])
        return 0


def command_runner_service() -> CommandRunnerService:
    return CommandRunnerService()
