"""Dialog content and layout helpers."""

from __future__ import annotations

from dataclasses import dataclass

from components.ui.src import input as ui_input


STOP_ACTION_LABELS = {"Stop running command", "Stop board command"}


@dataclass(frozen=True)
class ConfirmContent:
    title: str
    warning: str
    subject: str
    details: str
    footer: str


@dataclass(frozen=True)
class ConfirmLayout:
    top: int
    left: int
    width: int
    height: int
    inner_width: int
    content_x: int
    content_y: int


def action_confirm_content(label: str, description: str) -> ConfirmContent:
    if label in STOP_ACTION_LABELS:
        return ConfirmContent(
            title="Confirm",
            warning="Stop the active command?",
            subject=label,
            details="SIGTERM is sent first; if the process does not exit, SIGKILL is sent after a short timeout.",
            footer="Enter/y: stop | n/q/Esc: cancel",
        )
    return ConfirmContent(
        title="Confirm",
        warning="This action can change local or remote build state.",
        subject=label,
        details=description,
        footer="Enter/y: run | n/q/Esc: cancel",
    )


def exit_confirm_content() -> ConfirmContent:
    return ConfirmContent(
        title="Exit",
        warning="Leave the Moulin client?",
        subject="No remote process is stopped by exiting the menu.",
        details="If a command was started from this screen, it is stopped only from its command screen.",
        footer="Enter/y: exit | n/q/Esc: stay",
    )


def disconnect_confirm_content(title: str, subject: str) -> ConfirmContent:
    return ConfirmContent(
        title=title,
        warning="Disconnect the active host profile?",
        subject=subject,
        details="Running commands are not stopped by disconnect. Use Stop running command first if needed.",
        footer="Enter/y: disconnect | n/q/Esc: cancel",
    )


def confirm_key_result(text: str, ch: int) -> bool | None:
    if ui_input.key_matches_text(text, "y") or ch in (10, 13):
        return True
    if ui_input.key_matches_text(text, "n", "q") or ch in (27, 3):
        return False
    return None


def confirm_layout(screen_height: int, screen_width: int) -> ConfirmLayout:
    box_width = min(max(64, screen_width // 2), screen_width - 4)
    box_height = 10
    top = max(1, (screen_height - box_height) // 2)
    left = max(1, (screen_width - box_width) // 2)
    return ConfirmLayout(
        top=top,
        left=left,
        width=box_width,
        height=box_height,
        inner_width=box_width - 4,
        content_x=left + 2,
        content_y=top + 2,
    )


def close_confirm_flags() -> dict[str, bool]:
    return {
        "main_full_redraw": True,
        "menu_dirty": True,
        "logs_dirty": True,
    }
