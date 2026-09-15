from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from components.ui.api import main_draw
from components.ui.api.menu import MenuItem


class FakeScreen:
    def __init__(self, *, height: int = 30, width: int = 120) -> None:
        self.height = height
        self.width = width
        self.erase_count = 0
        self.refresh_count = 0

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def erase(self) -> None:
        self.erase_count += 1

    def refresh(self) -> None:
        self.refresh_count += 1


class FakePanels:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def draw_header(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls.append("header")

    def draw_actions_panel(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls.append("actions")

    def draw_details_panel(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls.append("details")

    def draw_logs_panel(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls.append("logs")

    def draw_footer(self, *_args: Any, **_kwargs: Any) -> str:
        self.calls.append("footer")
        return "footer"

    def draw_expanded_logs(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls.append("expanded")


class FakePort:
    def __init__(self, *, height: int = 30, width: int = 120) -> None:
        self.screen = FakeScreen(height=height, width=width)
        self.config = {
            "remote": {"label": "Build", "user": "builder", "host": "10.0.0.1", "project_dir": "/mnt/proj"},
            "board_host": {"label": "Board", "user": "tester", "host": "10.0.0.2"},
            "local": {"project_dir": "/tmp/local"},
            "moulin": {"manifest": "product.yaml"},
        }
        self.items = [MenuItem("Run product build", "build", "Build it", lambda _app: "preview", lambda _app: None)]
        self.selected = 0
        self.menu_scroll = 0
        self.menu_dirty = False
        self.main_full_redraw = True
        self.render_cache: dict[str, Any] = {}
        self.connection_state = "connected"
        self.board_connection_state = "connected"
        self.active_job: dict[str, Any] | None = None
        self.board_job: dict[str, Any] | None = None
        self.last_job: dict[str, Any] | None = None
        self.last_board_job: dict[str, Any] | None = None
        self.logs_expanded = False
        self.logs_dirty = True
        self.last_log_render_at = 0.0
        self.focus_panel = "actions"
        self.log_scroll = 0
        self.log_follow = True
        self.status = "Ready"
        self.build_params: dict[str, str] = {}
        self.docker_image = ""
        self.build_targets = ""
        self.preflight = ""
        self.mapping_selection_cache: list[str] = []
        self.last_exit: int | None = None
        self.rows: list[tuple[int, int, str, int]] = []
        self.profile_events: list[str] = []
        self.build_items_calls = 0

    def setup_colors(self) -> None:
        return None

    def add(self, y: int, x: int, text: str, attr: int = 0) -> None:
        self.rows.append((y, x, text, attr))

    def warn_attr(self) -> int:
        return 1

    def item_enabled(self, _item: MenuItem) -> bool:
        return True

    def disabled_reason(self, _item: MenuItem) -> str:
        return ""

    def build_items(self) -> list[MenuItem]:
        self.build_items_calls += 1
        return self.items

    def mapping_status_snapshot(self) -> dict[str, str]:
        return {"text": "none", "role": "disabled"}

    def ui_profile_slow(self, event: str, _started: float, **_fields: Any) -> float:
        self.profile_events.append(event)
        return _started


class MainDrawControllerTests(unittest.TestCase):
    def test_small_terminal_draws_warning_without_panels(self) -> None:
        port = FakePort(height=10, width=40)
        panels = FakePanels()

        with patch("components.ui.src.main_draw.ui_panels_api.main_panels_controller", return_value=panels):
            main_draw.main_draw_controller(app_dir=Path("/app")).draw(port)

        self.assertEqual(panels.calls, [])
        self.assertEqual(port.screen.erase_count, 1)
        self.assertTrue(port.main_full_redraw)
        self.assertTrue(any("Terminal is too small" in row[2] for row in port.rows))

    def test_full_draw_renders_all_main_panels_and_caches_layout(self) -> None:
        port = FakePort()
        panels = FakePanels()

        with patch("components.ui.src.main_draw.ui_panels_api.main_panels_controller", return_value=panels):
            main_draw.main_draw_controller(app_dir=Path("/app")).draw(port)

        self.assertEqual(panels.calls, ["header", "actions", "details", "logs", "footer"])
        self.assertIn("layout", port.render_cache)
        self.assertFalse(port.main_full_redraw)
        self.assertFalse(port.logs_dirty)
        self.assertEqual(port.screen.refresh_count, 1)

    def test_expanded_logs_draws_only_expanded_panel(self) -> None:
        port = FakePort()
        port.logs_expanded = True
        panels = FakePanels()

        with patch("components.ui.src.main_draw.ui_panels_api.main_panels_controller", return_value=panels):
            main_draw.main_draw_controller(app_dir=Path("/app")).draw(port)

        self.assertEqual(panels.calls, ["expanded"])
        self.assertFalse(port.logs_dirty)
        self.assertEqual(port.screen.refresh_count, 1)


if __name__ == "__main__":
    unittest.main()
