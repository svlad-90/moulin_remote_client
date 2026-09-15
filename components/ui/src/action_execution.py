"""Selected menu action execution controller."""

from __future__ import annotations

from typing import Any, Callable

from components.jobs.api import jobs as job_api
from components.ui.api import dialogs as ui_dialog_api
from components.ui.api import menu as ui_menu_api


class ActionExecutionController:
    """Run the currently selected menu action through the TUI workflow."""

    def __init__(
        self,
        *,
        confirm_dialog: Callable[[Any], bool],
        show_message: Callable[[str, list[str]], None],
        refresh_after_action: Callable[[], None],
    ) -> None:
        self.confirm_dialog = confirm_dialog
        self.show_message = show_message
        self.refresh_after_action = refresh_after_action

    def run_selected(self, port: Any) -> None:
        item = port.items[port.selected]
        plan = ui_menu_api.selected_action_plan(
            item,
            job_api.running_job_list(port.active_job, port.board_job),
            action_running=port.action_running,
            enabled_for_item=port.item_enabled,
            disabled_reason_for_item=port.disabled_reason,
        )
        guard = plan["guard"]
        if not guard["allowed"]:
            port.status = str(guard["status"])
            return
        if item.confirm and not self.confirm_dialog(ui_dialog_api.action_confirm_content(item.label, item.description)):
            port.status = f"Cancelled: {item.label}"
            return
        try:
            item.handler(port)
        except SystemExit as exc:
            self._show_action_failed(port, item.label, exc)
        except Exception as exc:
            self._show_action_failed(port, item.label, exc)
        finally:
            self.refresh_after_action()
            port.menu_dirty = True
            port.main_full_redraw = True
            port.logs_dirty = True

    def _show_action_failed(self, port: Any, item_label: str, exc: BaseException) -> None:
        port.status = f"{item_label}: failed"
        self.show_message("Action failed", [str(exc)])


def action_execution_controller(
    *,
    confirm_dialog: Callable[[Any], bool],
    show_message: Callable[[str, list[str]], None],
    refresh_after_action: Callable[[], None],
) -> ActionExecutionController:
    return ActionExecutionController(
        confirm_dialog=confirm_dialog,
        show_message=show_message,
        refresh_after_action=refresh_after_action,
    )
