from __future__ import annotations

import curses
import tempfile
import unittest
from pathlib import Path
from typing import Any

from components.project_mapping_ui.api import screen


class FakeScreen:
    def __init__(self, keys: list[int], *, height: int = 30, width: int = 120) -> None:
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


class FakeProjectPort:
    def __init__(self, keys: list[int]) -> None:
        self.screen = FakeScreen(keys)
        self.status = ""
        self.rows: list[tuple[int, int, str, int | None]] = []
        self.boxes: list[tuple[int, int, int, int, str]] = []
        self.confirm_result = True
        self.prompts: list[tuple[str, str]] = []

    def read_key(self) -> int:
        if not self.screen.keys:
            raise AssertionError("fake key queue is empty")
        return self.screen.keys.pop(0)

    def add(self, row: int, col: int, text: str, attr: int | None = None) -> None:
        self.rows.append((row, col, text, attr))

    def draw_box(self, top: int, left: int, height: int, width: int, title: str) -> None:
        self.boxes.append((top, left, height, width, title))

    def draw_scrollbar(self, *_args: Any) -> None:
        return None

    def draw_wrapped(self, row: int, _col: int, _width: int, text: str, _attr: int = 0, *, max_lines: int = 3) -> int:
        return row + min(max(1, len(text) // 80 + 1), max_lines)

    def draw_label_value_wrapped(self, row: int, _col: int, _width: int, _label: str, value: str, *, max_lines: int = 3) -> int:
        return row + min(max(1, len(value) // 80 + 1), max_lines)

    def selected_attr(self) -> int:
        return 1

    def accent_attr(self) -> int:
        return 2

    def warn_attr(self) -> int:
        return 3

    def error_attr(self) -> int:
        return 4

    def confirm_sync_action(self, _label: str, _description: str) -> bool:
        return self.confirm_result

    def prompt(self, label: str, current: str = "") -> str:
        self.prompts.append((label, current))
        return current


def config_with_mappings(app_dir: Path, mappings: list[dict[str, Any]], active: list[str] | None = None) -> dict[str, Any]:
    return {
        "inventory": {"mapping_selection": str(app_dir / "mapping-selection.txt")},
        "local": {"project_dir": str(app_dir / "overlay")},
        "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
        "active_remote": "build",
        "projects": [
            {
                "name": "prod",
                "project_dir": "meta-product",
                "active_mappings": list(active or []),
                "mappings": mappings,
            }
        ],
        "active_project": "prod",
    }


class ProjectScreenControllerTests(unittest.TestCase):
    def test_add_mapping_screen_toggles_current_remote_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            port = FakeProjectPort([ord(" "), ord("q")])
            saved: list[dict[str, Any]] = []
            config = config_with_mappings(app_dir, [])

            screen.run_add_mapping_screen(
                port,
                config,
                app_dir,
                fetch_project_listing=lambda _current_dir: [{"path": "layers/meta", "kind": "directory"}],
                save_config=saved.append,
            )

            mappings = config["projects"][0]["mappings"]
            self.assertEqual([mapping["name"] for mapping in mappings], ["layers-meta"])
            self.assertEqual(config["projects"][0]["active_mappings"], ["layers-meta"])
            self.assertEqual(len(saved), 2)
            self.assertIn("Mapping added", port.status)

    def test_project_mapping_screen_controller_owns_add_mapping_screen(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            port = FakeProjectPort([ord(" "), ord("q")])
            saved: list[dict[str, Any]] = []
            config = config_with_mappings(app_dir, [])
            controller = screen.project_mapping_screen_controller()

            controller.run_add_mapping_screen(
                port,
                config,
                app_dir,
                fetch_project_listing=lambda _current_dir: [{"path": "layers/meta", "kind": "directory"}],
                save_config=saved.append,
            )

            mappings = config["projects"][0]["mappings"]
            self.assertEqual([mapping["name"] for mapping in mappings], ["layers-meta"])
            self.assertEqual(config["projects"][0]["active_mappings"], ["layers-meta"])
            self.assertEqual(len(saved), 2)
            self.assertIn("Mapping added", port.status)

    def test_delete_mapping_screen_removes_mapping_after_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            port = FakeProjectPort([10])
            saved: list[dict[str, Any]] = []
            config = config_with_mappings(
                app_dir,
                [{"name": "meta", "remote": "layers/meta", "local": "layers/meta", "kind": "directory", "push": True}],
                active=["meta"],
            )

            screen.run_delete_mapping_screen(port, config, app_dir, save_config=saved.append)

            self.assertEqual(config["projects"][0]["mappings"], [])
            self.assertEqual(config["projects"][0]["active_mappings"], [])
            self.assertEqual(len(saved), 2)
            self.assertIn("Mapping deleted", port.status)

    def test_project_mapping_screen_controller_owns_delete_mapping_screen(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            port = FakeProjectPort([ord("d")])
            saved: list[dict[str, Any]] = []
            config = config_with_mappings(
                app_dir,
                [{"name": "meta", "remote": "layers/meta", "local": "layers/meta", "kind": "directory", "push": True}],
                active=["meta"],
            )
            controller = screen.project_mapping_screen_controller()

            controller.run_delete_mapping_screen(port, config, app_dir, save_config=saved.append)

            self.assertEqual(config["projects"][0]["mappings"], [])
            self.assertEqual(config["projects"][0]["active_mappings"], [])
            self.assertEqual(len(saved), 2)
            self.assertIn("Mapping deleted", port.status)

    def test_select_mappings_screen_toggles_active_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            port = FakeProjectPort([ord(" "), ord("q")])
            saved: list[dict[str, Any]] = []
            config = config_with_mappings(
                app_dir,
                [{"name": "meta", "remote": "layers/meta", "local": "layers/meta", "kind": "directory", "push": True}],
            )

            screen.run_select_mappings_screen(
                port,
                config,
                app_dir,
                save_config=saved.append,
                add_mapping_screen=lambda: None,
            )

            self.assertEqual(config["projects"][0]["active_mappings"], ["meta"])
            self.assertEqual(len(saved), 1)
            self.assertEqual(port.status, "Activate mappings closed")

    def test_project_mapping_screen_controller_owns_select_mappings_screen(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            port = FakeProjectPort([ord("a"), ord("q")])
            saved: list[dict[str, Any]] = []
            config = config_with_mappings(
                app_dir,
                [
                    {"name": "one", "remote": "one", "local": "one", "kind": "directory", "push": True},
                    {"name": "two", "remote": "two", "local": "two", "kind": "directory", "push": True},
                ],
            )
            controller = screen.project_mapping_screen_controller()

            controller.run_select_mappings_screen(
                port,
                config,
                app_dir,
                save_config=saved.append,
                add_mapping_screen=lambda: None,
            )

            self.assertEqual(set(config["projects"][0]["active_mappings"]), {"one", "two"})
            self.assertEqual(len(saved), 1)
            self.assertEqual(port.status, "Activate mappings closed")

    def test_select_mappings_empty_state_can_open_add_mapping_screen(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            port = FakeProjectPort([ord("a"), ord("q")])
            add_calls: list[bool] = []
            config = config_with_mappings(app_dir, [])

            screen.run_select_mappings_screen(
                port,
                config,
                app_dir,
                save_config=lambda _config: None,
                add_mapping_screen=lambda: add_calls.append(True),
            )

            self.assertEqual(add_calls, [True])
            self.assertEqual(port.status, "Activate mappings closed")
            self.assertEqual(port.screen.timeouts[-1], 250)


if __name__ == "__main__":
    unittest.main()
