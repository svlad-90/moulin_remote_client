from __future__ import annotations

import unittest
from typing import Any

from components.host_config_ui.api import remote_screen_renderer
from components.host_config_ui.api import remote_screen_state


class FakeRenderPort:
    def __init__(self) -> None:
        self.status = "ready"
        self.connection_state = "disconnected"
        self.rows: list[tuple[int, int, str, int | None]] = []
        self.boxes: list[tuple[int, int, int, int, str]] = []

    def add(self, row: int, col: int, text: str, attr: int | None = None) -> None:
        self.rows.append((row, col, text, attr))

    def draw_box(self, top: int, left: int, height: int, width: int, title: str) -> None:
        self.boxes.append((top, left, height, width, title))

    def selected_active_attr(self) -> int:
        return 1

    def selected_attr(self) -> int:
        return 2

    def active_row_attr(self) -> int:
        return 3

    def accent_attr(self) -> int:
        return 4

    def disabled_attr(self) -> int:
        return 5

    def editing_attr(self) -> int:
        return 6

    def selected_disabled_attr(self) -> int:
        return 7


def config() -> dict[str, Any]:
    return {
        "active_remote": "build-a",
        "remotes": [
            {"name": "build-a", "label": "Build A", "user": "user", "host": "10.0.0.1"},
        ],
    }


class RemoteScreenRendererTests(unittest.TestCase):
    def test_render_returns_remotes_fields_and_selected_remote(self) -> None:
        cfg = config()
        port = FakeRenderPort()
        state = remote_screen_state.RemoteScreenStateController(cfg)
        renderer = remote_screen_renderer.RemoteScreenRenderer(
            cfg,
            remote_fields_factory=lambda: [("Display label", "label")],
        )

        result = renderer.render(port, height=30, width=120, screen_state=state)

        self.assertEqual(result.selected_remote, cfg["remotes"][0])
        self.assertEqual(result.remotes, cfg["remotes"])
        self.assertEqual(result.fields, [("Display label", "label")])
        self.assertEqual(port.boxes, [(3, 0, 24, 120, "Build hosts")])
        self.assertTrue(any("Active: build-a" in row[2] for row in port.rows))

    def test_render_reports_inline_edit_cursor_position(self) -> None:
        cfg = config()
        port = FakeRenderPort()
        state = remote_screen_state.RemoteScreenStateController(cfg)
        state.state.remote_index_initialized = True
        state.state.focus = "fields"
        state.begin_inline_edit("label", "Build A")
        renderer = remote_screen_renderer.RemoteScreenRenderer(
            cfg,
            remote_fields_factory=lambda: [("Display label", "label")],
        )

        result = renderer.render(port, height=30, width=120, screen_state=state)

        self.assertIsNotNone(result.editing_cursor_yx)
        self.assertTrue(any("Enter: save" in row[2] for row in port.rows))


if __name__ == "__main__":
    unittest.main()
