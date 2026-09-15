"""Terminal layout calculation helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MainLayout:
    height: int
    width: int
    left_width: int
    right_left: int
    right_width: int
    panel_top: int
    panel_height: int
    details_height: int
    logs_height: int
    logs_top: int

    def signature(self) -> tuple[int, int, int, int, int, int, int, int, int, int]:
        return (
            self.height,
            self.width,
            self.left_width,
            self.right_left,
            self.right_width,
            self.panel_top,
            self.panel_height,
            self.details_height,
            self.logs_height,
            self.logs_top,
        )


@dataclass(frozen=True)
class LabelValueLayout:
    label_text: str
    label_width: int
    value_x: int
    value_width: int


def main_layout(height: int, width: int) -> MainLayout:
    left_width = min(46, max(34, width // 3))
    right_left = left_width + 1
    right_width = width - right_left
    panel_top = 11
    panel_height = height - 13
    details_height = max(8, panel_height // 2)
    logs_height = max(5, panel_height - details_height - 1)
    logs_top = panel_top + details_height + 1
    return MainLayout(
        height=height,
        width=width,
        left_width=left_width,
        right_left=right_left,
        right_width=right_width,
        panel_top=panel_top,
        panel_height=panel_height,
        details_height=details_height,
        logs_height=logs_height,
        logs_top=logs_top,
    )


def label_value_layout(x: int, width: int, label: str) -> LabelValueLayout:
    label_text = f"{label}:"
    label_width = min(14, max(8, len(label_text) + 1))
    value_x = x + label_width
    value_width = max(1, width - label_width)
    return LabelValueLayout(
        label_text=label_text,
        label_width=label_width,
        value_x=value_x,
        value_width=value_width,
    )


def scrollbar_thumb(top: int, height: int, total: int, visible: int, scroll: int) -> tuple[int, int] | None:
    if height <= 0 or total <= visible:
        return None
    thumb_height = max(1, int(height * visible / max(total, 1)))
    thumb_top = top + int((height - thumb_height) * scroll / max(total - visible, 1))
    return thumb_top, thumb_height
