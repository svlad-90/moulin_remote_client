from __future__ import annotations

import curses
import tempfile
import unittest
from pathlib import Path
from typing import Any

from components.project_config_ui.api import project_picker


class FakePickerScreen:
    def __init__(self, keys: list[int], *, height: int = 20, width: int = 90) -> None:
        self.keys = keys
        self.height = height
        self.width = width
        self.timeouts: list[int] = []
        self.erase_count = 0
        self.refresh_count = 0

    def timeout(self, value: int) -> None:
        self.timeouts.append(value)

    def erase(self) -> None:
        self.erase_count += 1

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def refresh(self) -> None:
        self.refresh_count += 1


class FakePickerPort:
    def __init__(self, keys: list[int], *, height: int = 20, width: int = 90) -> None:
        self.screen = FakePickerScreen(keys, height=height, width=width)
        self.status = ""
        self.rows: list[tuple[int, int, str, int | None]] = []
        self.boxes: list[tuple[int, int, int, int, str]] = []

    def read_key(self) -> int:
        if not self.screen.keys:
            raise AssertionError("fake key queue is empty")
        return self.screen.keys.pop(0)

    def add(self, row: int, col: int, text: str, attr: int | None = None) -> None:
        self.rows.append((row, col, text, attr))

    def draw_box(self, top: int, left: int, height: int, width: int, title: str) -> None:
        self.boxes.append((top, left, height, width, title))

    def selected_attr(self) -> int:
        return 2

    def accent_attr(self) -> int:
        return 4

    def warn_attr(self) -> int:
        return 6


def config_with_projects() -> dict[str, Any]:
    return {
        "projects": [
            {"name": "prod", "label": "Prod"},
            {"name": "sdk", "label": "SDK"},
        ],
        "active_project": "prod",
    }


class ProjectPickerControllerTests(unittest.TestCase):
    def test_select_project_moves_selection_and_saves_selected_project(self) -> None:
        cfg = config_with_projects()
        port = FakePickerPort([curses.KEY_DOWN, 10])
        saved: list[dict[str, Any]] = []
        reload_count = 0

        def reload_runtime() -> None:
            nonlocal reload_count
            reload_count += 1

        project_picker.ProjectPickerController(
            cfg,
            app_dir=Path("/app"),
            default_build_targets="image",
            default_moulin_manifest="product.yaml",
            default_dockerfile="doc/Dockerfile",
            save_config=saved.append,
        ).select_project(port, reload_runtime=reload_runtime)

        self.assertEqual(cfg["active_project"], "sdk")
        self.assertEqual(port.status, "Active project: SDK")
        self.assertEqual(len(saved), 1)
        self.assertEqual(reload_count, 1)
        self.assertEqual(port.screen.timeouts, [-1])

    def test_select_project_quit_leaves_active_project_unchanged(self) -> None:
        cfg = config_with_projects()
        port = FakePickerPort([ord("q")])
        saved: list[dict[str, Any]] = []

        project_picker.ProjectPickerController(
            cfg,
            app_dir=Path("/app"),
            default_build_targets="image",
            default_moulin_manifest="product.yaml",
            default_dockerfile="doc/Dockerfile",
            save_config=saved.append,
        ).select_project(port, reload_runtime=lambda: None)

        self.assertEqual(cfg["active_project"], "prod")
        self.assertEqual(saved, [])

    def test_select_project_handles_small_terminal_until_quit(self) -> None:
        cfg = config_with_projects()
        port = FakePickerPort([ord("q")], height=10, width=60)

        project_picker.ProjectPickerController(
            cfg,
            app_dir=Path("/app"),
            default_build_targets="image",
            default_moulin_manifest="product.yaml",
            default_dockerfile="doc/Dockerfile",
            save_config=lambda _config: None,
        ).select_project(port, reload_runtime=lambda: None)

        self.assertIn("Terminal is too small", port.rows[0][2])
        self.assertEqual(cfg["active_project"], "prod")

    def test_select_project_normalizes_missing_project_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg: dict[str, Any] = {}
            port = FakePickerPort([ord("q")])

            project_picker.ProjectPickerController(
                cfg,
                app_dir=Path(tmpdir),
                default_build_targets="image",
                default_moulin_manifest="product.yaml",
                default_dockerfile="doc/Dockerfile",
                save_config=lambda _config: None,
            ).select_project(port, reload_runtime=lambda: None)

        self.assertTrue(cfg["projects"])
        self.assertEqual(cfg["active_project"], cfg["projects"][0]["name"])


if __name__ == "__main__":
    unittest.main()
