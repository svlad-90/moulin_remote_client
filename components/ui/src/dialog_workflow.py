"""Interactive dialog workflow controller."""

from __future__ import annotations

import curses
from typing import Any

from components.ui.api import dialogs as ui_dialog_api
from components.ui.api import input as ui_input_api
from components.ui.api import session as ui_session_api


class DialogWorkflowController:
    """Run blocking prompt/message/confirmation workflows for the TUI."""

    def run_confirm_dialog(
        self,
        port: Any,
        content: ui_dialog_api.ConfirmContent,
        *,
        redraw_background: bool = True,
    ) -> bool:
        port.screen.timeout(-1)
        self.draw_confirm(
            port,
            content.title,
            content.warning,
            content.subject,
            content.details,
            content.footer,
            redraw_background=redraw_background,
        )
        while True:
            ch = port.read_key()
            result = ui_dialog_api.confirm_key_result(ui_input_api.key_code_to_text(ch), ch)
            if result is True:
                self.close_confirm(port)
                return True
            if result is False:
                self.close_confirm(port)
                return False

    def confirm_sync_action(self, port: Any, label: str, description: str) -> bool:
        return self.run_confirm_dialog(
            port,
            ui_dialog_api.ConfirmContent(
                title="Confirm",
                warning="This action can change local or remote mapped files.",
                subject=label,
                details=description,
                footer="Enter/y: run | n/q/Esc: cancel",
            ),
            redraw_background=False,
        )

    def close_confirm(self, port: Any) -> None:
        port.screen.timeout(250)
        ui_session_api.apply_state(port, ui_dialog_api.close_confirm_flags())
        port.render_cache.clear()

    def draw_confirm(
        self,
        port: Any,
        title: str,
        warning: str,
        subject: str,
        details: str,
        footer: str,
        *,
        redraw_background: bool = True,
    ) -> None:
        height, width = port.screen.getmaxyx()
        layout = ui_dialog_api.confirm_layout(height, width)
        if redraw_background:
            port.draw()
        port.draw_box(layout.top, layout.left, layout.height, layout.width, title)
        x = layout.content_x
        y = layout.content_y
        inner = layout.inner_width
        port.add(y, x, warning[:inner], port.warn_attr())
        y += 2
        port.add(y, x, subject[:inner], curses.A_BOLD)
        y += 1
        port.draw_wrapped(y, x, inner, details, max_lines=3)
        port.add(layout.top + layout.height - 2, x, footer[:inner], port.accent_attr())
        port.screen.refresh()

    def wait_message(self, port: Any, message: str) -> None:
        height, width = port.screen.getmaxyx()
        port.add(height - 1, 0, message[:width].ljust(width), curses.A_REVERSE)
        port.screen.timeout(-1)
        while True:
            ch = port.read_key()
            if ui_input_api.key_code_matches(ch, "q") or ch in (27, 10, 13):
                return

    def show_message(self, port: Any, title: str, lines: list[str]) -> None:
        port.screen.erase()
        height, width = port.screen.getmaxyx()
        port.add(0, 0, title[:width], curses.A_BOLD)
        for index, line in enumerate(lines[: max(0, height - 3)]):
            attr = port.warn_attr() if index == 0 else 0
            port.add(index + 2, 0, line[:width], attr)
        port.add(height - 2, 0, "q/Esc/Enter: return to menu"[:width], port.accent_attr())
        port.screen.refresh()
        self.wait_message(port, "q/Esc/Enter: return to menu")
        port.screen.timeout(250)

    def prompt(self, port: Any, label: str, current: str) -> str:
        value = current
        cursor = len(value)
        port.prompt_cancelled = False
        port.set_cursor(True)
        height, width = port.screen.getmaxyx()
        row = height - 2
        prompt = ui_input_api.prompt_render(label, current, width)
        try:
            while True:
                self.draw_prompt(port, row, width, prompt, value, cursor)
                ch = port.read_key()
                edit = ui_input_api.inline_edit_key_action(value, cursor, ch)
                if edit.action == "noop":
                    edit = ui_input_api.inline_edit_key_action(value, cursor, ch, port.read_queued_text(ch))
                if edit.action == "save":
                    return ui_input_api.prompt_value_or_current(value, current)
                if edit.action == "cancel":
                    port.prompt_cancelled = True
                    return ""
                if edit.action == "edit":
                    value = edit.value
                    cursor = edit.cursor
        finally:
            port.set_cursor(False)

    def draw_prompt(
        self,
        port: Any,
        row: int,
        width: int,
        prompt: ui_input_api.PromptRender,
        value: str,
        cursor: int,
    ) -> None:
        visible_width = max(0, width - 1)
        input_x = max(0, min(prompt.input_x, visible_width))
        input_width = max(0, visible_width - input_x)
        cursor = min(max(0, cursor), len(value))
        start = max(0, cursor - input_width + 1) if input_width else cursor
        visible_value = value[start : start + input_width]
        port.add(row, 0, prompt.clear_text)
        port.add(row, 0, prompt.visible_prompt)
        if input_width:
            port.add(row, input_x, visible_value[:input_width])
        try:
            port.screen.move(row, min(input_x + cursor - start, max(0, width - 1)))
        except curses.error:
            pass
        port.screen.refresh()


def dialog_workflow_controller() -> DialogWorkflowController:
    return DialogWorkflowController()
