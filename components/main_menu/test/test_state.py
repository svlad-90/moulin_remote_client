from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from components.main_menu.api import state
from components.ui.api.menu import MenuItem


class FakePort:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.preflight_values: dict[str, str] = {}
        self.active_job: dict[str, Any] | None = None
        self.board_job: dict[str, Any] | None = None
        self.connection_state = "connected"
        self.board_connection_state = "connected"


def _item(label: str, *, requires_remote: bool = False, requires_project: bool = False) -> MenuItem:
    return MenuItem(
        label,
        "build commands",
        "description",
        lambda _port: "",
        lambda _port: None,
        requires_remote=requires_remote,
        requires_project=requires_project,
    )


def _config(app_dir: Path) -> dict[str, Any]:
    return {
        "inventory": {"mapping_selection": str(app_dir / "selected.txt")},
        "local": {"project_dir": str(app_dir / "overlay")},
        "active_remote": "build",
        "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/work"}],
        "active_board_host": "board",
        "board_hosts": [{"name": "board", "user": "tester", "host": "10.0.0.2"}],
        "active_project": "prod",
        "projects": [
            {
                "name": "prod",
                "git_url": "https://example.invalid/prod.git",
                "git_ref": "main",
                "local_project_dir": str(app_dir / "overlay"),
                "project_dir": "prod",
            }
        ],
    }


class MainMenuStateControllerTests(unittest.TestCase):
    def test_item_enabled_uses_preflight_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            port = FakePort(_config(app_dir))
            port.preflight_values = {"project": "missing", "origin": "missing", "ref": "ok"}
            controller = state.main_menu_state_controller(app_dir=app_dir)

            self.assertFalse(controller.item_enabled(port, _item("Run product build", requires_remote=True, requires_project=True)))
            self.assertTrue(controller.item_enabled(port, _item("Prepare remote project", requires_remote=True, requires_project=True)))

    def test_disabled_reason_describes_missing_build_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            port = FakePort(_config(app_dir))
            port.connection_state = "disconnected"
            controller = state.main_menu_state_controller(app_dir=app_dir)

            reason = controller.disabled_reason(port, _item("Run product build", requires_remote=True, requires_project=True))

            self.assertEqual(reason, "connect to the build host first")

    def test_mapping_status_snapshot_resolves_selection_and_local_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            port = FakePort(_config(app_dir))
            controller = state.main_menu_state_controller(app_dir=app_dir)
            mapping = {"name": "src", "local": "src", "remote": "src", "push": True}

            with (
                patch("components.project.src.selection.ProjectMappingSelectionService.active_mapping_state_for_config", return_value=(["src"], [mapping], None)) as active_state,
                patch("components.main_menu.src.state.ui_mapping_status.mapping_status_snapshot", return_value={"text": "ok", "role": "ok"}) as snapshot,
            ):
                result = controller.mapping_status_snapshot(port)

            active_state.assert_called_once_with(port.config, app_dir / "selected.txt")
            snapshot.assert_called_once_with(["src"], [mapping], None, local_base=app_dir / "overlay")
            self.assertEqual(result, {"text": "ok", "role": "ok"})


if __name__ == "__main__":
    unittest.main()
