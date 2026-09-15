from __future__ import annotations

import curses
import tempfile
import unittest
from pathlib import Path
from typing import Any

from components.sync.api import screen


class FakeScreen:
    def __init__(self, keys: list[int], *, height: int = 30, width: int = 120) -> None:
        self.keys = keys
        self.height = height
        self.width = width
        self.timeouts: list[int] = []
        self.refresh_count = 0
        self.erase_count = 0

    def timeout(self, value: int) -> None:
        self.timeouts.append(value)

    def erase(self) -> None:
        self.erase_count += 1

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def refresh(self) -> None:
        self.refresh_count += 1


class FakeSyncPort:
    def __init__(self, keys: list[int]) -> None:
        self.screen = FakeScreen(keys)
        self.status = ""
        self.rows: list[tuple[int, int, str, int | None]] = []
        self.boxes: list[tuple[int, int, int, int, str]] = []
        self.messages: list[tuple[str, list[str]]] = []

    def read_key(self) -> int:
        if not self.screen.keys:
            raise AssertionError("fake key queue is empty")
        return self.screen.keys.pop(0)

    def add(self, row: int, col: int, text: str, attr: int | None = None) -> None:
        self.rows.append((row, col, text, attr))

    def draw_box(self, top: int, left: int, height: int, width: int, title: str) -> None:
        self.boxes.append((top, left, height, width, title))

    def draw_wrapped(self, row: int, _col: int, _width: int, text: str, *, max_lines: int = 3) -> int:
        return row + min(max(1, len(text) // 80 + 1), max_lines)

    def selected_attr(self) -> int:
        return 1

    def disabled_attr(self) -> int:
        return 2

    def accent_attr(self) -> int:
        return 3

    def warn_attr(self) -> int:
        return 4

    def confirm_sync_action(self, _label: str, _description: str) -> bool:
        return True

    def show_message(self, title: str, lines: list[str]) -> None:
        self.messages.append((title, lines))


class FakeSyncActionController:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []

    def run_action_result(self, _port: Any, result: dict[str, Any]) -> None:
        self.results.append(result)


def sync_config(app_dir: Path) -> dict[str, Any]:
    local_base = app_dir / "overlay"
    (local_base / "layers/meta").mkdir(parents=True)
    return {
        "inventory": {"mapping_selection": str(app_dir / "mapping-selection.txt")},
        "local": {"project_dir": str(local_base)},
        "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
        "active_remote": "build",
        "projects": [
            {
                "name": "prod",
                "project_dir": "meta-product",
                "active_mappings": ["meta"],
                "mappings": [{"name": "meta", "remote": "layers/meta", "local": "layers/meta"}],
            }
        ],
        "active_project": "prod",
    }


class SyncScreenControllerTests(unittest.TestCase):
    def test_run_sync_screen_quits_on_q(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            port = FakeSyncPort([ord("q")])

            screen.run_sync_screen(
                port,
                sync_config(Path(tmpdir)),
                Path(tmpdir),
                connected=lambda: False,
                action_controller=FakeSyncActionController(),
            )

            self.assertEqual(port.screen.timeouts[-1], 250)

    def test_run_sync_screen_blocks_remote_action_when_disconnected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            port = FakeSyncPort([10, ord("q")])

            action_controller = FakeSyncActionController()
            screen.run_sync_screen(
                port,
                sync_config(Path(tmpdir)),
                Path(tmpdir),
                connected=lambda: False,
                action_controller=action_controller,
            )

            self.assertEqual(port.status, "Connect to the build host first")
            self.assertEqual(action_controller.results, [])

    def test_run_sync_screen_runs_selected_mapping_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            port = FakeSyncPort([curses.KEY_DOWN, curses.KEY_DOWN, curses.KEY_DOWN, curses.KEY_DOWN, 10])
            action_controller = FakeSyncActionController()

            screen.run_sync_screen(
                port,
                sync_config(Path(tmpdir)),
                Path(tmpdir),
                connected=lambda: True,
                action_controller=action_controller,
            )

            self.assertEqual(len(action_controller.results), 1)
            result = action_controller.results[0]
            self.assertEqual(result["kind"], "run-commands")
            title = result["title"]
            argv = result["commands"]
            self.assertEqual(title, "Push selected mappings dry-run")
            self.assertEqual(len(argv), 1)
            self.assertIn("--dry-run", argv[0])
            self.assertEqual(port.screen.timeouts[-1], 250)

    def test_run_sync_screen_uses_injected_action_controller(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            port = FakeSyncPort([curses.KEY_DOWN, curses.KEY_DOWN, curses.KEY_DOWN, curses.KEY_DOWN, 10])
            action_controller = FakeSyncActionController()

            screen.run_sync_screen(
                port,
                sync_config(Path(tmpdir)),
                Path(tmpdir),
                connected=lambda: True,
                action_controller=action_controller,
            )

            self.assertEqual(len(action_controller.results), 1)
            self.assertEqual(action_controller.results[0]["kind"], "run-commands")
            self.assertEqual(action_controller.results[0]["title"], "Push selected mappings dry-run")
            self.assertEqual(port.screen.timeouts[-1], 250)


if __name__ == "__main__":
    unittest.main()
