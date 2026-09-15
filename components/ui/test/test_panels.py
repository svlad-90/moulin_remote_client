from __future__ import annotations

import unittest
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from components.ui.api import panels


@dataclass
class FakeMenuItem:
    label: str
    description: str


class FakeScreen:
    def __init__(self, *, height: int = 30, width: int = 120) -> None:
        self.height = height
        self.width = width
        self.erased = False

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def erase(self) -> None:
        self.erased = True


class FakePanelPort:
    def __init__(self) -> None:
        self.config = {
            "ui": {"title": "Moulin Client"},
            "inventory": {"mapping_selection": "/tmp/mapping-selection.txt"},
            "local": {"project_dir": "/tmp/overlay"},
            "remote": {
                "name": "build",
                "label": "Build",
                "user": "builder",
                "host": "10.0.0.1",
                "project_dir": "/mnt/projects/prod",
            },
            "board_host": {"name": "board", "label": "Board", "user": "tester", "host": "10.0.0.2"},
            "active_project": "prod",
            "projects": [{"name": "prod", "moulin_manifest": "product.yaml", "local_project_dir": "/tmp/overlay"}],
        }
        self.screen = FakeScreen()
        self.items = [FakeMenuItem("Run product build", "Build selected targets.")]
        self.selected = 0
        self.menu_scroll = 0
        self.active_job: dict[str, Any] | None = None
        self.board_job: dict[str, Any] | None = None
        self.last_job: dict[str, Any] | None = None
        self.last_board_job: dict[str, Any] | None = None
        self.logs_expanded = False
        self.log_follow = True
        self.log_scroll = 0
        self.status = ""
        self.focus_panel = "logs"
        self.connection_state = "connected"
        self.board_connection_state = "connected"
        self.build_params = {"ENABLE_ANDROID": "yes"}
        self.docker_image = "image"
        self.build_targets = "full_ufs.img.gz"
        self.preflight = "ssh ok"
        self.mapping_selection_cache = ["meta"]
        self.last_exit: int | None = 0
        self.rows: list[tuple[int, int, str, int | None]] = []
        self.boxes: list[tuple[int, int, int, int, str, int | None]] = []

    def add(self, row: int, col: int, text: str, attr: int | None = None) -> None:
        self.rows.append((row, col, text, attr))

    def add_segments(self, row: int, col: int, _width: int, segments: list[tuple[str, int]]) -> None:
        self.rows.append((row, col, "".join(text for text, _attr in segments), None))

    def draw_box(self, top: int, left: int, height: int, width: int, title: str, attr: int | None = None) -> None:
        self.boxes.append((top, left, height, width, title, attr))

    def draw_wrapped(self, row: int, _x: int, _width: int, _text: str, *, max_lines: int = 3) -> int:
        return row + min(max_lines, 1)

    def running_attr(self) -> int:
        return 1

    def group_attr(self) -> int:
        return 2

    def disabled_attr(self) -> int:
        return 3

    def accent_attr(self) -> int:
        return 4

    def selected_attr(self) -> int:
        return 6

    def connection_attr_for(self, _state: str) -> int:
        return 7

    def role_attr(self, _role: str) -> int:
        return 5

    def item_enabled(self, _item: Any) -> bool:
        return True

    def disabled_reason(self, _item: Any) -> str:
        return "disabled"

    def mapping_status_snapshot(self) -> dict[str, str]:
        return {"text": "active", "role": "ok"}


def _job(*, output: list[str] | None = None) -> dict[str, Any]:
    return {
        "title": "Run product build",
        "item_label": "Run product build",
        "output": deque(output or [], maxlen=1000),
        "process": None,
    }


class MainPanelsControllerTests(unittest.TestCase):
    def test_scroll_logs_reports_missing_log(self) -> None:
        port = FakePanelPort()

        panels.main_panels_controller().scroll_logs(port, 1)

        self.assertEqual(port.status, "No log for selected action")

    def test_draw_logs_panel_renders_output_and_counter(self) -> None:
        port = FakePanelPort()
        port.last_job = _job(output=["line 1", "line 2"])

        panels.main_panels_controller().draw_logs_panel(port, 0, 0, 10, 80, port.items[0])

        rendered = [row[2] for row in port.rows]
        self.assertIn("Run product build [DONE]", rendered)
        self.assertIn("line 1", rendered)
        self.assertIn("line 2", rendered)
        self.assertTrue(any("lines 1-2/2 follow" in text for text in rendered))

    def test_draw_details_panel_renders_mapping_and_last_exit(self) -> None:
        port = FakePanelPort()

        panels.main_panels_controller().draw_details_panel(port, 0, 0, 12, 100, port.items[0])

        rendered = [row[2] for row in port.rows]
        self.assertTrue(any("Selected mappings: meta" in text for text in rendered))
        self.assertTrue(any("Pre-build sync: active" in text for text in rendered))
        self.assertTrue(any("Last exit: 0" in text for text in rendered))

    def test_draw_header_renders_configured_state(self) -> None:
        port = FakePanelPort()

        panels.main_panels_controller().draw_header(port, 120, app_dir=Path("/tmp"))

        rendered = [row[2] for row in port.rows]
        self.assertTrue(any("Build host:" in text for text in rendered))
        self.assertTrue(any("Board host:" in text for text in rendered))
        self.assertTrue(any("full_ufs.img.gz" in text for text in rendered))
        self.assertTrue(any("Preflight: ssh ok" in text for text in rendered))

    def test_draw_actions_panel_renders_selected_item(self) -> None:
        port = FakePanelPort()
        menu_rows = [("BUILD COMMANDS", None), ("1. Run product build", 0)]

        panels.main_panels_controller().draw_actions_panel(
            port,
            3,
            10,
            40,
            menu_rows=menu_rows,
            menu_visible_rows=8,
            running_jobs=[],
        )

        self.assertTrue(any(row[2].strip() == "1. Run product build" for row in port.rows))

    def test_draw_footer_renders_status(self) -> None:
        port = FakePanelPort()
        port.status = "Ready"

        footer = panels.main_panels_controller().draw_footer(port, 20, 100, active_job_exists=False)

        rendered = [row[2] for row in port.rows]
        self.assertIn("Ready".ljust(100), rendered)
        self.assertTrue(footer.startswith("Left/Right panel"))


if __name__ == "__main__":
    unittest.main()
