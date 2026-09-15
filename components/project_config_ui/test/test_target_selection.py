from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from components.project_config_ui.api import target_selection


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


class FakeTargetPort:
    def __init__(self, keys: list[int]) -> None:
        self.screen = FakeScreen(keys)
        self.status = ""
        self.build_params = {"ENABLE_ANDROID": "yes"}
        self.build_targets = "boot"
        self.docker_image = "builder:latest"
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
        return 1

    def accent_attr(self) -> int:
        return 2

    def warn_attr(self) -> int:
        return 3


def config() -> dict[str, Any]:
    return {
        "moulin": {"manifest": "product.yaml"},
        "projects": [
            {
                "name": "prod",
                "targets": "boot",
                "board_artifacts": "",
            }
        ],
        "active_project": "prod",
    }


def candidates(_build_params: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"target": "boot", "source": "manifest", "desc": "Boot artifacts"},
        {"target": "full", "source": "manifest", "desc": "Full image"},
    ]


class TargetSelectionControllerTests(unittest.TestCase):
    def test_select_build_targets_saves_targets_and_runtime_settings(self) -> None:
        port = FakeTargetPort([ord("j"), ord(" "), 10])
        saved: list[dict[str, Any]] = []
        reloaded: list[bool] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            controller = target_selection.TargetSelectionController(
                config(),
                target_candidates=candidates,
                app_dir=Path(tmpdir),
                default_config_path=Path(tmpdir) / "config.json",
                save_config=saved.append,
            )

            with patch("components.project_config_ui.src.target_selection.config_runtime_api.save_current_runtime_build_settings") as save_runtime:
                controller.select_build_targets(port, reload_runtime=lambda: reloaded.append(True))

        self.assertEqual(port.build_targets, "boot full")
        self.assertEqual(saved[0]["projects"][0]["targets"], "boot full")
        self.assertEqual(reloaded, [True])
        self.assertEqual(port.status, "Build target selection saved")
        save_runtime.assert_called_once()

    def test_select_board_artifacts_saves_active_project_artifacts(self) -> None:
        port = FakeTargetPort([ord("j"), ord(" "), 10])
        saved: list[dict[str, Any]] = []
        reloaded: list[bool] = []
        controller = target_selection.TargetSelectionController(
            config(),
            target_candidates=candidates,
            app_dir=Path("/tmp"),
            default_config_path=Path("/tmp/config.json"),
            save_config=saved.append,
        )

        controller.select_board_artifacts(port, reload_runtime=lambda: reloaded.append(True))

        self.assertEqual(port.build_targets, "boot")
        self.assertEqual(saved[0]["projects"][0]["board_artifacts"], "boot full")
        self.assertEqual(reloaded, [True])
        self.assertEqual(port.status, "Board artifact selection saved")

    def test_select_targets_cancel_sets_cancel_status_and_returns_none(self) -> None:
        port = FakeTargetPort([ord("q")])
        controller = target_selection.TargetSelectionController(
            config(),
            target_candidates=candidates,
            app_dir=Path("/tmp"),
            default_config_path=Path("/tmp/config.json"),
            save_config=lambda _config: None,
        )

        result = controller.select_targets(
            port,
            title="Build Targets",
            selected_text=port.build_targets,
            default_text=port.build_targets,
            build_params=port.build_params,
            empty_message="No build targets found in Moulin manifest.",
            saved_status="saved",
            cancelled_status="cancelled",
        )

        self.assertIsNone(result)
        self.assertEqual(port.status, "cancelled")
        self.assertEqual(port.screen.timeouts[-1], 250)


if __name__ == "__main__":
    unittest.main()
