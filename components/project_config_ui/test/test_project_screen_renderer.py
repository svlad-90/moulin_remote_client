from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from components.project_config_ui.api import project_screen_renderer
from components.project_config_ui.api import project_screen_state


class FakeRenderPort:
    def __init__(self) -> None:
        self.status = "ready"
        self.connection_state = "disconnected"
        self.rows: list[tuple[int, int, str, int | None]] = []
        self.boxes: list[tuple[int, int, int, int, str]] = []
        self.wrapped: list[str] = []

    def add(self, row: int, col: int, text: str, attr: int | None = None) -> None:
        self.rows.append((row, col, text, attr))

    def draw_box(self, top: int, left: int, height: int, width: int, title: str) -> None:
        self.boxes.append((top, left, height, width, title))

    def draw_wrapped(self, _row: int, _col: int, _width: int, text: str, _attr: int = 0, *, max_lines: int = 3) -> int:
        self.wrapped.append(text)
        return 1

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
        "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
        "active_remote": "build",
        "active_project": "prod",
        "projects": [{"name": "prod", "label": "Prod", "project_dir": "meta-product"}],
    }


class ProjectScreenRendererTests(unittest.TestCase):
    def test_render_returns_projects_fields_and_selected_project(self) -> None:
        cfg = config()
        port = FakeRenderPort()
        state = project_screen_state.ProjectScreenStateController(cfg)
        renderer = project_screen_renderer.ProjectScreenRenderer(
            cfg,
            app_dir=Path("/app"),
            project_fields_factory=lambda _params: [{"label": "Display label", "key": "label", "kind": "text"}],
        )

        result = renderer.render(port, height=30, width=120, params=[], screen_state=state)

        self.assertEqual(result.selected_project, cfg["projects"][0])
        self.assertEqual(result.projects, cfg["projects"])
        self.assertEqual(result.fields, [{"label": "Display label", "key": "label", "kind": "text"}])
        self.assertEqual(port.boxes, [(3, 0, 24, 120, "Projects")])
        self.assertTrue(any("Active: Prod" in row[2] for row in port.rows))

    def test_render_reports_inline_edit_cursor_position(self) -> None:
        cfg = config()
        port = FakeRenderPort()
        state = project_screen_state.ProjectScreenStateController(cfg)
        state.state.project_index_initialized = True
        state.state.focus = "fields"
        state.begin_inline_edit("label", "Prod")
        renderer = project_screen_renderer.ProjectScreenRenderer(
            cfg,
            app_dir=Path("/app"),
            project_fields_factory=lambda _params: [{"label": "Display label", "key": "label", "kind": "text"}],
        )

        result = renderer.render(port, height=30, width=120, params=[], screen_state=state)

        self.assertIsNotNone(result.editing_cursor_yx)
        self.assertTrue(any("Enter: save" in row[2] for row in port.rows))


if __name__ == "__main__":
    unittest.main()
